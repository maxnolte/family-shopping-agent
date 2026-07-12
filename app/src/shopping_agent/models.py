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
