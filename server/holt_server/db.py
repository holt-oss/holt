"""Tables and sessions.

Postgres in production (asyncpg); the tests use SQLite (aiosqlite), so column
types stay portable: JSON, strings, integers, timestamps. The schema comes
from the Alembic migrations in `migrations/` (see `migrate.py`), applied at
deploy and again, as a no-op, at startup. A change to a model here needs a
migration too; `python -m holt_server.migrate check` and the tests catch one
that is missing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from holt.engine_version import ENGINE_VERSION


def now() -> datetime:
    return datetime.now(UTC)


def _rules_version() -> int:
    from holt_server.starter import rules_version

    return rules_version()


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
    # A plan name from the pricing catalogue (pricing.py). It lapses back to
    # free at `plan_expires_at` (NULL: until changed). Every change also
    # writes a `PlanEvent`.
    plan: Mapped[str] = mapped_column(String(40), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                             nullable=True)
    # Free credits (welcome grant, weekly claim, admin gifts) this user can
    # still spend; purchased ones are `CreditLot`s. Every change also writes a
    # `CreditEvent`; the balance lives here so a spend is one guarded UPDATE.
    ai_credits: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # When the one-off welcome credits were given; NULL until the first visit.
    credits_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                                nullable=True)
    # Starts the weekly claim clock (the welcome grant starts it too).
    last_claim_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                           nullable=True)
    # Retired: the monthly quota and the website's bring-your-own-key. Nothing
    # reads them; migration 0003 emptied the BYOK columns. They are dropped in a
    # later release, once no deployed release selects them.
    ai_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_period: Mapped[str] = mapped_column(String(7), default="")
    byok_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    byok_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    byok_cipher: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PR watch's free taste (alerts.py): alerts work until then without a
    # pass. Set once, the first time alerts are turned on; never cleared, so
    # it can't be had twice.
    alerts_trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                                  nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CreditEvent(Base):
    """The credit ledger: one row per change to a balance. `amount` is signed.

    source: `free` (a change to `User.ai_credits`) or `purchased` (a change to
    the `CreditLot` in `lot_id`). Per user, the `free` rows sum to
    `ai_credits` and the `purchased` rows to the lots' `remaining`.

    kind: `grant` (welcome), `claim` (weekly), `purchase` (a pack), `adjust`
    (an admin, with `reason`), `spend` (a feature used, `feature` and usually
    `job_id` say which), `refund` (that use failed), `expire` (a lot's
    leftover at its expiry).
    """

    __tablename__ = "credit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The server default covers rows the release before sources inserts.
    source: Mapped[str] = mapped_column(String(20), default="free",
                                        server_default=text("'free'"))
    lot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who made an `adjust`, e.g. `cli`.
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_credit_events_user", "user_id", "created_at"),)


class CreditLot(Base):
    """Purchased credits: one row per pack bought (or admin grant to the
    purchased pool). Spent soonest-expiring first, after free credits; an
    expired lot can't be spent and its leftover is written off as `expire`."""

    __tablename__ = "credit_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    # `pack` (bought) or `admin`.
    origin: Mapped[str] = mapped_column(String(20))
    pack_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The payment's id: the same payment can never add a second lot.
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    granted: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_credit_lots_user", "user_id", "remaining"),)


class Order(Base):
    """One checkout (payments.py): a pass, or a credit pack from before
    passes (`pack_id` holds the pass id, `expires_days` its days of Pro, and
    `credits` is 0). What it costs and what it buys are copied from the
    pricing file when it is created, so a price change
    never alters an order already open. Only a verified payment moves it to
    `paid`, once, in the same transaction that gives what it bought.

    status: `created` (checkout opened), `paid`, `failed` (the last attempt
    was declined; another attempt on the same order can still pay it), `held`
    (a payment that didn't match the order: nothing given, a person looks).
    """

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True,
                                    default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(200))
    pack_id: Mapped[str] = mapped_column(String(40))
    credits: Mapped[int] = mapped_column(Integer)
    # A pass: its days of Pro. A credit pack: days its credits last (NULL: never).
    expires_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Minor units (paise).
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(20))
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True)
    # The payment that paid it: one payment can never pay two orders.
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True,
                                                            unique=True)
    status: Mapped[str] = mapped_column(String(10), default="created")
    # Why it failed or was held, for people.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_orders_user", "user_id", "created_at"),)


