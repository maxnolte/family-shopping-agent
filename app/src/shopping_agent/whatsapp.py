"""Evolution API client: send WhatsApp messages."""

import os

import httpx

EVOLUTION_BASE_URL = os.environ["EVOLUTION_BASE_URL"].rstrip("/")
EVOLUTION_API_KEY = os.environ["EVOLUTION_API_KEY"]
EVOLUTION_INSTANCE_NAME = os.environ["EVOLUTION_INSTANCE_NAME"]


async def send_text(number: str, text: str) -> None:
    url = f"{EVOLUTION_BASE_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            json={"number": number, "text": text},
            headers={"apikey": EVOLUTION_API_KEY},
        )
        r.raise_for_status()
