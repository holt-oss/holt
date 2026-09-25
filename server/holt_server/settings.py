"""Configuration, all of it from the environment (or `server/.env`).

Names are the ones in `server/README.md`. Nothing here has a default that is
unsafe in production except `HOLT_INTERNAL_KEY` and `HOLT_SECRET_KEY`, which
are empty by default and make the server refuse the requests that need them.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "dev" serves /docs and /openapi.json; anything else does not.
    env: str = Field("production", alias="HOLT_ENV")
    database_url: str = Field(
        "postgresql+asyncpg://holt:holt@127.0.0.1:20131/holt", alias="DATABASE_URL"
    )
    # Run database migrations when the server starts (under a lock, so
    # replicas take turns). Turn off when a separate migrate step runs them.
    migrate_on_startup: bool = Field(True, alias="HOLT_MIGRATE_ON_STARTUP")
    internal_key: str = Field("", alias="HOLT_INTERNAL_KEY")
    secret_key: str = Field("", alias="HOLT_SECRET_KEY")
    # Where the badge links to: `{web_url}/{owner}/{repo}`.
    web_url: str = Field("https://holt.dev", alias="HOLT_WEB_URL")

    github_tokens: str = Field("", alias="GITHUB_TOKENS")

    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("openai/gpt-5-mini", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field("https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    job_concurrency: int = Field(2, alias="HOLT_JOB_CONCURRENCY")
    cache_hours: float = Field(24, alias="HOLT_CACHE_HOURS")
    # Plans, allowances and prices: plans.toml next to this file, or this path.
    plans_file: str = Field("", alias="HOLT_PLANS_FILE")
    # A paid plan stays on this long past its period end while the renewal
    # webhook is on its way (or Razorpay is retrying a failed charge).
    billing_grace_hours: float = Field(24, alias="HOLT_BILLING_GRACE_HOURS")
    # Billing cycles a Razorpay subscription is created for (it needs a number).
    subscription_cycles: int = Field(120, alias="HOLT_SUBSCRIPTION_CYCLES")
    razorpay_key_id: str = Field("", alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field("", alias="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field("", alias="RAZORPAY_WEBHOOK_SECRET")
    # New work (jobs, starter-issue lookups) per hour.
    anon_rate_per_hour: int = Field(10, alias="HOLT_ANON_RATE_PER_HOUR")
    user_rate_per_hour: int = Field(60, alias="HOLT_USER_RATE_PER_HOUR")
    # Reads that miss the cache (starter issues): a separate, generous bucket,
    # so viewing and reloading report pages never uses up the work bucket above.
    anon_read_rate_per_hour: int = Field(120, alias="HOLT_ANON_READ_RATE_PER_HOUR")
    user_read_rate_per_hour: int = Field(600, alias="HOLT_USER_READ_RATE_PER_HOUR")
    # How long starter issues for a repository are served from the cache.
    starter_cache_hours: float = Field(1, alias="HOLT_STARTER_CACHE_HOURS")
    # Rules checks queued by public badge requests: per client IP, and in total.
    # Separate from the buckets user requests draw from.
    badge_rate_per_ip: int = Field(20, alias="HOLT_BADGE_RATE_PER_IP")
    badge_rate_total: int = Field(60, alias="HOLT_BADGE_RATE_TOTAL")
    # Badge refreshes running at once, at most. They also queue behind user jobs.
    badge_concurrency: int = Field(1, alias="HOLT_BADGE_CONCURRENCY")
    # Pull-request pages crawled per analysis (25 PRs a page).
    max_pages: int = Field(8, alias="HOLT_MAX_PAGES")

    @property
    def token_list(self) -> list[str]:
        return [t.strip() for t in self.github_tokens.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
