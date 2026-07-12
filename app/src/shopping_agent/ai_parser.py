"""Gemini-backed intent parser.

Takes the current shopping list plus an incoming message and returns a list of
operations. The AI provider is isolated to this module so it can be swapped
(see PLAN.md) without touching the rest of the app.
"""

import json
import logging
import os
from enum import StrEnum

from google import genai
from google.genai import types
from pydantic import BaseModel

from .models import ShoppingItem

log = logging.getLogger("shopping-agent.ai")

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client = genai.Client(api_key=GEMINI_API_KEY)


class Action(StrEnum):
    add = "add"
    remove = "remove"
    clear = "clear"
    list = "list"


class Operation(BaseModel):
    action: Action
    item_id: int | None = None
    name: str | None = None
    quantity: float | None = None
    unit: str | None = None


SYSTEM_INSTRUCTION = """\
You manage a shared household shopping list. Given the current list and a new \
message, return a JSON array of operations to apply.

Each operation object has: action ("add" | "remove" | "clear" | "list"), \
item_id, name, quantity, unit.

Rules:
- "add": set name (singular, lowercase). Set quantity and unit only if the \
  user gave them; otherwise leave them null.
- "remove": set item_id to the id of a matching item from the current list. \
  If nothing matches, omit the operation.
- "clear": the user wants to empty the whole list. No other fields needed.
- "list": the user is asking what is currently on the list.
- A single message may map to several operations (e.g. add two items).
- If the message is small talk or you cannot map it to any operation, return \
  an empty array.

Return only the JSON array."""


def _render_list(items: list[ShoppingItem]) -> str:
    return json.dumps(
        [
            {
                "id": it.id,
                "name": it.name,
                "quantity": it.quantity,
                "unit": it.unit,
            }
            for it in items
        ],
        ensure_ascii=False,
    )


async def parse_message(
    message: str, current_items: list[ShoppingItem]
) -> list[Operation]:
    prompt = f'Current list:\n{_render_list(current_items)}\n\nMessage: "{message}"'
    try:
        response = await _client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=list[Operation],
                temperature=0.0,
            ),
        )
    except Exception:
        log.exception("Gemini request failed")
        return []

    ops = response.parsed
    if not ops:
        return []
    return ops
