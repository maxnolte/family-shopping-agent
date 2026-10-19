"""Build a synthetic shopping.db for developing and CI-testing the dbt project.

Uses the app's own SQLModel tables, so a schema change in the app shows up
here (and breaks `dbt build` in CI) instead of silently drifting.

Run with the app's environment:
    cd app
    uv run python ../analytics/scripts/make_fixture.py ../analytics/data/shopping.db
"""

import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/shopping.db").resolve()
out.parent.mkdir(parents=True, exist_ok=True)
out.unlink(missing_ok=True)
# db.py reads DB_PATH at import time.
os.environ["DB_PATH"] = str(out)

from shopping_agent.db import get_session, init_db  # noqa: E402
from shopping_agent.models import ItemEvent, Message, ShoppingItem  # noqa: E402

MEMBERS = ["41700000001", "41700000002"]
ITEMS = {
    "milk": (None, None),
    "bread": (None, None),
    "eggs": (10, None),
    "potatoes": (2, "kg"),
    "apples": (1, "kg"),
    "pasta": (500, "g"),
    "coffee": (None, None),
    "butter": (None, None),
    "tomatoes": (6, None),
    "cheese": (200, "g"),
    "flour": (1, "kg"),
    "yoghurt": (4, None),
}
SMALL_TALK = ["thanks!", "how are you?", "👍"]
DAYS = 90

rng = random.Random(42)
start = datetime(2026, 7, 1, tzinfo=UTC)
on_list: dict[str, tuple[float | None, str | None, str]] = {}


def message(s, at, sender, text, status, ops, reply) -> int:
    msg = Message(
        received_at=at,
        sender=sender,
        text=text,
        status=status,
        ops_json=None if ops is None else json.dumps(ops),
        reply=reply,
    )
    s.add(msg)
    s.flush()
    return msg.id


def event(s, at, message_id, sender, action, name, qty, unit) -> None:
    s.add(
        ItemEvent(
            message_id=message_id,
            occurred_at=at,
            sender=sender,
            action=action,
            item_name=name,
            quantity=qty,
            unit=unit,
        )
    )


init_db()
with get_session() as s:
    for day in range(DAYS):
        for _ in range(rng.randint(0, 4)):
            at = start + timedelta(
                days=day, hours=rng.randint(7, 21), minutes=rng.randint(0, 59)
            )
            sender = rng.choice(MEMBERS)
            roll = rng.random()

            if roll < 0.55:  # add (or update if already on the list)
                name = rng.choice(list(ITEMS))
                qty, unit = ITEMS[name]
                action = "update" if name in on_list and qty else "add"
                if name in on_list and not qty:
                    continue
                mid = message(
                    s,
                    at,
                    sender,
                    f"add {name}",
                    "ok",
                    [{"action": "add", "name": name, "quantity": qty, "unit": unit}],
                    f"✓ Added: {name}",
                )
                event(s, at, mid, sender, action, name, qty, unit)
                on_list[name] = (qty, unit, sender)
            elif roll < 0.85 and on_list:  # bought something
                name = rng.choice(sorted(on_list))
                qty, unit, _ = on_list.pop(name)
                mid = message(
                    s,
                    at,
                    sender,
                    f"bought {name}",
                    "ok",
                    [{"action": "remove", "item_id": 1}],
                    f"✓ Removed: {name}",
                )
                event(s, at, mid, sender, "remove", name, qty, unit)
            elif roll < 0.92:  # look at the list
                message(
                    s,
                    at,
                    sender,
                    "what's on the list?",
                    "ok",
                    [{"action": "list"}],
                    "🛒 Shopping list: …",
                )
            elif roll < 0.97:  # small talk the parser can't map
                message(s, at, sender, rng.choice(SMALL_TALK), "fallback", [], "Sorry…")
            elif on_list:  # weekly-shop style clear, confirmed
                message(
                    s,
                    at,
                    sender,
                    "clear the list",
                    "confirm_requested",
                    [{"action": "clear"}],
                    "⚠ This will remove all …",
                )
                at += timedelta(seconds=30)
                mid = message(s, at, sender, "yes", "cleared", None, "✓ List cleared")
                for name, (qty, unit, _) in sorted(on_list.items()):
                    event(s, at, mid, sender, "clear", name, qty, unit)
                on_list.clear()

    for name, (qty, unit, sender) in on_list.items():
        s.add(ShoppingItem(name=name, quantity=qty, unit=unit, added_by=sender))
    s.commit()

print(f"fixture written: {out}")
