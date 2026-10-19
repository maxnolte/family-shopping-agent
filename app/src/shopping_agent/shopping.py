"""Shopping-list business logic and message orchestration."""

import json
import logging

from sqlmodel import select

from . import pending
from .ai_parser import Action, Operation, parse_message
from .db import get_session
from .models import ItemEvent, Message, ShoppingItem

log = logging.getLogger("shopping-agent.shopping")

AFFIRMATIVE = {"yes", "y", "confirm", "ja", "yep", "yeah"}

FALLBACK_REPLY = (
    'Sorry, I didn\'t understand that. Try e.g. "add milk and 2 kg potatoes", '
    '"remove milk", "what\'s on the list" or "clear the list".'
)


# ─── CRUD helpers ──────────────────────────────────────────────────────────


def list_items(session) -> list[ShoppingItem]:
    return list(session.exec(select(ShoppingItem).order_by(ShoppingItem.id)).all())


def add_item(
    session, added_by: str, name: str, quantity: float | None, unit: str | None
) -> tuple[ShoppingItem, bool]:
    """Add an item, deduplicating by name: if the item is already on the list,
    update its quantity/unit (when the new op provides a quantity) instead of
    creating a duplicate row. Returns (item, created)."""
    name = name.strip().lower()
    unit = (unit.strip().lower() or None) if unit else None

    existing = session.exec(
        select(ShoppingItem).where(ShoppingItem.name == name)
    ).first()
    if existing is not None:
        if quantity is not None:
            existing.quantity = quantity
            existing.unit = unit
            session.add(existing)
        return existing, False

    item = ShoppingItem(
        name=name,
        quantity=quantity,
        unit=unit,
        added_by=added_by,
    )
    session.add(item)
    return item, True


def remove_item(session, item_id: int) -> ShoppingItem | None:
    item = session.get(ShoppingItem, item_id)
    if item is not None:
        session.delete(item)
    return item


def clear_all(session) -> int:
    items = list_items(session)
    for it in items:
        session.delete(it)
    return len(items)


# ─── Formatting ────────────────────────────────────────────────────────────


def _fmt_qty(qty: float) -> str:
    return str(int(qty)) if float(qty).is_integer() else str(qty)


def format_item(item: ShoppingItem) -> str:
    if item.quantity is not None:
        qstr = _fmt_qty(item.quantity)
        if item.unit:
            return f"{item.name} ({qstr} {item.unit})"
        return f"{item.name} ({qstr})"
    if item.unit:
        return f"{item.name} ({item.unit})"
    return item.name


def format_full_list(items: list[ShoppingItem]) -> str:
    if not items:
        return "🛒 Your shopping list is empty."
    lines = ["🛒 Shopping list:"]
    lines += [f"• {format_item(it)}" for it in items]
    return "\n".join(lines)


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


# ─── History ───────────────────────────────────────────────────────────────


def record_message(sender: str, text: str) -> int:
    """Store an inbound message on receipt and return its id."""
    with get_session() as s:
        msg = Message(sender=sender, text=text)
        s.add(msg)
        s.commit()
        return msg.id


def finish_message(
    message_id: int, status: str, reply: str, ops: list[Operation] | None = None
) -> None:
    """Complete a stored message with its outcome, reply and parsed ops."""
    with get_session() as s:
        msg = s.get(Message, message_id)
        if msg is None:
            return
        msg.status = status
        msg.reply = reply
        if ops is not None:
            msg.ops_json = json.dumps([op.model_dump(mode="json") for op in ops])
        s.add(msg)
        s.commit()


def _event(message_id: int, sender: str, action: str, item: ShoppingItem) -> ItemEvent:
    return ItemEvent(
        message_id=message_id,
        sender=sender,
        action=action,
        item_name=item.name,
        quantity=item.quantity,
        unit=item.unit,
    )


# ─── Orchestration ─────────────────────────────────────────────────────────


async def handle_message(sender: str, text: str, message_id: int) -> str:
    """Process one inbound message from an authorised sender, record the outcome
    on its stored Message row, and return the reply text to send back."""
    reply, status, ops = await _process(sender, text, message_id)
    finish_message(message_id, status, reply, ops)
    return reply


async def _process(
    sender: str, text: str, message_id: int
) -> tuple[str, str, list[Operation] | None]:
    """Returns (reply, status, parsed ops). List changes and their ItemEvents
    are committed together."""
    text = text.strip()
    lower = text.lower()

    # 1. Resolve any pending clear-list confirmation first.
    if pending.has_pending(sender):
        if lower in AFFIRMATIVE:
            count = pending.take_pending(sender)
            if count is not None:
                with get_session() as s:
                    for it in list_items(s):
                        s.add(_event(message_id, sender, "clear", it))
                    removed = clear_all(s)
                    s.commit()
                log.info("action=clear count=%d by=%s", removed, sender)
                reply = f"✓ List cleared ({removed} item{_plural(removed)} removed)."
                return reply, "cleared", None
        else:
            # Any other message cancels the pending clear, then is processed
            # normally below.
            pending.clear_pending(sender)

    # 2. Ask the AI to turn the message into operations.
    with get_session() as s:
        current = list_items(s)
    ops = await parse_message(text, current)

    if not ops:
        return FALLBACK_REPLY, "fallback", ops

    # 3. A clear request short-circuits into the two-step confirmation flow.
    if any(op.action == Action.clear for op in ops):
        count = len(current)
        if count == 0:
            return "🛒 Your shopping list is already empty.", "ok", ops
        pending.set_pending(sender, count)
        log.info("action=clear-requested count=%d by=%s", count, sender)
        reply = (
            f"⚠ This will remove all {count} item{_plural(count)}. "
            "Reply 'yes' within 2 minutes to confirm."
        )
        return reply, "confirm_requested", ops

    # 4. Apply add / remove / list operations.
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []
    want_list = False

    with get_session() as s:
        for op in ops:
            if op.action == Action.add and op.name:
                item, created = add_item(s, sender, op.name, op.quantity, op.unit)
                if created:
                    added.append(format_item(item))
                    s.add(_event(message_id, sender, "add", item))
                    log.info("action=add item=%s by=%s", item.name, sender)
                elif op.quantity is not None:
                    updated.append(format_item(item))
                    s.add(_event(message_id, sender, "update", item))
                    log.info("action=update item=%s by=%s", item.name, sender)
                else:
                    unchanged.append(item.name)
            elif op.action == Action.remove and op.item_id is not None:
                item = remove_item(s, op.item_id)
                if item is not None:
                    removed.append(format_item(item))
                    s.add(_event(message_id, sender, "remove", item))
                    log.info("action=remove item=%s by=%s", item.name, sender)
            elif op.action == Action.list:
                want_list = True
                log.info("action=list by=%s", sender)
        s.commit()
        list_str = format_full_list(list_items(s)) if want_list else None

    parts: list[str] = []
    if added:
        parts.append("✓ Added: " + ", ".join(added))
    if updated:
        parts.append("✓ Updated: " + ", ".join(updated))
    if unchanged:
        parts.append("Already on the list: " + ", ".join(unchanged))
    if removed:
        parts.append("✓ Removed: " + ", ".join(removed))
    if list_str is not None:
        parts.append(list_str)

    if not parts:
        return "I couldn't act on that — nothing on the list matched.", "no_match", ops
    return "\n".join(parts), "ok", ops
