"""HTTP API (SYSTEM_DESIGN.md §16.4). The React app is display-only; every decision lives here."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings
from app.db.store import Store
from app.domain.models import SellerProfile


class CodeCheck(BaseModel):
    code: str


def _code_matches(settings: Settings, code: str | None) -> bool:
    expected = settings.demo_access_code
    if expected is None:  # no code configured: open (local development)
        return True
    return code is not None and hmac.compare_digest(code, expected.get_secret_value())


def _store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def _require_code(request: Request, x_access_code: Annotated[str | None, Header()] = None) -> None:
    if not _code_matches(request.app.state.settings, x_access_code):
        raise HTTPException(401, "A valid access code is required.")


StoreDep = Annotated[Store, Depends(_store)]

public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(_require_code)])


@public.post("/auth/check")
async def check_code(body: CodeCheck, request: Request) -> dict[str, bool]:
    return {"ok": _code_matches(request.app.state.settings, body.code)}


@api.get("/profile")
async def get_profile(store: StoreDep) -> dict[str, Any]:
    data = await store.get_profile()
    if data is None:
        raise HTTPException(404, "No seller profile yet.")
    return SellerProfile.model_validate(data).model_dump(mode="json")


@api.put("/profile")
async def put_profile(profile: SellerProfile, store: StoreDep) -> dict[str, Any]:
    version = await store.put_profile(profile.model_dump(mode="json"))
    return {"version": version, "profile": profile.model_dump(mode="json")}


def create_app(settings: Settings, *, store: Store) -> FastAPI:
    app = FastAPI(title="Signal to Draft", version="0.1.0")
    app.state.settings = settings
    app.state.store = store
    app.include_router(public)
    app.include_router(api)
    return app