class Subscription(Base):
    """One monthly plan bought through Razorpay. No longer sold (passes
    replaced monthly plans); the table stays until a migration drops it. The price
    and the Razorpay plan are copied from the pricing file when it starts.
    Only Razorpay's word (a signed webhook, or a fetch after a signed
    checkout) moves it on, and only forward: an event about an older billing
    period than the one held here changes nothing.

    status is Razorpay's: `created` (checkout opened), `authenticated`
    (mandate set up, nothing paid yet), `active`, `pending` (a renewal failed
    and Razorpay is retrying: the plan continues through the grace period),
    `halted` (the retries failed: the plan ends), `paused`, `cancelled`,
    `completed`, `expired`. At most one per user is live (created to pending).
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True,
                                    default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(String(200))
    plan_id: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))
    provider_subscription_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider_plan_id: Mapped[str] = mapped_column(String(100))
    # Each charge, in minor units (paise).
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="created")
    # The billing period paid for most recently, and the next charge.
    current_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                           nullable=True)
    current_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The user asked to stop at the end of the period they paid for.
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False,
                                                       server_default=text("false"))
    # The plan expiry this subscription last gave the user (period end + grace).
    granted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                           nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_subscriptions_user", "user_id", "created_at"),
        Index("ux_subscriptions_live_user", "user_id", unique=True,
              postgresql_where=text(
                  "status IN ('created', 'authenticated', 'active', 'pending')"),
              sqlite_where=text(
                  "status IN ('created', 'authenticated', 'active', 'pending')")),
    )


class SubscriptionCharge(Base):
    """One payment Razorpay took for a subscription: the billing history. One
    row per payment id, so a replayed `subscription.charged` adds nothing.
    status: `paid`, or `held` (the amount didn't match: no plan given)."""

    __tablename__ = "subscription_charges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(String(200))
    provider_payment_id: Mapped[str] = mapped_column(String(100), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="paid")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_subscription_charges_user", "user_id", "created_at"),)


class PlanEvent(Base):
    """Every change to `User.plan` / `plan_expires_at`, and why."""

    __tablename__ = "plan_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_plan_events_user", "user_id", "created_at"),)


class PlanUsage(Base):
    """Uses of a plan's allowance: one counter per user, feature and UTC
    month ("YYYY-MM"), or `total` for an allowance in all (the free plan's
    taste of a feature), raised by a guarded UPDATE."""

    __tablename__ = "plan_usage"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    feature: Mapped[str] = mapped_column(String(40), primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True,
                                    default=lambda: uuid.uuid4().hex)
    kind: Mapped[str] = mapped_column(String(20), default="analysis")  # analysis | find | playbook | preflight | merge_plan
    repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    repo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="rules")
    days: Mapped[int] = mapped_column(Integer, default=7)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    user_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Where the model key came from: "server" (retired: "byok").
    key_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # An AI credit was spent on this job (refunded if it fails).
    charged: Mapped[bool] = mapped_column(Boolean, default=False)
    # Identical questions share a job: at most one queued/running job per key,
    # enforced by the partial unique index below, not by a read-then-insert.
    dedupe_key: Mapped[str | None] = mapped_column(String(260), nullable=True)
    # Lower runs first. User requests are 0; badge refreshes are BADGE_PRIORITY.
    priority: Mapped[int] = mapped_column(Integer, default=0)
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


BADGE_PRIORITY = 10
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
    # The engine's ENGINE_VERSION when the report was made. NULL (reports from
    # before the column) counts as older than every version.
    engine_version: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                       default=lambda: ENGINE_VERSION)

    __table_args__ = (Index("ix_reports_lookup", "repo_key", "mode", "days", "created_at"),)

    @property
    def outdated(self) -> bool:
        """Made by an older engine: its verdict or shape may be out of date,
        so no cache serves it as an answer."""
        return self.engine_version is None or self.engine_version < ENGINE_VERSION


def current_engine():
    """SQL filter: reports made by this engine version (or a newer one)."""
    return Report.engine_version >= ENGINE_VERSION


# `ping` gives up after this long, well inside the container health check's
# own timeout (deploy/*/compose.yml).
PING_TIMEOUT_S = 1.5
# How long `/metrics` waits for its own connection (two scrapes at once).
STATS_TIMEOUT_S = 2.0


