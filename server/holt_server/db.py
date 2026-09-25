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
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
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
    # When paid access ends unless renewed. Null with a paid plan means a grant
    # made by hand, which does not lapse. Changed only by verified payment
    # events (see billing/service.py), never by what a client says.
    plan_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Start of the current paid billing cycle: the monthly allowance resets on
    # the subscription's cycle, not the calendar month.
    cycle_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # AI reports run on the server's key in `ai_period` (see quota.period_key).
    ai_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_period: Mapped[str] = mapped_column(String(20), default="")
    # One-time pack credits. Never expire; spent after the monthly allowance.
    pack_credits: Mapped[int] = mapped_column(Integer, default=0)
    # Set while a pack payment is disputed: credits stay but cannot be spent.
    packs_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    # The provider subscription that granted `plan`. Only that subscription's
    # events (or a newer one's) may change or end it.
    plan_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    byok_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    byok_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    byok_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# Lower runs first: paid plans, then everyone else, then badge refreshes.
PAID_PRIORITY = 0
USER_PRIORITY = 5
BADGE_PRIORITY = 10


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
    # Which pool paid for it: "plan" (monthly allowance) or "pack". Refunds go
    # back to the same pool.
    quota_pool: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Identical questions share a job: at most one queued/running job per key,
    # enforced by the partial unique index below, not by a read-then-insert.
    dedupe_key: Mapped[str | None] = mapped_column(String(260), nullable=True)
    # Lower runs first; see PAID_PRIORITY / USER_PRIORITY / BADGE_PRIORITY.
    priority: Mapped[int] = mapped_column(Integer, default=USER_PRIORITY)
    # The runner that claimed the job, and when it last said it was alive. A
    # `running` job whose heartbeat is stale belonged to a dead process.
    worker_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="Waiting to start")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_jobs_status_priority", "status", "priority", "created_at"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ux_jobs_active_dedupe", "dedupe_key", unique=True,
              postgresql_where=text("status IN ('queued', 'running')"),
              sqlite_where=text("status IN ('queued', 'running')")),
    )


ACTIVE = ("queued", "running")


def dedupe_key(repo_key: str, mode: str, days: int) -> str:
    return f"analysis:{repo_key}:{mode}:{days}"


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


# --- billing ------------------------------------------------------------------

LIVE_SUBSCRIPTION = ("status IN ('created', 'authenticated', 'active', 'pending') "
                     "AND NOT cancel_at_period_end")
#
# No card data is ever stored or seen: the provider's checkout collects it.
# Amounts are integers in minor units (paise, cents) with their currency.


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_subscription_id: Mapped[str] = mapped_column(String(100), unique=True)
    plan: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[int] = mapped_column(Integer)
    # created | authenticated | active | pending | halted | cancelled | completed | expired
    status: Mapped[str] = mapped_column(String(20), default="created")
    current_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now,
                                                 onupdate=now)

    # At most one live, renewing subscription per user: a second checkout
    # reuses or cancels the first (billing/routes.py), and this makes a race
    # between two checkouts fail instead of billing twice.
    __table_args__ = (
        Index("ux_subscriptions_one_live", "user_id", unique=True,
              postgresql_where=text(LIVE_SUBSCRIPTION),
              sqlite_where=text(LIVE_SUBSCRIPTION)),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))  # pack | subscription
    item: Mapped[str] = mapped_column(String(40))  # pack id or plan id
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True,
                                                          nullable=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True,
                                                            nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True,
                                                                 index=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="created")  # created|paid|failed
    # Pack credits were added for this payment. Set in the same transaction as
    # the credit, under a conditional UPDATE, so no event credits twice.
    credited: Mapped[bool] = mapped_column(Boolean, default=False)
    # Minor units refunded so far (partial refunds add up).
    refunded_amount: Mapped[int] = mapped_column(Integer, default=0)
    # Pack ledger. `credits_left`: this pack's unspent reports (packs are spent
    # oldest first). `credits_taken`: reports clawed back for refunds so far,
    # as ceil(reports * refunded / amount); each new refund takes only the
    # difference, and only from this pack's unspent credits.
    credits_left: Mapped[int] = mapped_column(Integer, default=0)
    credits_taken: Mapped[int] = mapped_column(Integer, default=0)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now,
                                                 onupdate=now)


class Refund(Base):
    """Each provider refund, applied once however many events mention it."""

    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_refund_id: Mapped[str] = mapped_column(String(100), unique=True)
    payment_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WebhookEvent(Base):
    """Every webhook delivery we acted on, keyed by a hash of its signed body
    (the event-id header is not covered by the signature)."""

    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(60))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
