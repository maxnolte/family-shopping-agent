import logging
import os

import httpx
from fastapi import FastAPI, HTTPException, Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("shopping-agent")

EVOLUTION_BASE_URL = os.environ["EVOLUTION_BASE_URL"].rstrip("/")
EVOLUTION_API_KEY = os.environ["EVOLUTION_API_KEY"]
EVOLUTION_INSTANCE_NAME = os.environ["EVOLUTION_INSTANCE_NAME"]
WEBHOOK_TOKEN = os.environ["WEBHOOK_TOKEN"]
ALLOWED_NUMBERS = {
    n.strip().lstrip("+")
    for n in os.environ["ALLOWED_NUMBERS"].split(",")
    if n.strip()
}

REPLY_TEXT = "Message received, thank you"

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook/{token}")
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

    log.info("message from %s", sender)
    await send_text(sender, REPLY_TEXT)
    return {"ok": True}


async def send_text(number: str, text: str) -> None:
    url = f"{EVOLUTION_BASE_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            json={"number": number, "text": text},
            headers={"apikey": EVOLUTION_API_KEY},
        )
        r.raise_for_status()