class PoolMeter:
    """What the pool is asked for, counted for `/metrics` (metrics.py):
    requests waiting for a connection right now (or opening one), how long
    each waited, and how many gave up at `pool_timeout`."""

    def __init__(self) -> None:
        self.waiting = 0
        self.timeouts = 0
        # Called with each wait, in seconds.
        self.observe: Callable[[float], None] | None = None


def metered_pool(meter: PoolMeter) -> type[AsyncAdaptedQueuePool]:
    """The usual pool class, counting into `meter`. A class of its own per
    `Database`, so the pool SQLAlchemy builds again on `dispose` still counts.

    `_do_get` is SQLAlchemy's own (private) checkout step and where a request
    waits when every connection is out. test_server_metrics.py fails if an
    upgrade renames it."""

    class MeteredPool(AsyncAdaptedQueuePool):
        def _do_get(self):
            started = time.monotonic()
            meter.waiting += 1
            try:
                return super()._do_get()
            except PoolTimeout as exc:
                # `_do_get` may call itself: count a timeout once.
                if not getattr(exc, "counted", False):
                    exc.counted = True
                    meter.timeouts += 1
                raise
            finally:
                meter.waiting -= 1
                if meter.observe is not None:
                    meter.observe(time.monotonic() - started)

    return MeteredPool


class Database:
    """The pool every request and job takes its sessions from, and a few
    connections of their own beside it (`ping`, `advisory_lock`).

    A session holds a pool connection from its first statement until it
    commits, rolls back or closes, so keep that short: read, close, then call
    GitHub or do the slow work. `pool_size` connections are opened as they
    are needed and kept; a request waits `pool_timeout` seconds for one and
    then fails (HOLT_DB_POOL_SIZE, HOLT_DB_POOL_TIMEOUT).

    `max_overflow` (HOLT_DB_MAX_OVERFLOW) is 0 unless set: an overflow
    connection is opened under load and closed when given back, and opening
    one costs about 0.15 s of this process's CPU (asyncpg does Postgres's
    SCRAM password check in Python, on the event loop), so under the very load
    it is meant for it slows every request. A bigger `pool_size` costs that
    once.

    Every process's worst case has to fit in Postgres's `max_connections`:
    the budget is in deploy/prod/compose.yml.
    """

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 0,
                 pool_timeout: float = 10.0) -> None:
        connect: dict = {}
        pooled = True
        if url.startswith("sqlite"):
            connect["connect_args"] = {"check_same_thread": False}
            # An in-memory database is one connection, not a pool.
            pooled = make_url(url).database not in (None, "", ":memory:")
            if pooled:
                # SQLAlchemy's default for a file only since 2.0.38.
                connect["poolclass"] = AsyncAdaptedQueuePool
        else:
            connect["pool_pre_ping"] = True

        def pool(size: int, overflow: int, timeout: float) -> dict:
            return ({"pool_size": size, "max_overflow": overflow, "pool_timeout": timeout}
                    if pooled else {})

        # Waits on the main pool, for /metrics. The side engines aren't counted.
        self.pool_meter = PoolMeter()
        metered = {"poolclass": metered_pool(self.pool_meter)} if pooled else {}
        self.engine: AsyncEngine = create_async_engine(
            url, **{**connect, **metered}, **pool(pool_size, max_overflow, pool_timeout))
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)
        # The health check's own connection, kept open: it must answer while
        # every pool connection is busy, without opening one each time.
        self._health: AsyncEngine = create_async_engine(
            url, isolation_level="AUTOCOMMIT", **connect, **pool(1, 0, PING_TIMEOUT_S))
        # /metrics' own connection, kept open the same way: it has to say how
        # long the queue is while every pool connection is busy. Opened by the
        # first scrape, so a process nobody scrapes never opens it. (An
        # in-memory database is one connection: the main engine's.)
        self._stats: AsyncEngine = create_async_engine(
            url, isolation_level="AUTOCOMMIT", **connect,
            **pool(1, 0, STATS_TIMEOUT_S)) if pooled else self.engine
        # Advisory locks: a connection each, opened for the pass and closed
        # after it, so a lock held for minutes never takes a request's slot.
        self._locks: AsyncEngine = create_async_engine(
            url, poolclass=NullPool, isolation_level="AUTOCOMMIT",
            **{k: v for k, v in connect.items() if k == "connect_args"})

    async def migrate(self) -> None:
        """Bring the schema up to date (see `holt_server.migrate`)."""
        from holt_server.migrate import upgrade

        async with self.engine.begin() as conn:
            await conn.run_sync(upgrade)

    async def ping(self) -> bool:
        """Whether the database answers, asked on a connection of its own:
        a full pool is slow requests, not a dead database."""
        try:
            async with asyncio.timeout(PING_TIMEOUT_S):
                async with self._health.connect() as conn:
                    await conn.execute(text("select 1"))
            return True
        except Exception:
            return False

    @contextlib.asynccontextmanager
    async def stats(self) -> AsyncIterator[AsyncConnection]:
        """A connection for `/metrics`' few counting queries, outside the pool."""
        async with self._stats.connect() as conn:
            yield conn

    @contextlib.asynccontextmanager
    async def advisory_lock(self, lock_id: int) -> AsyncIterator[bool]:
        """Hold Postgres advisory lock `lock_id` for the block, so one process
        at a time does the work inside. Yields False when another process
        holds it. The lock lives on a connection of its own, not the pool's,
        and closing that connection lets it go whatever happens. Always True
        on other databases (one process)."""
        if self.engine.dialect.name != "postgresql":
            yield True
            return
        async with self._locks.connect() as conn:
            got = bool((await conn.execute(text("SELECT pg_try_advisory_lock(:id)"),
                                           {"id": lock_id})).scalar())
            yield got

    async def dispose(self) -> None:
        await self.engine.dispose()
        await self._health.dispose()
        await self._stats.dispose()
        await self._locks.dispose()


