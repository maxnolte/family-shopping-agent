from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShoppingItem(SQLModel, table=True):
    __tablename__ = "shopping_items"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    quantity: float | None = None
    unit: str | None = None
    added_by: str
    added_at: datetime = Field(default_factory=_utcnow)
