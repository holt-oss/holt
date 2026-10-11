"""Everything a request or a job needs, in one object the tests can swap parts of."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from holt_server import budget, engine, llm, mailer, payments, payments_dodo, pro
from holt_server.db import Database, Job
from holt_server.errors import ApiError
from holt_server.evidence_store import EvidenceStore
from holt_server.github import GitHubLookup, build_pool
from holt_server.jobs import JobRunner
from holt_server.metrics import Metrics
from holt_server.ratelimit import RateLimiter
from holt_server.settings import Settings

CANONICAL_CACHE = 2048


class Services:
    def __init__(self, settings: Settings, db: Database | None = None) -> None:
        self.settings = settings
        self.db = db or Database(
            settings.database_url, pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout)
        # One connection pool for every GitHub call this process makes.
        self.http = httpx.Client(timeout=30.0)
        # The GitHub App if it is set up, else GITHUB_TOKENS.
        self.pool = build_pool(settings, self.http)
        self.lookup = GitHubLookup(self.pool, self.http)
        # Paid features: None when HOLT_PRO_URL is not set.
        self.pro: pro.ProClient | None = pro.build(settings)
        # Credit-pack checkout: None when the Razorpay keys are not set.
        self.razorpay: payments.Razorpay | None = payments.build(settings)
        # USD checkout: None without Dodo's key (or with a DODO_ENV it doesn't know).
        self.dodo: payments_dodo.Dodo | None = payments_dodo.build(settings)
        # Alert and account emails: None (no email sent) without RESEND_API_KEY.
        self.mailer: mailer.Mailer | None = mailer.build(settings, self.http)
        # Work (new analyses, find) and reads (cache misses on starter issues)
        # draw on separate counters.
        self.limiter = RateLimiter()
        self.read_limiter = RateLimiter()
        # Single-flight: concurrent cache misses for one repo share one fetch.
        self.inflight: dict[str, Any] = {}
        # Its own counters: badge traffic never uses up what user requests draw on.
        self.badge_limiter = RateLimiter()
        # The evidence each report read, kept on disk (off without HOLT_EVIDENCE_DIR).
        self.evidence = EvidenceStore(settings.evidence_dir, settings.evidence_keep_days)
        self.runner = JobRunner(self, settings.job_concurrency, settings.badge_concurrency)
        # What `GET /metrics` serves (metrics.py).
        self.metrics = Metrics(self)
        self._canonical: OrderedDict[str, str] = OrderedDict()
        # Swappable seams. Tests replace these; production uses the defaults.
        self.provider_factory: Callable[[str, datetime], Any] = self._live_provider
        self.model_factory: Callable[[llm.ModelSpec], Any] = llm.build
        self.analysis_fn: Callable[..., dict[str, Any]] = engine.analyze
        # What each running AI job's model work cost, when the job learns it
        # (budget.py): playbook and pre-flight jobs put it here for `_finish`.
        self.ai_costs: dict[str, float | None] = {}
        # And which model did it, for `ai_runs.model`.
        self.ai_models: dict[str, str | None] = {}

    def _live_provider(self, repo: str, as_of: datetime):
        # The pool's transport: it skips dead or used-up tokens and hears back
        # how many points each one has left.
        return engine.live_provider(None, as_of, self.settings.max_pages,
                                    transport=self.pool.transport(self.http))

    async def canonical(self, repo: str) -> str:
        """GitHub's casing for `repo`, or `not_found`. Remembered per process."""
        key = repo.lower()
        if key in self._canonical:
            self._canonical.move_to_end(key)
            return self._canonical[key]
        name = (await self.lookup.repo(repo)).name_with_owner
        self._canonical[key] = name
        while len(self._canonical) > CANONICAL_CACHE:
            self._canonical.popitem(last=False)
        return name

    def require_pro(self) -> pro.ProClient:
        """The paid-feature client, or the "not available yet" error."""
        if self.pro is None:
            raise pro.not_available()
        return self.pro

    def ai_on(self) -> bool:
        """AI work may be queued at all: there is a budget (budget.py)."""
        return budget.limit_usd(self.settings) > 0

    def server_model_available(self) -> bool:
        s = self.settings
        return (bool(s.openrouter_api_key) and self.ai_on()
                and budget.resolve_price(s.openrouter_model)[0] is not None)

    async def model_spec_for(self, job: Job) -> llm.ModelSpec:
        s = self.settings
        if not self.server_model_available():
            # Refused before queueing too; this covers a key removed since.
            raise ApiError("ai_unavailable", "AI reports aren't switched on yet. "
                           "Your free AI report was not used up.")
        return llm.ModelSpec(
            provider=s.model_provider or llm.provider_for(s.openrouter_base_url),
            model=s.openrouter_model, api_key=s.openrouter_api_key,
            base_url=s.openrouter_base_url, reasoning_effort=s.model_reasoning_effort)