class FindCache(Base):
    """Finished `/v1/find` results by profile, so a repeated search is instant."""

    __tablename__ = "find_cache"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    params: Mapped[dict] = mapped_column(JSON)
    results: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @property
    def outdated(self) -> bool:
        """Screened by an older engine (`params.engine_version`, missing on
        results stored before it was recorded), or listing starter issues older
        rules picked (`params.starter_rules`): not served, searched again."""
        from holt_server.starter import current, rules_version

        params = self.params or {}
        version = params.get("engine_version")
        rules = params.get("starter_rules")
        return (not isinstance(version, int) or version < ENGINE_VERSION
                or rules != rules_version()
                or not all(current(r.get("issues") or [], rules) for r in self.results or []))


def find_key(languages: list[str], topics: list[str], hacktoberfest: bool, days: int) -> str:
    """Same search, same key: case, order and duplicates don't matter."""
    langs = ",".join(sorted({x.strip().lower() for x in languages if x.strip()}))
    tops = ",".join(sorted({x.strip().lower() for x in topics if x.strip()}))
    return f"l={langs};t={tops};h={int(bool(hacktoberfest))};d={days}"[:300]


class StarterCache(Base):
    """Starter issues per repository, so a report page view costs no GitHub call."""

    __tablename__ = "starter_cache"

    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    issues: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # `holt.starter.RULES_VERSION` of the rules that picked `issues`.
    rules_version: Mapped[int | None] = mapped_column(Integer, default=_rules_version)


class WarmFailure(Base):
    """A seed the warm pass couldn't make a report for, and when it may try
    again (warm.py): one row per repository, removed when a report is made.
    Without it a failing seed stayed "missing" and was first in every pass."""

    __tablename__ = "warm_failures"

    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    # The failed job's error code (API.md): upstream, not_found, internal;
    # or "timeout" when the job never finished.
    code: Mapped[str] = mapped_column(String(20))
    # Failures in a row; each one doubles the wait before the next try.
    failures: Mapped[int] = mapped_column(Integer, default=1)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Feedback(Base):
    """"Was this verdict right?" answers: one per person per report version.

    `report_id` is the report row the person was shown, so the answer stays
    tied to that exact version (and its verdict) after the repo is re-checked.
    `voter` is `user:<id>` when signed in, else `ip:<salted hash>`; the raw IP
    is never stored. See `holt_server.feedback`.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(Integer)
    repo: Mapped[str] = mapped_column(String(200))
    repo_key: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(10))
    days: Mapped[int] = mapped_column(Integer)
    # The report's own `generated_at`, and the verdict it showed.
    generated_at: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(40))
    vote: Mapped[str] = mapped_column(String(10))  # up | down
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voter: Mapped[str] = mapped_column(String(210))
    user_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ux_feedback_report_voter", "report_id", "voter", unique=True),
        Index("ix_feedback_updated", "updated_at"),
    )


class Usage(Base):
    """One row per analysis or search someone asked for, cached or not: the
    product numbers (deploy/prod/stats.sh). `who` is a hash of the user id or
    IP that changes every UTC day (usage.py), so it counts distinct people per
    day but can't be traced back or linked across days. Nothing else about
    the person is kept."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(String(10))  # "YYYY-MM-DD", UTC
    kind: Mapped[str] = mapped_column(String(10))  # analysis | find
    who: Mapped[str] = mapped_column(String(32))
    signed_in: Mapped[bool] = mapped_column(Boolean, default=False)
    repo_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_usage_day_kind", "day", "kind"),)


