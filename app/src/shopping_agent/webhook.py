import logging
import os

from fastapi import APIRouter, HTTPException, Request

from . import ratelimit
from .shopping import handle_message
from .whatsapp import send_text

log = logging.getLogger("shopping-agent.webhook")

WEBHOOK_TOKEN = os.environ["WEBHOOK_TOKEN"]
ALLOWED_NUMBERS = {
    n.strip().lstrip("+")
    for n in os.environ["ALLOWED_NUMBERS"].split(",")
    if n.strip()
}

router = APIRouter()


def _extract_text(message: dict) -> str:
    """Pull plain text out of an Evolution messages.upsert payload."""
    return (
        message.get("conversation")
        or (message.get("extendedTextMessage") or {}).get("text")
        or ""
    )


@router.post("/webhook/{token}")
async def webhook(token: str, request: Request) -> dict[str, str | bool]:
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=404)

    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data") or {}
    key = data.get("key") or {}

    if event != "messages.upsert":
        return {"ignored": f"event:{event}"}
    if key.get("fromMe"):
        return {"ignored": "fromMe"}

    remote_jid: str = key.get("remoteJid", "")
    # Individual chats end in @s.whatsapp.net; groups end in @g.us.
    if not remote_jid.endswith("@s.whatsapp.net"):
        return {"ignored": "non-individual-chat"}

    sender = remote_jid.split("@", 1)[0]
    if sender not in ALLOWED_NUMBERS:
        log.warning("rejected message from %s", sender)
        return {"ignored": "sender-not-whitelisted"}

    if not ratelimit.allow(sender):
        log.warning("rate-limited %s", sender)
        return {"ignored": "rate-limited"}

    text = _extract_text(data.get("message") or {})
    if not text.strip():
        return {"ignored": "no-text"}

    log.info("message from %s", sender)
    try:
        reply = await handle_message(sender, text)
    except Exception:
        log.exception("handler failed for %s", sender)
        reply = "Sorry, something went wrong. Please try again."

    await send_text(sender, reply)
    return {"ok": True}
