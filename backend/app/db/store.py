"""Persistence: a thin async store over SQLAlchemy (SQLite locally, Supabase Postgres deployed).

Documents (profile, campaigns, run outcomes) are stored as JSON validated by the domain models,
so the schema evolves with the models; only the fields we filter on are real columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(UTC)


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
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


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
