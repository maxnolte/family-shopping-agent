"""Webhook → history: messages are stored, failures recorded as errors."""

from fastapi.testclient import TestClient
from sqlmodel import delete, select

from shopping_agent import webhook
from shopping_agent.db import get_session, init_db
from shopping_agent.main import app
from shopping_agent.models import ItemEvent, Message

ME = "41791234567"
STRANGER = "41700000000"


def payload(sender: str, text: str) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": f"{sender}@s.whatsapp.net", "fromMe": False},
            "message": {"conversation": text},
        },
    }


def stored() -> list[tuple]:
    with get_session() as s:
        return [(m.sender, m.text, m.status) for m in s.exec(select(Message))]


def setup_function():
    init_db()
    with get_session() as s:
        s.exec(delete(ItemEvent))
        s.exec(delete(Message))
        s.commit()
    webhook.ratelimit._buckets.clear()


def test_handler_error_is_recorded(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_send(number, text):
        sent.append((number, text))

    async def boom(sender, text, message_id):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(webhook, "send_text", fake_send)
    monkeypatch.setattr(webhook, "handle_message", boom)

    r = TestClient(app).post("/webhook/test-token", json=payload(ME, "add milk"))
    assert r.status_code == 200
    assert stored() == [(ME, "add milk", "error")]
    assert sent == [(ME, "Sorry, something went wrong. Please try again.")]


def test_non_whitelisted_sender_is_not_stored(monkeypatch):
    r = TestClient(app).post("/webhook/test-token", json=payload(STRANGER, "hi"))
    assert r.json() == {"ignored": "sender-not-whitelisted"}
    assert stored() == []
