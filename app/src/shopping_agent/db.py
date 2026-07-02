import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

# Import models so their tables are registered on SQLModel.metadata before
# create_all() runs.
from . import models  # noqa: F401

DB_PATH = os.environ.get("DB_PATH", "/app/data/shopping.db")

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False: FastAPI may touch the connection from worker threads.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
