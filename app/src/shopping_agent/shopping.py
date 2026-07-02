"""Shopping-list business logic and message orchestration."""

import logging

from sqlmodel import select

from . import pending
from .ai_parser import Action, parse_message
from .db import get_session
from .models import ShoppingItem

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
) -> ShoppingItem:
    item = ShoppingItem(
        name=name.strip().lower(),
        quantity=quantity,
        unit=(unit.strip() or None) if unit else None,
        added_by=added_by,
    )
    session.add(item)
    return item


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
        return f"{item.name} ({qstr} {item.unit})" if item.unit else f"{item.name} ({qstr})"
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


# ─── Orchestration ─────────────────────────────────────────────────────────


async def handle_message(sender: str, text: str) -> str:
    """Process one inbound message from an authorised sender and return the
    reply text to send back."""
    text = text.strip()
    lower = text.lower()

    # 1. Resolve any pending clear-list confirmation first.
    if pending.has_pending(sender):
        if lower in AFFIRMATIVE:
            count = pending.take_pending(sender)
            if count is not None:
                with get_session() as s:
                    removed = clear_all(s)
                    s.commit()
                return f"✓ List cleared ({removed} item{_plural(removed)} removed)."
        else:
            # Any other message cancels the pending clear, then is processed
            # normally below.
            pending.clear_pending(sender)

    # 2. Ask the AI to turn the message into operations.
    with get_session() as s:
        current = list_items(s)
    ops = await parse_message(text, current)

    if not ops:
        return FALLBACK_REPLY

    # 3. A clear request short-circuits into the two-step confirmation flow.
    if any(op.action == Action.clear for op in ops):
        count = len(current)
        if count == 0:
            return "🛒 Your shopping list is already empty."
        pending.set_pending(sender, count)
        return (
            f"⚠ This will remove all {count} item{_plural(count)}. "
            "Reply 'yes' within 2 minutes to confirm."
        )

    # 4. Apply add / remove / list operations.
    added: list[str] = []
    removed: list[str] = []
    want_list = False

    with get_session() as s:
        for op in ops:
            if op.action == Action.add and op.name:
                item = add_item(s, sender, op.name, op.quantity, op.unit)
                added.append(format_item(item))
            elif op.action == Action.remove and op.item_id is not None:
                item = remove_item(s, op.item_id)
                if item is not None:
                    removed.append(format_item(item))
            elif op.action == Action.list:
                want_list = True
        s.commit()
        list_str = format_full_list(list_items(s)) if want_list else None

    parts: list[str] = []
    if added:
        parts.append("✓ Added: " + ", ".join(added))
    if removed:
        parts.append("✓ Removed: " + ", ".join(removed))
    if list_str is not None:
        parts.append(list_str)

    if not parts:
        return "I couldn't act on that — nothing on the list matched."
    return "\n".join(parts)