class GitHubConnection(Base):
    """A Holt user's connected GitHub account (connections.py). Only public
    data about it is ever read, with the server's tokens, never the user's.
    Deleting the row (disconnect) also deletes the user's `repo_views`."""

    __tablename__ = "github_connections"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # When they ticked "I'm 18 or older". Required to connect.
    adult_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # "Don't include me in statistics": leave them out of cross-user repo stats.
    stats_opt_out: Mapped[bool] = mapped_column(Boolean, default=False,
                                                server_default=text("false"))


class RepoView(Base):
    """Which report pages a connected user opened on Holt, one row per repo,
    so My Contributions can tell a PR opened soon after checking the repo here."""

    __tablename__ = "repo_views"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    views: Mapped[int] = mapped_column(Integer, default=1)


class ContributionSync(Base):
    """When a connected user's public pull requests were last fetched
    (contributions.py). The refresh cooldown reads `fetched_at`."""

    __tablename__ = "contribution_syncs"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    # The login the pull requests were searched for.
    login: Mapped[str] = mapped_column(String(100))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # GitHub had more than we keep (the fetch stops at a fixed number).
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)


class ContributionChoice(Base):
    """Whether a repository's pull requests count in a connected user's
    contribution numbers (contributions.py). A row is the person's own choice
    and wins over the default; no row means the default. Kept across fetches,
    deleted on disconnect."""

    __tablename__ = "contribution_choices"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    # owner/name as the pull requests showed it.
    repo: Mapped[str] = mapped_column(String(200))
    counted: Mapped[bool] = mapped_column(Boolean)
    chosen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Contribution(Base):
    """One public pull request a connected user opened, as GitHub last showed
    it. Replaced wholesale on every fetch; deleted on disconnect."""

    __tablename__ = "contributions"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500))
    state: Mapped[str] = mapped_column(String(10))  # open | merged | closed
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Where an open one stands (pr_state.py), read right after the search.
    # Empty ("unknown") for merged and closed ones, and when that read failed.
    node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    turn: Mapped[str] = mapped_column(String(10), default="unknown",
                                      server_default=text("'unknown'"))
    turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                              nullable=True)
    review_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The team member who spoke last after the author's last move, and what
    # they did: `changes` (asked for changes), `approved` or `reply`. Null
    # when the author acted last.
    reply_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reply_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)


