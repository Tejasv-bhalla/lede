"""HTTP API (SYSTEM_DESIGN.md §16.4). The React app is display-only; every decision lives here."""

from __future__ import annotations

import csv
import hmac
import io
import json
import statistics
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator
from sse_starlette import EventSourceResponse

from app.batch.csv_import import CsvFormatError, read_prospects
from app.config import Settings
from app.context.merge import merge_brief
from app.db.store import Store
from app.domain.models import Campaign, ProspectInput, RunState, SellerProfile, Tier
from app.pipeline.ports import Contact, Draft
from app.pipeline.run import PipelineDeps
from app.providers.catalogue import ProviderId
from app.providers.llm_roles import Role
from app.services.models import Choice, ModelService, NeedsSecret, NoKey
from app.services.runs import DraftRejected, NotFound, NotReady, ReviewAction, RunService

MAX_CSV_BYTES = 1_000_000
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


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


@public.get("/health")
async def health(request: Request) -> dict[str, bool]:
    """For the uptime pinger. Deliberately database-free, so pings don't keep Neon awake."""
    return {"ok": True, "runs_enabled": request.app.state.runs is not None}


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
    """Every campaign, with how far its prospects have got."""
    return [
        {**c, "stats": await _campaign_stats(store, c["id"])} for c in await store.list_campaigns()
    ]


_NEEDS_YOU = {RunState.NEEDS_CLARIFICATION.value, RunState.CONTACT_MOVED.value}
_DRAFTED = {RunState.DRAFT_READY.value, RunState.DRAFT_HELD.value}


async def _campaign_stats(store: Store, campaign_id: str) -> dict[str, Any]:
    prospects = await store.list_prospects(campaign_id)
    runs = await store.list_runs(campaign_id=campaign_id)  # newest first
    latest: dict[int, dict[str, Any]] = {}
    for run in runs:
        latest.setdefault(run["prospect_id"], run)
    return {
        "prospects": len(prospects),
        "not_run": sum(pid not in latest for pid, _ in prospects),
        "to_review": sum(r["state"] in _DRAFTED and not r["review_state"] for r in latest.values()),
        "needs_you": sum(r["state"] in _NEEDS_YOU for r in latest.values()),
        "approved": sum((r["review_state"] or "").startswith("APPROVED") for r in runs),
        "last_run_at": runs[0]["created_at"] if runs else None,
    }


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


@api.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, store: StoreDep) -> None:
    """Delete a campaign with its prospects, runs and drafts. Cannot be undone."""
    result = await store.delete_campaign(campaign_id)
    if result == "missing":
        raise HTTPException(404, f"No campaign '{campaign_id}'.")
    if result == "running":
        raise HTTPException(409, "A run in this campaign is still running; delete it when done.")


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
    latest = await store.latest_runs(campaign_id)
    return [
        {"id": pid, **data, "last_run": latest.get(pid)}
        for pid, data in await store.list_prospects(campaign_id)
    ]


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


class RunRequest(BaseModel):
    prospect_id: int
    tier: Tier = Tier.STANDARD
    pinned_identity: Contact | None = None  # the rep's pick after NEEDS_CLARIFICATION


def _runs(request: Request) -> RunService:
    runs: RunService | None = request.app.state.runs
    if runs is None:
        raise HTTPException(503, "No AI providers are configured; add API keys to .env.")
    return runs


RunsDep = Annotated[RunService, Depends(_runs)]


@api.post("/runs", status_code=202)
async def start_run(body: RunRequest, runs: RunsDep) -> dict[str, str]:
    try:
        run_id = await runs.start(body.prospect_id, body.tier, body.pinned_identity)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


@api.get("/runs")
async def list_runs(
    store: StoreDep, campaign_id: str | None = None, state: RunState | None = None
) -> list[dict[str, Any]]:
    return await store.list_runs(campaign_id=campaign_id, state=state.value if state else None)


@api.get("/runs/{run_id}")
async def get_run(run_id: str, runs: RunsDep) -> dict[str, Any]:
    try:
        return await runs.detail(run_id)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@api.get("/runs/{run_id}/events")
async def run_events(run_id: str, runs: RunsDep) -> EventSourceResponse:
    """Server-sent events: replays what happened so far, then follows the run live."""
    await get_run(run_id, runs)  # 404 before the stream opens

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for event in runs.follow(run_id):
            yield {"event": "stage", "data": json.dumps(event)}

    return EventSourceResponse(stream(), ping=15)


class ReviewRequest(BaseModel):
    action: ReviewAction
    subject: str | None = None
    body: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _fields_for_action(self) -> ReviewRequest:
        if self.action == "edit" and not (self.subject and self.body):
            raise ValueError("An edit needs both a subject and a body.")
        if self.action == "reject" and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the draft is rejected; it trains future runs.")
        return self


@api.post("/runs/{run_id}/review")
async def review_run(run_id: str, body: ReviewRequest, runs: RunsDep) -> dict[str, Any]:
    edited = Draft(subject=body.subject, body=body.body) if body.subject and body.body else None
    try:
        return await runs.review(run_id, body.action, draft=edited, reason=body.reason)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except NotReady as exc:
        raise HTTPException(409, str(exc)) from exc
    except DraftRejected as exc:
        raise HTTPException(422, {"violations": exc.violations}) from exc


