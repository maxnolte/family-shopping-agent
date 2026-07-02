import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .webhook import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("shopping-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("database ready")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


app.include_router(router)
