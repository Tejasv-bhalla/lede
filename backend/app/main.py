"""Production entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.factory import Runtime
from app.api.app import create_app
from app.config import get_settings
from app.db.store import Store, StoreLedger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def build() -> FastAPI:
    settings = get_settings()
    store = Store(settings.database_url)
    runtime = Runtime.create(settings, StoreLedger(store))
    if not runtime.ready:
        log.warning("AI roles missing a provider; runs are disabled until keys are added to .env")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await store.create_all()
        yield
        await runtime.close()
        await store.dispose()

    return create_app(
        settings,
        store=store,
        deps_factory=runtime.deps if runtime.ready else None,
        lifespan=lifespan,
    )


app = build()
