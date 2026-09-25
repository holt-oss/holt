"""Everything a request or a job needs, in one object the tests can swap parts of."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from holt_server import crypto, engine, llm, plans
from holt_server.db import Database, Job, User
from holt_server.errors import ApiError
from holt_server.github import GitHubLookup, TokenPool
from holt_server.jobs import JobRunner
from holt_server.ratelimit import RateLimiter
from holt_server.settings import Settings

CANONICAL_CACHE = 2048


class Services:
    def __init__(self, settings: Settings, db: Database | None = None) -> None:
        self.settings = settings
        self.db = db or Database(settings.database_url)
        self.pool = TokenPool(settings.token_list)
        # One connection pool for every GitHub call this process makes.
        self.http = httpx.Client(timeout=30.0)
        self.lookup = GitHubLookup(self.pool, self.http)
        # Work (new analyses, find) and reads (cache misses on starter issues)
        # draw on separate counters.
        self.limiter = RateLimiter()
        self.read_limiter = RateLimiter()
        # Single-flight: concurrent cache misses for one repo share one fetch.
        self.inflight: dict[str, Any] = {}
        # Its own counters: badge traffic never uses up what user requests draw on.
        self.badge_limiter = RateLimiter()
        self.runner = JobRunner(self, settings.job_concurrency, settings.badge_concurrency)
        self._canonical: OrderedDict[str, str] = OrderedDict()
        self.catalog = plans.load(settings.plans_file or None)
        self.grace = timedelta(hours=settings.billing_grace_hours)
        # None until the Razorpay keys are set; billing endpoints then say so.
        self.payments = None
        if settings.razorpay_key_id and settings.razorpay_key_secret:
            from holt_server.billing.razorpay import Razorpay

            self.payments = Razorpay(settings.razorpay_key_id,
                                     settings.razorpay_key_secret,
                                     settings.razorpay_webhook_secret)
        # Swappable seams. Tests replace these; production uses the defaults.
        self.provider_factory: Callable[[str, datetime], Any] = self._live_provider
        self.model_factory: Callable[[llm.ModelSpec], Any] = llm.build
        self.analysis_fn: Callable[..., dict[str, Any]] = engine.analyze

    def _live_provider(self, repo: str, as_of: datetime):
        return engine.live_provider(self.pool.next(), as_of, self.settings.max_pages,
                                    http=self.http)

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

    def server_model_available(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    async def model_spec_for(self, job: Job) -> llm.ModelSpec:
        s = self.settings
        if job.key_source == "byok" and job.user_id:
            async with self.db.session() as session:
                user = await session.get(User, job.user_id)
            if user is None or not user.byok_cipher:
                raise ApiError("needs_key", "Your saved API key was removed before "
                               "this report could run. Add a key or use a free report.")
            try:
                key = crypto.decrypt(s.secret_key, user.byok_cipher, user.id)
            except Exception as exc:
                raise ApiError("needs_key", "We couldn't read your saved API key. "
                               "Please save it again in your settings.") from exc
            provider = user.byok_provider or "openrouter"
            return llm.ModelSpec(
                provider=provider,
                model=user.byok_model or llm.DEFAULT_MODELS.get(provider, ""),
                api_key=key,
                byok=True,
            )
        if not s.openrouter_api_key:
            raise ApiError("needs_key", "AI reports aren't available on this server "
                           "right now. Add your own API key in settings to run one.")
        return llm.ModelSpec(provider="openrouter", model=s.openrouter_model,
                             api_key=s.openrouter_api_key, base_url=s.openrouter_base_url)
