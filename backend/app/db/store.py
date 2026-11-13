"""Persistence: a thin async store over SQLAlchemy (SQLite locally, Supabase Postgres deployed).

Documents (profile, campaigns, run outcomes) are stored as JSON validated by the domain models,
so the schema evolves with the models; only the fields we filter on are real columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, select
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
