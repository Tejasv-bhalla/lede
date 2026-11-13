"""HTTP API (SYSTEM_DESIGN.md §16.4). The React app is display-only; every decision lives here."""

from __future__ import annotations

import csv
import hmac
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.batch.csv_import import CsvFormatError, read_prospects
from app.config import Settings
from app.context.merge import merge_brief
from app.db.store import Store
from app.domain.models import Campaign, ProspectInput, SellerProfile

MAX_CSV_BYTES = 1_000_000


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


@api.get("/campaigns")
async def list_campaigns(store: StoreDep) -> list[dict[str, Any]]:
    return await store.list_campaigns()


@api.post("/campaigns", status_code=201)
async def create_campaign(campaign: Campaign, store: StoreDep) -> dict[str, Any]:
    data = campaign.model_dump(mode="json")
    await store.add_campaign(data)
    return data


async def _campaign(store: Store, campaign_id: str) -> Campaign:
    data = await store.get_campaign(campaign_id)
    if data is None:
        raise HTTPException(404, f"No campaign '{campaign_id}'.")
    return Campaign.model_validate(data)


@api.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, store: StoreDep) -> dict[str, Any]:
    return (await _campaign(store, campaign_id)).model_dump(mode="json")


@api.put("/campaigns/{campaign_id}")
async def put_campaign(campaign_id: str, campaign: Campaign, store: StoreDep) -> dict[str, Any]:
    data = campaign.model_copy(update={"id": campaign_id}).model_dump(mode="json")
    if not await store.put_campaign(data):
        raise HTTPException(404, f"No campaign '{campaign_id}'.")
    return data


async def _profile(store: Store) -> SellerProfile:
    data = await store.get_profile()
    if data is None:
        raise HTTPException(
            409, "Set up the seller profile first; campaigns are checked against it."
        )
    return SellerProfile.model_validate(data)


@api.post("/campaigns/{campaign_id}/validate")
async def validate_campaign(campaign_id: str, store: StoreDep) -> dict[str, Any]:
    campaign = await _campaign(store, campaign_id)
    brief = merge_brief(await _profile(store), campaign)
    return {
        "ok": brief.ok,
        "issues": [asdict(i) for i in brief.issues],
        "provenance": brief.provenance,
    }


@api.get("/campaigns/{campaign_id}/prospects")
async def list_prospects(campaign_id: str, store: StoreDep) -> list[dict[str, Any]]:
    await _campaign(store, campaign_id)
    return [{"id": pid, **data} for pid, data in await store.list_prospects(campaign_id)]


@api.post("/campaigns/{campaign_id}/prospects", status_code=201)
async def add_prospect(
    campaign_id: str, prospect: ProspectInput, store: StoreDep
) -> dict[str, Any]:
    await _campaign(store, campaign_id)
    data = prospect.model_dump(mode="json")
    (pid,) = await store.add_prospects(campaign_id, [data])
    return {"id": pid, **data}


@api.post("/campaigns/{campaign_id}/prospects/csv")
async def import_prospects_csv(
    campaign_id: str, file: UploadFile, store: StoreDep, dry_run: bool = True
) -> dict[str, Any]:
    """Preview (dry_run, the default) or save a prospect CSV; nothing costs quota here."""
    await _campaign(store, campaign_id)
    existing = [ProspectInput.model_validate(d) for _, d in await store.list_prospects(campaign_id)]
    try:
        text = (await file.read(MAX_CSV_BYTES + 1)).decode("utf-8-sig")
        if len(text) > MAX_CSV_BYTES:
            raise CsvFormatError("The file is larger than 1 MB.")
        preview = read_prospects(text, existing)
    except (CsvFormatError, UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = [p.model_dump(mode="json") for p in preview.rows]
    saved = 0 if dry_run else len(await store.add_prospects(campaign_id, rows))
    return {
        "rows": rows,
        "errors": [asdict(e) for e in preview.errors],
        "unmapped_columns": preview.unmapped_columns,
        "saved": saved,
    }


def create_app(settings: Settings, *, store: Store) -> FastAPI:
    app = FastAPI(title="Signal to Draft", version="0.1.0")
    app.state.settings = settings
    app.state.store = store
    app.include_router(public)
    app.include_router(api)
    return app
