"""Persistence: a thin async store over SQLAlchemy (SQLite locally, Supabase Postgres deployed).

Documents (profile, campaigns, run outcomes) are stored as JSON validated by the domain models,
so the schema evolves with the models; only the fields we filter on are real columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import TypeAdapter
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.research.ports import SearchHit

Json = JSON().with_variant(JSONB(), "postgresql")
_HITS = TypeAdapter(list[SearchHit])


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything we store is UTC, so say so."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def async_url(url: str) -> str:
    """Accept the plain URLs people copy from dashboards and pick the async driver."""
    for plain, driver in (
        ("postgres://", "postgresql+psycopg://"),
        ("postgresql://", "postgresql+psycopg://"),
        ("sqlite://", "sqlite+aiosqlite://"),
    ):
        if url.startswith(plain):
            return driver + url.removeprefix(plain)
    return url


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # single workspace: always 1
    data: Mapped[dict[str, Any]] = mapped_column(Json)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CampaignRow(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProspectRow(Base):
    __tablename__ = "prospects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    tier: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), index=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(Json)  # prospect, brief, pinned identity
    outcome: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)
    events: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    review: Mapped[dict[str, Any] | None] = mapped_column(Json, nullable=True)
    review_state: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "prospect_id": self.prospect_id,
            "tier": self.tier,
            "state": self.state,
            "review_state": self.review_state,
            "prospect": self.inputs["prospect"],
            "created_at": _utc(self.created_at).isoformat(),
            "finished_at": _utc(self.finished_at).isoformat() if self.finished_at else None,
        }


class SearchCacheRow(Base):
    __tablename__ = "search_cache"
    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    hits: Mapped[list[dict[str, Any]]] = mapped_column(Json)
    expires_at: Mapped[float] = mapped_column(Float, index=True)  # epoch seconds: portable


class EngineSpendRow(Base):
    __tablename__ = "engine_spend"
    engine: Mapped[str] = mapped_column(String(32), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    spent: Mapped[float] = mapped_column(Float, default=0.0)


class SettingRow(Base):
    """Small named settings documents, e.g. the model choices."""

    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(Json)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Store:
    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(async_url(url))
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self._engine.dispose()

    def session(self) -> AsyncSession:
        return self._session()

    # ── seller profile ────────────────────────────────────────────────────────

    async def get_profile(self) -> dict[str, Any] | None:
        async with self.session() as s:
            row = await s.get(ProfileRow, 1)
            return row.data if row else None

    async def put_profile(self, data: dict[str, Any]) -> int:
        """Save the profile and return its new version."""
        async with self.session() as s, s.begin():
            row = (await s.execute(select(ProfileRow).where(ProfileRow.id == 1))).scalar()
            if row is None:
                s.add(ProfileRow(id=1, data=data, version=1))
                return 1
            row.data, row.version, row.updated_at = data, row.version + 1, _now()
            return row.version

    # ── named settings ────────────────────────────────────────────────────────

    async def get_setting(self, key: str) -> dict[str, Any] | None:
        async with self.session() as s:
            row = await s.get(SettingRow, key)
            return row.data if row else None

    async def put_setting(self, key: str, data: dict[str, Any]) -> None:
        async with self.session() as s, s.begin():
            row = await s.get(SettingRow, key)
            if row is None:
                s.add(SettingRow(key=key, data=data))
            else:
                row.data, row.updated_at = data, _now()

    # ── campaigns ─────────────────────────────────────────────────────────────

    async def add_campaign(self, data: dict[str, Any]) -> None:
        async with self.session() as s, s.begin():
            s.add(CampaignRow(id=data["id"], data=data))

    async def list_campaigns(self) -> list[dict[str, Any]]:
        async with self.session() as s:
            rows = await s.scalars(select(CampaignRow).order_by(CampaignRow.created_at))
            return [r.data for r in rows]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        async with self.session() as s:
            row = await s.get(CampaignRow, campaign_id)
            return row.data if row else None

    async def put_campaign(self, data: dict[str, Any]) -> bool:
        """Replace an existing campaign; False if there is none with that id."""
        async with self.session() as s, s.begin():
            row = await s.get(CampaignRow, data["id"])
            if row is None:
                return False
            row.data = data
            return True

    async def delete_campaign(self, campaign_id: str) -> Literal["deleted", "missing", "running"]:
        """Delete a campaign with its prospects and runs, unless a run is still going."""
        async with self.session() as s, s.begin():
            if await s.get(CampaignRow, campaign_id) is None:
                return "missing"
            running = await s.scalar(
                select(func.count())
                .select_from(RunRow)
                .where(RunRow.campaign_id == campaign_id, RunRow.state == "RUNNING")
            )
            if running:
                return "running"
            await s.execute(delete(RunRow).where(RunRow.campaign_id == campaign_id))
            await s.execute(delete(ProspectRow).where(ProspectRow.campaign_id == campaign_id))
            await s.execute(delete(CampaignRow).where(CampaignRow.id == campaign_id))
            return "deleted"

    # ── prospects ─────────────────────────────────────────────────────────────

    async def add_prospects(self, campaign_id: str, items: list[dict[str, Any]]) -> list[int]:
        async with self.session() as s, s.begin():
            rows = [ProspectRow(campaign_id=campaign_id, data=d) for d in items]
            s.add_all(rows)
            await s.flush()
            return [r.id for r in rows]

    async def list_prospects(self, campaign_id: str) -> list[tuple[int, dict[str, Any]]]:
        async with self.session() as s:
            rows = await s.scalars(
                select(ProspectRow)
                .where(ProspectRow.campaign_id == campaign_id)
                .order_by(ProspectRow.id)
            )
            return [(r.id, r.data) for r in rows]

    async def get_prospect(self, prospect_id: int) -> tuple[str, dict[str, Any]] | None:
        """(campaign id, prospect data), or None."""
        async with self.session() as s:
            row = await s.get(ProspectRow, prospect_id)
            return (row.campaign_id, row.data) if row else None

    # ── runs ──────────────────────────────────────────────────────────────────

    async def create_run(
        self,
        run_id: str,
        *,
        campaign_id: str,
        prospect_id: int,
        tier: str,
        inputs: dict[str, Any],
    ) -> None:
        async with self.session() as s, s.begin():
            s.add(
                RunRow(
                    id=run_id,
                    campaign_id=campaign_id,
                    prospect_id=prospect_id,
                    tier=tier,
                    state="RUNNING",
                    inputs=inputs,
                    events=[],
                )
            )

    async def finish_run(
        self, run_id: str, *, state: str, outcome: dict[str, Any], events: list[dict[str, Any]]
    ) -> None:
        async with self.session() as s, s.begin():
            row = await s.get(RunRow, run_id)
            assert row is not None
            row.state, row.outcome, row.events, row.finished_at = state, outcome, events, _now()

    async def list_runs(
        self, *, campaign_id: str | None = None, state: str | None = None
    ) -> list[dict[str, Any]]:
        query = select(RunRow).order_by(RunRow.created_at.desc())
        if campaign_id:
            query = query.where(RunRow.campaign_id == campaign_id)
        if state:
            query = query.where(RunRow.state == state)
        async with self.session() as s:
            return [r.summary() for r in await s.scalars(query)]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self.session() as s:
            row = await s.get(RunRow, run_id)
            if row is None:
                return None
            return {
                **row.summary(),
                "brief": row.inputs["brief"],
                "pinned_identity": row.inputs.get("pinned_identity"),
                "outcome": row.outcome,
                "events": list(row.events),
                "review": row.review,
            }

    async def save_review(self, run_id: str, review: dict[str, Any]) -> None:
        async with self.session() as s, s.begin():
            row = await s.get(RunRow, run_id)
            assert row is not None
            row.review, row.review_state = review, review["state"]

    async def count_runs(self) -> tuple[dict[str, int], dict[str, int]]:
        """(runs per state, reviewed runs per review state)."""
        async with self.session() as s:
            states = await s.execute(select(RunRow.state, func.count()).group_by(RunRow.state))
            reviews = await s.execute(
                select(RunRow.review_state, func.count())
                .where(RunRow.review_state.is_not(None))
                .group_by(RunRow.review_state)
            )
            return (
                {state: n for state, n in states},
                {state: n for state, n in reviews if state},
            )

    async def approved_runs(self, campaign_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            select(RunRow)
            .where(RunRow.review_state.in_(("APPROVED", "APPROVED_WITH_EDITS")))
            .order_by(RunRow.created_at)
        )
        if campaign_id:
            query = query.where(RunRow.campaign_id == campaign_id)
        async with self.session() as s:
            return [
                {**r.summary(), "outcome": r.outcome, "review": r.review}
                for r in await s.scalars(query)
            ]

    async def latest_runs(self, campaign_id: str) -> dict[int, dict[str, Any]]:
        """The most recent run of each prospect in a campaign."""
        query = (
            select(RunRow)
            .where(RunRow.campaign_id == campaign_id)
            .order_by(RunRow.created_at.desc())
        )
        latest: dict[int, dict[str, Any]] = {}
        async with self.session() as s:
            for row in await s.scalars(query):
                latest.setdefault(row.prospect_id, row.summary())
        return latest

    async def run_durations(self) -> list[float]:
        """Seconds from start to finish of every finished run."""
        query = select(RunRow.created_at, RunRow.finished_at).where(RunRow.finished_at.is_not(None))
        async with self.session() as s:
            return [
                (finished - created).total_seconds()
                for created, finished in await s.execute(query)
                if finished is not None
            ]

    async def engine_spend(self, period: str) -> dict[str, float]:
        async with self.session() as s:
            rows = await s.scalars(select(EngineSpendRow).where(EngineSpendRow.period == period))
            return {r.engine: r.spent for r in rows}


class StoreLedger:
    """The search cache and engine spend, kept in the database so restarts don't forget them."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def cached(self, key: str, now: datetime) -> list[SearchHit] | None:
        async with self._store.session() as s:
            row = await s.get(SearchCacheRow, key)
            if row is None or row.expires_at <= now.timestamp():
                return None
            return _HITS.validate_python(row.hits)

    async def remember(self, key: str, hits: list[SearchHit], expires: datetime) -> None:
        data = _HITS.dump_python(hits, mode="json")
        async with self._store.session() as s, s.begin():
            row = await s.get(SearchCacheRow, key)
            if row is None:
                s.add(SearchCacheRow(key=key, hits=data, expires_at=expires.timestamp()))
            else:
                row.hits, row.expires_at = data, expires.timestamp()

    async def spent(self, engine: str, period: str) -> float:
        async with self._store.session() as s:
            row = await s.get(EngineSpendRow, (engine, period))
            return row.spent if row else 0.0

    async def charge(self, engine: str, period: str, amount: float) -> None:
        async with self._store.session() as s, s.begin():
            # An atomic increment, so parallel searches can't lose each other's spend.
            done = await s.execute(
                update(EngineSpendRow)
                .where(EngineSpendRow.engine == engine, EngineSpendRow.period == period)
                .values(spent=EngineSpendRow.spent + amount)
            )
            if done.rowcount == 0:  # type: ignore[attr-defined]
                s.add(EngineSpendRow(engine=engine, period=period, spent=amount))