class AlertSettings(Base):
    """A user's PR watch settings (alerts.py). A row exists once they have
    turned alerts on or saved a setting; deleted on disconnect."""

    __tablename__ = "alert_settings"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    # The top switch: off, Holt stops reading their pull requests for alerts.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where alert emails go: the address `web/` vouches for (the verified one
    # from sign-in). Null: the bell only.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # The Email switch; the one-click unsubscribe turns it off.
    email_on: Mapped[bool] = mapped_column(Boolean, default=True)
    # turn (your turn right away, the rest daily) | daily | all (everything
    # as it happens).
    email_mode: Mapped[str] = mapped_column(String(10), default="turn")
    # The user's local date of the last daily email run, so it runs once a day.
    last_daily_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # IANA name, from the browser when settings are saved.
    tz: Mapped[str] = mapped_column(String(64), default="UTC")
    # The unsubscribe token is HMAC(HOLT_SECRET_KEY, user id + this), never
    # stored; `unsubscribe_hash` is its SHA-256, to find the user by.
    unsubscribe_nonce: Mapped[str] = mapped_column(String(32))
    unsubscribe_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WatchMute(Base):
    """A pull request its author muted: no alerts for it. Its own table
    because `contributions` rows are replaced on every fetch."""

    __tablename__ = "watch_mutes"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    muted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Alert(Base):
    """One thing PR watch told a user about one of their pull requests. The
    line a person reads is built from `kind` and `facts` when it is shown
    (alerts.line), so a wording fix reaches old alerts too. Deleted after
    `alerts.KEEP_DAYS`, and on disconnect.

    kind: changes | reply | approved | late_reply | late_merge | stale_soon |
    merged | closed.
    email_via: how it was emailed: `now`, `daily`, or `failed` (the provider
    refused it for good). Null: not yet, or never.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    repo: Mapped[str] = mapped_column(String(200))
    repo_key: Mapped[str] = mapped_column(String(200))
    number: Mapped[int] = mapped_column(Integer)
    pr_url: Mapped[str] = mapped_column(String(500))
    pr_title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    # The numbers and names the line is built from.
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    # A hash of user + pull request + kind + the event's time: an event
    # alerts once, whichever read sees it first.
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_via: Mapped[str | None] = mapped_column(String(10), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_alerts_user", "user_id", "created_at"),
        Index("ix_alerts_unsent", "emailed_at", "created_at"),
    )


class AlertEmail(Base):
    """One alert email handed to the provider (mailer.py): the daily cap
    counts these, and support can tell what was sent. The address isn't
    copied here. status: sent | failed."""

    __tablename__ = "alert_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))  # now | daily
    alert_ids: Mapped[list] = mapped_column(JSON, default=list)
    # The provider's id for the message; its refusal's status when it failed.
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="sent")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_alert_emails_sent", "sent_at"),
                      Index("ix_alert_emails_user", "user_id", "sent_at"))


class AccountMail(Base):
    """Where a user's account emails go and whether they want the optional
    ones (account_mail.py). A row exists once `web/` has reported a sign-in,
    or once an email was due."""

    __tablename__ = "account_mail"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    # The address the user signed in with, as `web/` reports it at sign-in.
    # Null: not reported yet (the alert settings' address is used, if any).
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # The "product emails" switch: the welcome and the two "ending" emails.
    # The one-click unsubscribe turns it off. A receipt goes out either way.
    product_on: Mapped[bool] = mapped_column(Boolean, default=True)
    # When the account's first sign-in was reported: the welcome email is due
    # from then, for a day. Null: the account is older than these emails.
    welcome_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)
    # As on `alert_settings`: the token is never stored, only its hash.
    unsubscribe_nonce: Mapped[str] = mapped_column(String(32))
    unsubscribe_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountEmail(Base):
    """The sent-log of account emails: one row per (user, `key`), so each
    goes out once. `key` is the email's kind, with what it is about when
    there can be several ("receipt:<order id>", "pass_ending:<date>"). The row
    is written before the send (`pending`) and is what stops a second one.
    The address isn't copied here. status: pending | sent | failed."""

    __tablename__ = "account_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    # welcome | receipt | trial_ending | trial_ended | pass_ending
    kind: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(80))
    # The provider's id for the message; its refusal's status when it failed.
    provider_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_account_emails_user_key"),
                      Index("ix_account_emails_sent", "sent_at"))


