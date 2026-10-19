"""End-to-end tests of handle_message: real SQLite, stubbed Gemini."""

import asyncio
import json

import pytest
from sqlmodel import delete, select

from shopping_agent import pending, shopping
from shopping_agent.ai_parser import Action, Operation
from shopping_agent.db import get_session, init_db
from shopping_agent.models import ItemEvent, Message, ShoppingItem

ME = "41791234567"
SECOND_USER = "41797654321"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Fresh DB and pending store per test; parse_message driven by a dict."""
    init_db()
    with get_session() as s:
        s.exec(delete(ShoppingItem))
        s.exec(delete(ItemEvent))
        s.exec(delete(Message))
        s.commit()
    pending._pending.clear()

    script: dict[str, list[Operation]] = {}

    async def fake_parse(message, current_items):
        return script.get(message, [])

    monkeypatch.setattr(shopping, "parse_message", fake_parse)
    return script


def run(sender: str, msg: str) -> str:
    message_id = shopping.record_message(sender, msg)
    return asyncio.run(shopping.handle_message(sender, msg, message_id))


def events() -> list[tuple]:
    with get_session() as s:
        rows = s.exec(select(ItemEvent).order_by(ItemEvent.id)).all()
        return [(e.action, e.item_name, e.quantity, e.unit, e.sender) for e in rows]


def messages() -> list[tuple]:
    with get_session() as s:
        rows = s.exec(select(Message).order_by(Message.id)).all()
        return [(m.text, m.status) for m in rows]


def items() -> set[tuple]:
    with get_session() as s:
        return {(i.name, i.quantity, i.unit) for i in shopping.list_items(s)}


def test_add_multiple_items(clean_state):
    clean_state["add milk and 2 kg potatoes"] = [
        Operation(action=Action.add, name="Milk"),
        Operation(action=Action.add, name="potatoes", quantity=2, unit="kg"),
    ]
    reply = run(SECOND_USER, "add milk and 2 kg potatoes")
    assert reply == "✓ Added: milk, potatoes (2 kg)"
    assert items() == {("milk", None, None), ("potatoes", 2.0, "kg")}


def test_dedup_no_quantity_reports_already_on_list(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    reply = run(SECOND_USER, "add milk")
    assert reply == "Already on the list: milk"
    assert items() == {("milk", None, None)}


def test_dedup_with_quantity_updates_in_place(clean_state):
    clean_state["add 2 kg potatoes"] = [
        Operation(action=Action.add, name="potatoes", quantity=2, unit="kg")
    ]
    clean_state["add 3 kg potatoes"] = [
        Operation(action=Action.add, name="Potatoes", quantity=3, unit="KG")
    ]
    run(ME, "add 2 kg potatoes")
    reply = run(SECOND_USER, "add 3 kg potatoes")
    assert reply == "✓ Updated: potatoes (3 kg)"
    assert items() == {("potatoes", 3.0, "kg")}


def test_list_and_remove(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")

    clean_state["what's on the list"] = [Operation(action=Action.list)]
    reply = run(SECOND_USER, "what's on the list")
    assert reply.startswith("🛒 Shopping list:")
    assert "milk" in reply

    with get_session() as s:
        milk_id = shopping.list_items(s)[0].id
    clean_state["remove milk"] = [Operation(action=Action.remove, item_id=milk_id)]
    reply = run(SECOND_USER, "remove milk")
    assert reply == "✓ Removed: milk"
    assert items() == set()


def test_clear_requires_confirmation(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    run(ME, "add milk")

    reply = run(ME, "clear the list")
    assert reply.startswith("⚠ This will remove all 1 item")
    assert items() != set()  # nothing removed yet

    reply = run(ME, "yes")
    assert reply == "✓ List cleared (1 item removed)."
    assert items() == set()


def test_clear_confirmation_is_per_sender(clean_state):
    clean_state["add bread"] = [Operation(action=Action.add, name="bread")]
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    run(ME, "add bread")
    run(ME, "clear the list")

    # The second user's "yes" has no pending clear -> falls through to the AI.
    reply = run(SECOND_USER, "yes")
    assert reply == shopping.FALLBACK_REPLY
    assert items() == {("bread", None, None)}


def test_any_other_message_cancels_pending_clear(clean_state):
    clean_state["add bread"] = [Operation(action=Action.add, name="bread")]
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    run(ME, "add bread")
    run(ME, "clear the list")
    run(ME, "add milk")  # cancels the pending clear

    reply = run(ME, "yes")
    assert reply == shopping.FALLBACK_REPLY
    assert items() == {("bread", None, None), ("milk", None, None)}


def test_unrecognised_message_changes_nothing(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    before = items()

    reply = run(SECOND_USER, "how are you?")
    assert reply == shopping.FALLBACK_REPLY
    assert items() == before


def test_clear_on_empty_list(clean_state):
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    reply = run(ME, "clear the list")
    assert reply == "🛒 Your shopping list is already empty."


# ─── History ───────────────────────────────────────────────────────────────


def test_history_records_add_update_remove(clean_state):
    clean_state["add 2 kg potatoes"] = [
        Operation(action=Action.add, name="potatoes", quantity=2, unit="kg")
    ]
    clean_state["add 3 kg potatoes"] = [
        Operation(action=Action.add, name="potatoes", quantity=3, unit="kg")
    ]
    run(ME, "add 2 kg potatoes")
    run(SECOND_USER, "add 3 kg potatoes")
    with get_session() as s:
        potato_id = shopping.list_items(s)[0].id
    clean_state["bought potatoes"] = [
        Operation(action=Action.remove, item_id=potato_id)
    ]
    run(ME, "bought potatoes")

    assert events() == [
        ("add", "potatoes", 2.0, "kg", ME),
        ("update", "potatoes", 3.0, "kg", SECOND_USER),
        ("remove", "potatoes", 3.0, "kg", ME),
    ]
    assert [st for _, st in messages()] == ["ok", "ok", "ok"]


def test_history_unchanged_add_writes_no_event(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    run(ME, "add milk")
    assert [e[0] for e in events()] == ["add"]


def test_history_clear_writes_event_per_item(clean_state):
    clean_state["add milk and bread"] = [
        Operation(action=Action.add, name="milk"),
        Operation(action=Action.add, name="bread"),
    ]
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    run(ME, "add milk and bread")
    run(ME, "clear the list")
    run(ME, "yes")

    assert [(e[0], e[1]) for e in events()] == [
        ("add", "milk"),
        ("add", "bread"),
        ("clear", "milk"),
        ("clear", "bread"),
    ]
    assert messages() == [
        ("add milk and bread", "ok"),
        ("clear the list", "confirm_requested"),
        ("yes", "cleared"),
    ]


def test_history_message_stores_reply_and_ops(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    run(ME, "how are you?")

    with get_session() as s:
        ok, fallback = s.exec(select(Message).order_by(Message.id)).all()
    assert ok.reply == "✓ Added: milk"
    assert json.loads(ok.ops_json) == [
        {
            "action": "add",
            "item_id": None,
            "name": "milk",
            "quantity": None,
            "unit": None,
        }
    ]
    assert (fallback.status, fallback.ops_json) == ("fallback", "[]")


def test_history_events_link_to_message(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    with get_session() as s:
        msg = s.exec(select(Message)).one()
        event = s.exec(select(ItemEvent)).one()
    assert event.message_id == msg.id