@api.get("/dashboard")
async def dashboard(store: StoreDep, request: Request) -> dict[str, Any]:
    """Run outcomes, review results and this month's search spend against free-tier limits."""
    by_state, by_review = await store.count_runs()
    reviewed = sum(by_review.values())
    approved = by_review.get("APPROVED", 0) + by_review.get("APPROVED_WITH_EDITS", 0)
    durations = await store.run_durations()
    settings: Settings = request.app.state.settings
    spend = await store.engine_spend(datetime.now(UTC).strftime("%Y-%m"))
    quota = [
        {
            "name": "Tavily",
            "used": spend.get("tavily", 0.0),
            "limit": settings.tavily_monthly_credits,
            "unit": "credits",
        },
        {
            "name": "Exa",
            "used": round(spend.get("exa", 0.0), 3),
            "limit": settings.exa_monthly_usd,
            "unit": "USD",
        },
    ]
    if settings.hunter_api_key:
        quota.append(
            {
                "name": "Hunter",
                "used": spend.get("hunter", 0.0),
                "limit": settings.hunter_monthly_credits,
                "unit": "email lookups",
            }
        )
    return {
        "runs_total": sum(by_state.values()),
        "by_state": by_state,
        "by_review": by_review,
        "approval_rate": round(approved / reviewed, 3) if reviewed else None,
        "median_run_seconds": round(statistics.median(durations), 1) if durations else None,
        "quota": quota,
    }


EXPORT_COLUMNS = (
    "run_id",
    "campaign_id",
    "company_name",
    "person_name",
    "title",
    "email",
    "email_source",
    "subject",
    "body",
    "hook",
    "hook_url",
    "review_state",
    "reviewed_at",
)


@api.get("/export")
async def export_csv(store: StoreDep, campaign_id: str | None = None) -> Response:
    """Approved drafts, footer appended, ready to paste into a mail tool or CRM."""
    profile = await store.get_profile()
    footer = SellerProfile.model_validate(profile).footer if profile else ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for run in await store.approved_runs(campaign_id):
        draft, prospect = run["review"]["draft"], run["prospect"]
        ranked = (run["outcome"] or {}).get("ranking", {}).get("ranked") or [{}]
        email = (run["outcome"] or {}).get("email") or {}
        hook = ranked[0].get("evidence", {})
        writer.writerow(
            {
                "run_id": run["id"],
                "campaign_id": run["campaign_id"],
                "company_name": prospect["company_name"],
                "person_name": prospect.get("person_name") or "",
                "title": prospect.get("title") or "",
                "email": email.get("address", ""),
                "email_source": email.get("source", ""),
                "subject": draft["subject"],
                "body": f"{draft['body']}\n\n{footer}" if footer else draft["body"],
                "hook": hook.get("claim", ""),
                "hook_url": hook.get("url", ""),
                "review_state": run["review_state"],
                "reviewed_at": run["review"]["at"],
            }
        )
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="approved-drafts.csv"'},
    )


# ── model settings ────────────────────────────────────────────────────────────


class KeyIn(BaseModel):
    api_key: str = ""
    base_url: str | None = None


def _models(request: Request) -> ModelService:
    models: ModelService | None = request.app.state.models
    if models is None:
        raise HTTPException(503, "Model settings are not available on this server.")
    return models


ModelsDep = Annotated[ModelService, Depends(_models)]


@api.get("/models")
async def get_models(models: ModelsDep) -> dict[str, Any]:
    return models.view()


@api.put("/models/keys/{provider}")
async def put_model_key(provider: ProviderId, body: KeyIn, models: ModelsDep) -> dict[str, Any]:
    try:
        await models.save_key(provider, body.api_key, body.base_url)
    except NeedsSecret as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return models.view()


@api.delete("/models/keys/{provider}")
async def delete_model_key(provider: ProviderId, models: ModelsDep) -> dict[str, Any]:
    await models.delete_key(provider)
    return models.view()


@api.put("/models/roles")
async def put_model_roles(body: dict[Role, Choice | None], models: ModelsDep) -> dict[str, Any]:
    try:
        await models.choose(body)
    except NoKey as exc:
        raise HTTPException(409, str(exc)) from exc
    return models.view()


@api.post("/models/test")
async def test_model(body: Choice, models: ModelsDep) -> dict[str, Any]:
    return asdict(await models.test(body.provider, body.model))


def create_app(
    settings: Settings,
    *,
    store: Store,
    deps_factory: Callable[[Tier], PipelineDeps] | None = None,
    models: ModelService | None = None,
    today: Callable[[], date] = date.today,
    lifespan: Lifespan | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Lede", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.runs = RunService(store, deps_factory, today) if deps_factory else None
    app.state.models = models
    app.include_router(public)
    app.include_router(api)
    if static_dir is not None and (static_dir / "index.html").is_file():
        _serve_web_app(app, static_dir)
    return app


def _serve_web_app(app: FastAPI, site: Path) -> None:
    """Serve the built React app from the same origin: files as they are, and every other
    non-API path as index.html so the browser router can open deep links."""
    app.mount("/assets", StaticFiles(directory=site / "assets"), name="assets")
    index = site / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        file = (site / path).resolve()
        if path and file.is_file() and file.is_relative_to(site.resolve()):
            return FileResponse(file)  # e.g. favicon.svg
        return FileResponse(index)
