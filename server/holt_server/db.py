"""Tables and sessions.

Postgres in production (asyncpg); the tests use SQLite (aiosqlite), so column
types stay portable: JSON, strings, integers, timestamps. The schema is made
with `create_all` at startup. It is small and pre-launch; when it first needs
to change in place, that is the moment to add Alembic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, Index, Integer, String, Text, text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime | None) -> datetime | None:
    """SQLite hands timestamps back naive; they were written as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def iso(value: datetime | None) -> str | None:
    value = utc(value)
    return value.isoformat().replace("+00:00", "Z") if value else None


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class User(Base):
    """Keyed by the id `web/` (Auth.js) uses. Created the first time we see it."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    plan: Mapped[str] = mapped_column(String(40), default="free")
    # AI reports run on the server's key in `ai_period` (a "YYYY-MM" month).
    ai_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_period: Mapped[str] = mapped_column(String(7), default="")
    byok_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    byok_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    byok_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True,
                                    default=lambda: uuid.uuid4().hex)
    kind: Mapped[str] = mapped_column(String(20), default="analysis")  # analysis | find
    repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    repo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="rules")
    days: Mapped[int] = mapped_column(Integer, default=7)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    user_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Where the model key came from: "server" (counts against quota) or "byok".
    key_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    charged: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="Waiting to start")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_dedupe", "repo_key", "mode", "days", "status"),
    )


class Report(Base):
    """Every finished report, newest wins. The 24h cache and the public pages."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo: Mapped[str] = mapped_column(String(200))
    repo_key: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(10))
    days: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_reports_lookup", "repo_key", "mode", "days", "created_at"),)


class Database:
    def __init__(self, url: str) -> None:
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=5, max_overflow=5, pool_pre_ping=True)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("select 1"))
            return True
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()
