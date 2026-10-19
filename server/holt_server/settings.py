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
    # The database connection pool of this process (db.py): connections it
    # opens as needed and keeps, extra ones opened under load and closed
    # after (0: opening one is slow, see db.py), and how long a request waits
    # for one before it fails (seconds; under the web app's 20 s). Size it
    # with Postgres's max_connections: the budget is in deploy/prod/compose.yml.
    db_pool_size: int = Field(10, ge=1, alias="HOLT_DB_POOL_SIZE")
    db_max_overflow: int = Field(0, ge=0, alias="HOLT_DB_MAX_OVERFLOW")
    db_pool_timeout: float = Field(10, gt=0, alias="HOLT_DB_POOL_TIMEOUT")
    internal_key: str = Field("", alias="HOLT_INTERNAL_KEY")
    # Server secret for keyed hashes (usage counting).
    secret_key: str = Field("", alias="HOLT_SECRET_KEY")
    # Where the badge links to: `{web_url}/{owner}/{repo}`.
    web_url: str = Field("https://githolt.com", alias="HOLT_WEB_URL")

    github_tokens: str = Field("", alias="GITHUB_TOKENS")
    # The Holt GitHub App (github_app.py). With all three set, the server reads
    # GitHub as the app and GITHUB_TOKENS is not used; with none, it is.
    github_app_id: str = Field("", alias="GITHUB_APP_ID")
    github_app_installation_id: str = Field("", alias="GITHUB_APP_INSTALLATION_ID")
    # A path to the .pem (mounted read-only), or the key itself.
    github_app_private_key_file: str = Field("", alias="GITHUB_APP_PRIVATE_KEY_FILE")
    github_app_private_key: str = Field("", alias="GITHUB_APP_PRIVATE_KEY", repr=False)

    # The optional internal service for paid features. Empty URL = off.
    pro_url: str = Field("", alias="HOLT_PRO_URL")
    pro_key: str = Field("", alias="HOLT_PRO_KEY")
    # How long a written playbook is served before the next unlock asks the
    # service for a new one. Playbook jobs use HOLT_JOB_TIMEOUT_AI.
    playbook_cache_hours: float = Field(168, alias="HOLT_PLAYBOOK_CACHE_HOURS")

    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("openai/gpt-5-mini", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field("https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    # Which dialect that endpoint speaks: "openrouter", "openai" or "gemini".
    # Empty: read from OPENROUTER_BASE_URL (api.openai.com means OpenAI's own
    # API, which wants `max_completion_tokens` and a model id without "openai/").
    model_provider: str = Field("", alias="HOLT_MODEL_PROVIDER")
    # "minimal" | "low" | "medium" | "high" for reasoning models; empty sends
    # nothing and the provider's default applies.
    model_reasoning_effort: str = Field("", alias="HOLT_MODEL_REASONING_EFFORT")
    # The most this environment may spend on AI models, in USD, over its whole
    # life: AI reports and the paid-features service's playbooks and summaries
    # together (budget.py). 0 = AI off. With HOLT_ENV=production a budget
    # counts only with HOLT_AI_BUDGET_OWNER_OK=1 as well, the owner's explicit
    # say-so; without it AI stays off and the server logs an error.
    ai_budget_usd: float = Field(0.0, ge=0, alias="HOLT_AI_BUDGET_USD")
    ai_budget_owner_ok: bool = Field(False, alias="HOLT_AI_BUDGET_OWNER_OK")
    # What one run may cost at most: held from the budget when it is queued
    # and given back, less what it really cost, when it ends. An AI report's
    # model calls are refused once the next one could take it past this.
    ai_run_max_usd: float = Field(0.10, gt=0, alias="HOLT_AI_RUN_MAX_USD")
    # The same for a playbook or pre-flight summary written by the service.
    ai_pro_run_max_usd: float = Field(0.05, gt=0, alias="HOLT_AI_PRO_RUN_MAX_USD")

    # Analyses and finds running at once for people (the user lane). Each is a
    # worker thread holding one crawl in memory; see deploy/prod/compose.yml.
    job_concurrency: int = Field(2, alias="HOLT_JOB_CONCURRENCY")
    # A job running longer than this is stopped and fails with a plain
    # "took too long" error (seconds; rules reports, AI reports, find).
    job_timeout_rules: float = Field(180, alias="HOLT_JOB_TIMEOUT_RULES")
    job_timeout_ai: float = Field(480, alias="HOLT_JOB_TIMEOUT_AI")
    job_timeout_find: float = Field(300, alias="HOLT_JOB_TIMEOUT_FIND")
    cache_hours: float = Field(24, alias="HOLT_CACHE_HOURS")
    # Free AI credits: given once to every signed-in user, then one more can
    # be claimed each time this many days have passed since the last claim.
    # 0 (the default since the merge plan's free taste replaced them): a new
    # account gets none and nothing to claim; users who already had the
    # welcome grant keep their credits and their weekly claim.
    signup_ai_credits: int = Field(0, ge=0, alias="HOLT_SIGNUP_AI_CREDITS")
    claim_every_days: float = Field(7, alias="HOLT_CLAIM_EVERY_DAYS")
    # Features, plans and passes (pricing.py). Empty: the packaged
    # holt_server/pricing.json, where no pass is on sale.
    pricing_file: str = Field("", alias="HOLT_PRICING_FILE")
    # Pass checkout (payments.py). Off unless this is 1 AND the Razorpay keys
    # are set: with it off, no pass is offered and no order can be created.
    # Orders already paid for are still confirmed.
    payments_enabled: bool = Field(False, alias="HOLT_PAYMENTS_ENABLED")
    # 1 puts every pass in the pricing file on sale, whatever its `on_sale`
    # says: for trying checkout on staging with Razorpay test keys. Ignored
    # with HOLT_ENV=production, where only the pricing file decides.
    passes_on_sale: bool = Field(False, alias="HOLT_PASSES_ON_SALE")
    razorpay_key_id: str = Field("", alias="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field("", alias="RAZORPAY_KEY_SECRET")
    # Set in the Razorpay dashboard with the webhook URL. Empty: webhooks refused.
    razorpay_webhook_secret: str = Field("", alias="RAZORPAY_WEBHOOK_SECRET")
    # User ids (comma-separated) that may read /v1/admin/*. Empty: nobody.
    admin_users: str = Field("", alias="HOLT_ADMIN_USERS")
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
    # The background lane: workers of their own for badge refreshes and warm
    # passes, on top of HOLT_JOB_CONCURRENCY. They take a person's queued job
    # first whenever one is waiting. 0 turns badge and warm work off.
    badge_concurrency: int = Field(1, alias="HOLT_BADGE_CONCURRENCY")
    # Warm cache (see warm.py). 0 hours = no in-process schedule.
    warm_interval_hours: float = Field(0, alias="HOLT_WARM_INTERVAL_HOURS")
    warm_seeds_file: str = Field("", alias="HOLT_WARM_SEEDS")
    # Reports younger than this are not re-run by a warm pass.
    warm_max_age_hours: float = Field(20, alias="HOLT_WARM_MAX_AGE_HOURS")
    # Stop a warm pass when any GitHub token has fewer GraphQL points left.
    warm_min_points: int = Field(1500, alias="HOLT_WARM_MIN_POINTS")
    # A warm pass reads repo details, oldest first, for at most this long;
    # the rest wait for the next pass. 0 = no limit.
    meta_max_minutes: float = Field(15, ge=0, alias="HOLT_META_MAX_MINUTES")
    # Report jobs a warm pass keeps in flight at once. They run in the
    # background lane, so HOLT_BADGE_CONCURRENCY should be at least this.
    warm_parallel: int = Field(3, ge=1, alias="HOLT_WARM_PARALLEL")
    # The refresh tiers' ages (deploy/prod/warm-refresh.sh): repos someone
    # saved or viewed lately, and the rest of the seed list.
    refresh_weekly_hours: float = Field(168, gt=0, alias="HOLT_REFRESH_WEEKLY_HOURS")
    refresh_monthly_hours: float = Field(720, gt=0, alias="HOLT_REFRESH_MONTHLY_HOURS")
    # My Contributions: re-read connected users' pull requests this often, in
    # the background (contributions.py). 0 = no background refresh.
    contributions_refresh_hours: float = Field(24, alias="HOLT_CONTRIBUTIONS_REFRESH_HOURS")
    # PR watch (alerts.py, watch.py, mailer.py). Off by default: with it off
    # nothing checks pull requests, makes alerts or sends email, and alerts
    # can't be turned on. The owner switches it on deliberately.
    pr_watch: bool = Field(False, alias="HOLT_PR_WATCH")
    # Minutes between checks of watched pull requests.
    pr_watch_minutes: float = Field(30, gt=0, alias="HOLT_PR_WATCH_MINUTES")
    # Alert emails go through Resend's HTTP API. Empty key: no email is sent
    # (alerts still reach the bell).
    resend_api_key: str = Field("", alias="RESEND_API_KEY", repr=False)
    alert_email_from: str = Field("Holt <alerts@githolt.com>", alias="HOLT_ALERT_EMAIL_FROM")
    alert_email_reply_to: str = Field("hello@githolt.com", alias="HOLT_ALERT_EMAIL_REPLY_TO")
    # The provider's daily sending limit (Resend's free tier: 100). The
    # mailer stops 5 short of it over any 24 hours.
    alert_email_daily_limit: int = Field(100, ge=0, alias="HOLT_ALERT_EMAIL_DAILY_LIMIT")
    # Account emails (account_mail.py): the welcome, a pass's receipt, and
    # the "ending" ones. Off by default: with it off none is sent. They go
    # through the same provider and count against the same daily limit.
    account_emails: bool = Field(False, alias="HOLT_ACCOUNT_EMAILS")
    # How long a finished /v1/find result is served for the same search.
    find_cache_hours: float = Field(6, alias="HOLT_FIND_CACHE_HOURS")
    # Pull-request pages crawled per analysis (25 PRs a page).
    max_pages: int = Field(8, alias="HOLT_MAX_PAGES")
    # Evidence snapshots (evidence_store.py): the evidence each report read,
    # one gzipped file per report under this directory. Empty = none kept.
    evidence_dir: str = Field("", alias="HOLT_EVIDENCE_DIR")
    # Delete a repo's snapshots older than this many days (its newest always
    # stays). 0 = keep every one.
    evidence_keep_days: float = Field(0, ge=0, alias="HOLT_EVIDENCE_KEEP_DAYS")
    # `warm --stale-only` makes a report again from a snapshot younger than
    # its repo's refresh tier (above), or than this if it is longer, instead
    # of reading GitHub. 0 = always read GitHub.
    evidence_reuse_hours: float = Field(168, ge=0, alias="HOLT_EVIDENCE_REUSE_HOURS")

    @property
    def sell_every_pass(self) -> bool:
        """Whether HOLT_PASSES_ON_SALE applies here: never in production."""
        return self.passes_on_sale and self.env != "production"

    @property
    def token_list(self) -> list[str]:
        return [t.strip() for t in self.github_tokens.split(",") if t.strip()]

    @property
    def admin_user_ids(self) -> frozenset[str]:
        return frozenset(u.strip() for u in self.admin_users.split(",") if u.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
