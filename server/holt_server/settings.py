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
    # How many AI reports a user may run on the server's key per calendar month.
    free_ai_limit: int = Field(3, alias="HOLT_FREE_AI_LIMIT")
    plan_ai_limit: int = Field(100, alias="HOLT_PLAN_AI_LIMIT")
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
    # Warm cache (see warm.py). 0 hours = no in-process schedule.
    warm_interval_hours: float = Field(0, alias="HOLT_WARM_INTERVAL_HOURS")
    warm_seeds_file: str = Field("", alias="HOLT_WARM_SEEDS")
    # Reports younger than this are not re-run by a warm pass.
    warm_max_age_hours: float = Field(20, alias="HOLT_WARM_MAX_AGE_HOURS")
    # Stop a warm pass when any GitHub token has fewer GraphQL points left.
    warm_min_points: int = Field(1500, alias="HOLT_WARM_MIN_POINTS")
    # How long a finished /v1/find result is served for the same search.
    find_cache_hours: float = Field(6, alias="HOLT_FIND_CACHE_HOURS")
    # Pull-request pages crawled per analysis (25 PRs a page).
    max_pages: int = Field(8, alias="HOLT_MAX_PAGES")

    @property
    def token_list(self) -> list[str]:
        return [t.strip() for t in self.github_tokens.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
