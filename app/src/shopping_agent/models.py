from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ShoppingItem(SQLModel, table=True):
    __tablename__ = "shopping_items"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    quantity: float | None = None
    unit: str | None = None
    added_by: str
    added_at: datetime = Field(default_factory=_utcnow)


# ─── History (append-only; raw layer for analytics/) ───────────────────────


class Message(SQLModel, table=True):
    """One inbound message from a whitelisted sender. Inserted on receipt,
    then completed with the parsed ops, reply and outcome."""

    __tablename__ = "messages"

    id: int | None = Field(default=None, primary_key=True)
    received_at: datetime = Field(default_factory=_utcnow, index=True)
    sender: str = Field(index=True)
    text: str
    # Operations returned by the AI parser, as a JSON array (null until parsed
    # or when the message was a clear confirmation).
    ops_json: str | None = None
    reply: str | None = None
    # received | ok | fallback | no_match | confirm_requested | cleared | error
    status: str = "received"


class ItemEvent(SQLModel, table=True):
    """One change to the shopping list. Written in the same transaction as the
    change itself, so the list and its history can't diverge."""

    __tablename__ = "item_events"

    id: int | None = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="messages.id", index=True)
    occurred_at: datetime = Field(default_factory=_utcnow, index=True)
    sender: str
    # add | update | remove | clear
    action: str
    item_name: str
    quantity: float | None = None
    unit: str | None = None
