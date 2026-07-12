"""End-to-end tests of handle_message: real SQLite, stubbed Gemini."""

import asyncio

import pytest
from sqlmodel import delete

from shopping_agent import pending, shopping
from shopping_agent.ai_parser import Action, Operation
from shopping_agent.db import get_session, init_db
from shopping_agent.models import ShoppingItem

ME = "41791234567"
WIFE = "41797654321"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Fresh DB and pending store per test; parse_message driven by a dict."""
    init_db()
    with get_session() as s:
        s.exec(delete(ShoppingItem))
        s.commit()
    pending._pending.clear()

    script: dict[str, list[Operation]] = {}

    async def fake_parse(message, current_items):
        return script.get(message, [])

    monkeypatch.setattr(shopping, "parse_message", fake_parse)
    return script


def run(sender: str, msg: str) -> str:
    return asyncio.run(shopping.handle_message(sender, msg))


def items() -> set[tuple]:
    with get_session() as s:
        return {(i.name, i.quantity, i.unit) for i in shopping.list_items(s)}


def test_add_multiple_items(clean_state):
    clean_state["add milk and 2 kg potatoes"] = [
        Operation(action=Action.add, name="Milk"),
        Operation(action=Action.add, name="potatoes", quantity=2, unit="kg"),
    ]
    reply = run(WIFE, "add milk and 2 kg potatoes")
    assert reply == "✓ Added: milk, potatoes (2 kg)"
    assert items() == {("milk", None, None), ("potatoes", 2.0, "kg")}


def test_dedup_no_quantity_reports_already_on_list(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")
    reply = run(WIFE, "add milk")
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
    reply = run(WIFE, "add 3 kg potatoes")
    assert reply == "✓ Updated: potatoes (3 kg)"
    assert items() == {("potatoes", 3.0, "kg")}


def test_list_and_remove(clean_state):
    clean_state["add milk"] = [Operation(action=Action.add, name="milk")]
    run(ME, "add milk")

    clean_state["what's on the list"] = [Operation(action=Action.list)]
    reply = run(WIFE, "what's on the list")
    assert reply.startswith("🛒 Shopping list:")
    assert "milk" in reply

    with get_session() as s:
        milk_id = shopping.list_items(s)[0].id
    clean_state["remove milk"] = [Operation(action=Action.remove, item_id=milk_id)]
    reply = run(WIFE, "remove milk")
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

    # Wife's "yes" has no pending clear -> falls through to the AI (fallback).
    reply = run(WIFE, "yes")
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

    reply = run(WIFE, "how are you?")
    assert reply == shopping.FALLBACK_REPLY
    assert items() == before


def test_clear_on_empty_list(clean_state):
    clean_state["clear the list"] = [Operation(action=Action.clear)]
    reply = run(ME, "clear the list")
    assert reply == "🛒 Your shopping list is already empty."