class RepoMeta(Base):
    """What GitHub says about a repository Holt has a report for: the details
    a Discover card shows and filters on (discover.py), and the report's
    "About this repo" (`schema.RepoAbout`). Read right after the
    repo's report is stored (meta_refresh.py) and daily by the warm pass,
    many repositories per GraphQL query."""

    __tablename__ = "repo_meta"

    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    # GitHub's casing, as it answered.
    repo: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # GitHub's primary language, then a second one when it is a real share of
    # the code (github.main_languages). `language` stays the filter.
    languages: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    fork: Mapped[bool] = mapped_column(Boolean, default=False)
    # The report's "About this repo" (0021); null until the details are read
    # again after that migration.
    forks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_issues: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Pull requests ever opened, how many are open, and people who committed (0024).
    pull_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_pull_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contributors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license: Mapped[str | None] = mapped_column(String(80), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # [{"name": "Python", "share": 0.92}, ...], biggest first, at most three.
    language_shares: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The repository this one is a fork of.
    fork_of: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # The README's first sentence (holt/about.py), not the README.
    readme_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The top of the README, Markdown, for the report's README section (0027).
    readme: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where a newcomer finds help (0025): [{"kind": "contributing", "url": …}, …].
    links: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # {"tag", "published_at", "url"} of GitHub's latest release, or null.
    latest_release: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The most active committers (0028): [{"login", "name", "url", "avatar_url",
    # "contributions"}, …], GitHub's order, bots left out. Null until read.
    top_contributors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Profile(Base):
    """What a signed-in user told us about themselves (profiles.py), so /find
    and /hacktoberfest start from it. Stated, never inferred."""

    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    days: Mapped[int] = mapped_column(Integer, default=7)
    # code | docs | tests | design | translations
    contributions: Mapped[list] = mapped_column(JSON, default=list)
    # newcomer | experienced
    level: Mapped[str] = mapped_column(String(20), default="newcomer")
    # When they ticked "I'm 18 or older" here. Null when they had already
    # confirmed it by connecting GitHub.
    adult_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                                nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RepoUserStats(Base):
    """What connected Holt users' pull requests to one repository came to
    (repo_stats.py): counts only, never who. A row exists only while at least
    `repo_stats.MIN_PEOPLE` people who didn't opt out make up the numbers.
    Rebuilt by the daily contributions refresh; a user's repositories are
    rebuilt at once when they opt out or disconnect."""

    __tablename__ = "repo_user_stats"

    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    people: Mapped[int] = mapped_column(Integer)
    pull_requests: Mapped[int] = mapped_column(Integer)
    merged: Mapped[int] = mapped_column(Integer)
    closed: Mapped[int] = mapped_column(Integer)
    waiting: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Playbook(Base):
    """The latest "How to get merged here" playbook per repository
    (playbook.py), as the paid-features service wrote it. Replaced when a
    newer one is written."""

    __tablename__ = "playbooks"

    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    playbook: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlaybookUnlock(Base):
    """A user who paid for one repository's playbook. `paid` is what
    `entitlements.charge` took (kept for the refund); `job_id` is the job the
    playbook was still being written by, or NULL when it was served from the
    cache. If that job fails, the row is deleted and `paid` given back."""

    __tablename__ = "playbook_unlocks"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    paid: Mapped[dict] = mapped_column(JSON)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_playbook_unlocks_job", "job_id"),)


class MergePlan(Base):
    """A user's latest merge plan for one repository (merge_plan.py), as the
    paid-features service wrote it and mapped to the public shape. Replaced
    when they ask for a newer one; a paid result, so it is kept until then."""

    __tablename__ = "merge_plans"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200))
    plan: Mapped[dict] = mapped_column(JSON)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Preflight(Base):
    """A finished PR pre-flight check (preflight.py): one per user, target
    (`pr:12` or `branch:...`) and head commit, replaced when that commit is
    checked again."""

    __tablename__ = "preflights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(200))
    repo_key: Mapped[str] = mapped_column(String(200))
    repo: Mapped[str] = mapped_column(String(200))
    target: Mapped[str] = mapped_column(String(300))
    head_sha: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ix_preflights_target", "user_id", "repo_key", "target", "created_at"),
    )


class AiBudget(Base):
    """One row, id 1: what this environment has committed to AI models, in
    micro-dollars (budget.py). It is the sum over `ai_runs` of each run's
    cost, or of what it holds while it runs. Raised only by a guarded
    `UPDATE`, so racing runs can't take it past `HOLT_AI_BUDGET_USD`."""

    __tablename__ = "ai_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    committed_micros: Mapped[int] = mapped_column(BigInteger, default=0)


class AiRun(Base):
    """One AI run's claim on the budget: an AI report, or a playbook or
    pre-flight summary from the paid-features service. `reserved_micros` is
    held when the job is queued; `cost_micros` is what the run cost, recorded
    when it ends (`estimated` when it isn't known, e.g. a run that timed out,
    and it is then counted at the reservation). `model` is the model id it
    ran on, recorded then too, for comparing models offline; it is never
    shown to anyone."""

    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(20))
    reserved_micros: Mapped[int] = mapped_column(BigInteger)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_ai_runs_job", "job_id"),)


class SavedRepo(Base):
    """A repository a signed-in user saved to come back to later (saved.py).
    One row per user and repo; saving again keeps the first `saved_at`."""

    __tablename__ = "saved_repos"

    user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    # owner/name as it was saved (GitHub's casing when Holt knows it).
    repo: Mapped[str] = mapped_column(String(200))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (Index("ix_saved_repos_user", "user_id", "saved_at"),)
