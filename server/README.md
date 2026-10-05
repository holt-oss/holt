# Holt API server

The HTTP API behind the Holt web app. It wraps the engine in `src/holt` and
implements [`API.md`](../API.md), which is the contract with `web/`.

FastAPI, Postgres (SQLAlchemy async + asyncpg), and an in-process jobs runner.
No Redis: jobs live in a Postgres table and run in worker threads, in two
lanes: `HOLT_JOB_CONCURRENCY` workers for people's jobs, and
`HOLT_BADGE_CONCURRENCY` background workers for badge refreshes and warm
passes (they take a waiting person's job first). Each job has a time limit.
While a job waits, its event stream says its place in the queue.

## Run it locally

```sh
export PATH="$HOME/.local/bin:$PATH"
uv sync                                   # from the repo root; installs holt-server too

docker compose -f server/compose.yml up -d   # Postgres on 127.0.0.1:${HOLT_API_DB_PORT:-20131}
cp server/.env.example server/.env           # then fill it in (see below)

cd server
PORT=20130 uv run holt-server              # http://127.0.0.1:20130, docs at /docs
curl localhost:20130/health
```

`holt-server` reads `server/.env` when started from `server/`, plus the process
environment (which wins). The schema is brought up to date on startup (see
[Changing the schema](#changing-the-schema)).
Stop Postgres with `docker compose -f server/compose.yml down` (add `-v` to
drop the data). Its service (`api-db`), volume and port variable
(`HOLT_API_DB_PORT`) differ from `web/compose.yml`'s, so the two databases can
run side by side under one `$COMPOSE_PROJECT_NAME`; or skip this one and give
the API a second database in the web app's Postgres
([`docs/DEV-WORKFLOW.md`](../docs/DEV-WORKFLOW.md#2-real-data-on-your-machine)).

A quick check with a real repository:

```sh
K="X-Holt-Internal-Key: $HOLT_INTERNAL_KEY"
curl -s -XPOST localhost:20130/v1/analyses -H "$K" -H 'content-type: application/json' \
  -d '{"repo": "pallets/flask"}'                       # -> 202 {"job_id": ...}
curl -sN localhost:20130/v1/analyses/<job_id>/events -H "$K"   # stage ... done
```

## Environment

| Variable | Default | What it does |
|---|---|---|
| `HOLT_ENV` | `production` | `dev` serves the interactive docs at `/docs` and `/openapi.json`; otherwise they are off. |
| `DATABASE_URL` | `postgresql+asyncpg://holt:holt@127.0.0.1:20131/holt` | SQLAlchemy async URL. `sqlite+aiosqlite:///path.db` works for quick experiments. |
| `HOLT_DB_POOL_SIZE` | `10` | Database connections this process opens as it needs them and keeps. A session holds one only between its first statement and its commit or close, a few milliseconds, so ten serve the job workers and the page requests together. Every process's pool has to fit in Postgres's `max_connections`: the budget is in `deploy/prod/compose.yml`. |
| `HOLT_DB_MAX_OVERFLOW` | `0` | Extra connections opened when the pool is all in use, and closed when given back. Off: opening a connection takes about 0.15 s of the server's CPU (the password check runs in Python), so opening them under load slows every request. Raise `HOLT_DB_POOL_SIZE` instead. |
| `HOLT_DB_POOL_TIMEOUT` | `10` | Seconds a request waits for a free connection before it fails. Under the web app's 20 s, so a request never waits after its caller gave up. |
| `HOLT_INTERNAL_KEY` | *(empty)* | Shared secret with `web/`. Every `/v1` request must send it as `X-Holt-Internal-Key`. Empty means every `/v1` request is refused. |
| `HOLT_SECRET_KEY` | *(empty)* | Server secret for keyed hashes (usage counting). Use 32 random bytes, base64: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`. |
| `HOLT_WEB_URL` | `https://githolt.com` | The badge links to `{HOLT_WEB_URL}/{owner}/{repo}`. |
| `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID` | *(empty)* | The Holt GitHub App and its installation on `holt-oss`. With these and a private key set, the server reads GitHub as the app: it signs a 9-minute JWT, trades it for an installation token, and fetches the next one 10 minutes before the hour is up (`holt_server/github_app.py`). `GITHUB_TOKENS` is then not used. Set all of them or none: a partial setup stops the server at startup. `python -m holt_server.github_app` prints the app, its points left and whether it can read public repositories, never a secret. Setup and the reasons for an App are in the maintainers' ops notes. |
| `GITHUB_APP_PRIVATE_KEY_FILE` | *(empty)* | Path to the app's `.pem` private key (in the deploys, mounted read-only). `GITHUB_APP_PRIVATE_KEY` takes the key itself instead, with `\n` for line breaks if it is on one line. Never logged. |
| `GITHUB_TOKENS` | *(empty)* | Used when the GitHub App isn't set up. Comma-separated GitHub tokens, used round-robin, one per analysis. A token GitHub refuses is left out for 10 minutes, and one that is rate-limited or nearly used up (points left, read from every reply) until it resets; logs name tokens by position (`token #2`), or "the GitHub App", never by value. Read-only public access is enough (a fine-grained token with no extra permissions). |
| `HOLT_PRO_URL` | *(empty)* | Base URL of the optional internal service that runs paid features (a separate program on the server's private network, e.g. `http://pro:8000`). Empty means paid features are off and answer "not available yet". At startup the server pings it once and logs one line, `holt-pro: ok at ...` or `holt-pro: not working at ...`; `python -m holt_server.pro` does the same on demand. |
| `HOLT_PRO_KEY` | *(empty)* | Shared key for that service, sent as `X-Holt-Pro-Key` on every call. Never logged. |
| `HOLT_PLAYBOOK_CACHE_HOURS` | `168` | How long a written playbook ("How to get merged here") is served before the next unlock asks the service for a new one. Playbook jobs are stopped after `HOLT_JOB_TIMEOUT_AI`. |
| `OPENROUTER_API_KEY` | *(empty)* | The server's model key; every AI report runs on it. Empty means AI reports are off: requests get `ai_unavailable` and spend nothing. |
| `OPENROUTER_MODEL` | `openai/gpt-5-mini` | Model id on OpenRouter for server-paid AI reports. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. Point it at `https://api.openai.com/v1` (with `OPENROUTER_MODEL=gpt-5-mini` and an OpenAI key) to use OpenAI directly. |
| `HOLT_MODEL_PROVIDER` | *(read from the endpoint)* | `openrouter`, `openai` or `gemini`: which parameter names the endpoint takes (`max_tokens` and `reasoning` for OpenRouter; `max_completion_tokens` and `reasoning_effort` for OpenAI). Set it only for a proxy whose URL doesn't say. |
| `HOLT_AI_BUDGET_USD` | `0` (AI off) | The most this environment may ever spend on AI models, in USD: AI reports and the paid-features service's playbooks and summaries together. See [AI budget](#ai-budget). `0` turns every AI feature off (they answer `ai_unavailable` and charge nothing). |
| `HOLT_AI_BUDGET_OWNER_OK` | `0` | With `HOLT_ENV=production`, a budget counts only when this is `1` too: the owner's explicit say-so. Without it AI stays off and startup logs an error. |
| `HOLT_AI_RUN_MAX_USD` | `0.10` | The most one AI report may cost. Held from the budget while it runs; its model calls are refused once the next could pass it. |
| `HOLT_AI_PRO_RUN_MAX_USD` | `0.05` | The same for a playbook, pre-flight summary or merge plan from the paid-features service. A merge plan holds this plus `HOLT_AI_RUN_MAX_USD`, since it may run an AI report's stages first. |
| `HOLT_MODEL_REASONING_EFFORT` | *(empty)* | `minimal`, `low`, `medium` or `high` for reasoning models (gpt-5, o-series). Empty sends nothing and the provider's default applies. |
| `HOLT_JOB_CONCURRENCY` | `2` | User lane: people's analyses and finds running at once in this process. Each holds a thread and some memory. |
| `HOLT_JOB_TIMEOUT_RULES` | `180` | Seconds a rules report may run before it is stopped and fails with a plain "took too long" error. |
| `HOLT_JOB_TIMEOUT_AI` | `480` | The same, for AI reports and PR pre-flight checks (refunded when stopped). A merge plan gets this for its AI stages plus 330 s for the service. |
| `HOLT_JOB_TIMEOUT_FIND` | `300` | The same, for `/v1/find`. |
| `HOLT_CACHE_HOURS` | `24` | How long a finished report is served instead of re-running. |
| `HOLT_SIGNUP_AI_CREDITS` | `0` | Free AI reports every signed-in user gets once, on their first visit. 0 since the 3 free merge plans replaced them: new accounts get none and no weekly claim; accounts welcomed before keep theirs. |
| `HOLT_CLAIM_EVERY_DAYS` | `7` | After that, one more can be claimed each time this many days have passed since the last claim (or the welcome grant). |
| `HOLT_PRICING_FILE` | the catalogue shipped in the package (`holt_server/pricing.json`) | Features, plans and Pro passes, with prices in INR and USD. See [Credits, plans and passes](#credits-plans-and-passes). A file that doesn't parse stops startup. |
| `HOLT_PAYMENTS_ENABLED` | `0` | `1` switches the pass checkout on (it also needs the Razorpay keys and a pass on sale). See [Pass checkout](#pass-checkout). |
| `HOLT_PASSES_ON_SALE` | `0` | `1` puts every pass in the catalogue on sale, whatever its `on_sale` says. For staging with Razorpay test keys; **ignored when `HOLT_ENV=production`** (the server logs an error), where only the pricing file puts a pass on sale. |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | *(empty)* | Razorpay API keys (`rzp_test_…` for test mode). Empty: no checkout. |
| `RAZORPAY_WEBHOOK_SECRET` | *(empty)* | The secret set on the webhook in the Razorpay dashboard. Empty: webhooks are refused. |
| `HOLT_ADMIN_USERS` | *(empty)* | Comma-separated user ids that may read `/v1/admin/*`. Empty means nobody. |
| `HOLT_ANON_RATE_PER_HOUR` | `10` | Work bucket: new analyses and find per hour per IP for anonymous callers (`X-Holt-Client-Ip`). Cached answers are free. |
| `HOLT_USER_RATE_PER_HOUR` | `60` | The same, per signed-in user. |
| `HOLT_ANON_READ_RATE_PER_HOUR` | `120` | Read bucket, per IP: starter-issue lookups that miss the cache. Separate from the work bucket above, so page views never block analyses. |
| `HOLT_USER_READ_RATE_PER_HOUR` | `600` | The same, per signed-in user. |
| `HOLT_STARTER_CACHE_HOURS` | `1` | How long starter issues per repository are served from the cache. |
| `HOLT_BADGE_RATE_PER_IP` | `20` | Rules checks a single client can trigger per hour by loading badges (client = `CF-Connecting-IP`, else the socket address). |
| `HOLT_BADGE_RATE_TOTAL` | `60` | The same, across all clients. |
| `HOLT_BADGE_CONCURRENCY` | `1` (production: `3`) | Background lane: workers of their own, on top of `HOLT_JOB_CONCURRENCY`, for badge refreshes and warm-pass jobs. They take a waiting person's job before any badge work. `0` turns badge and warm work off. |
| `HOLT_FIND_CACHE_HOURS` | `6` | How long a finished `/v1/find` search is served to anyone asking the same thing. |
| `HOLT_WARM_INTERVAL_HOURS` | `0` (off) | Run a warm pass in the API process every N hours (one process at a time; Postgres advisory lock). Each pass also refreshes Discover's repository details (`repo_meta`) once a day, about one GraphQL point per hundred repos. |
| `HOLT_CONTRIBUTIONS_REFRESH_HOURS` | `24` | Re-read connected users' public pull requests (My Contributions) every N hours in the API process; stops when GitHub points drop below `HOLT_WARM_MIN_POINTS`. `0` = off. |
| `HOLT_PR_WATCH` | `0` (off) | The switch for PR watch. `1` starts the checker and the mailer in the API process and lets people turn alerts on. Off, nothing checks pull requests, makes alerts or sends email. See [PR watch](#pr-watch). |
| `HOLT_PR_WATCH_MINUTES` | `30` | Minutes between checks of watched pull requests. |
| `RESEND_API_KEY` | *(empty)* | Resend's API key, for alert emails and account emails. Empty: no email is sent (logged once); alerts still reach the bell. Never logged. Emails also need `HOLT_SECRET_KEY`, which makes the unsubscribe links. |
| `HOLT_ALERT_EMAIL_FROM`, `HOLT_ALERT_EMAIL_REPLY_TO` | `Holt <alerts@githolt.com>`, `hello@githolt.com` | The sender and the reply address of alert emails. The sender's domain must be verified with Resend. |
| `HOLT_ALERT_EMAIL_DAILY_LIMIT` | `100` | The provider's daily sending limit (Resend's free tier), for alert and account emails together. They stop 5 short of it in any 24 hours: "your turn" emails go first, daily emails that don't fit go out once there is room. Only a pass's receipt may use the last 5. |
| `HOLT_ACCOUNT_EMAILS` | `0` (off) | The switch for account emails: the welcome, a pass's receipt, and the "ending" ones. Off, none is sent. They also need `RESEND_API_KEY`. See [Account emails](#account-emails). |
| `HOLT_WARM_SEEDS` | the list shipped in the package (`holt_server/seeds/repos.txt`) | The warm pass's seed list. |
| `HOLT_WARM_MAX_AGE_HOURS` | `20` | A warm pass skips repos whose report is younger than this. |
| `HOLT_WARM_MIN_POINTS` | `1500` | A warm pass stops when any GitHub token has fewer GraphQL points left, counting 20 for each report still in flight. |
| `HOLT_WARM_PARALLEL` | `3` | Report jobs a warm pass keeps in flight at once (`--parallel N` for one pass). They run in the background lane, so keep `HOLT_BADGE_CONCURRENCY` at least this. |
| `HOLT_REFRESH_WEEKLY_HOURS`, `HOLT_REFRESH_MONTHLY_HOURS` | `168`, `720` | The refresh tiers' ages, as `deploy/prod/warm-refresh.sh` uses them. `warm --stale-only` reuses a snapshot up to its repo's tier age. |
| `HOLT_MAX_PAGES` | `8` | Pull-request pages crawled per analysis (25 PRs a page). |
| `HOLT_EVIDENCE_DIR` | empty (off) | Keep every report's evidence here, one gzipped file per report (`<owner>__<name>/<UTC time>.json.gz`, the shape of a golden recording). See [Evidence snapshots](#evidence-snapshots). |
| `HOLT_EVIDENCE_KEEP_DAYS` | `0` (keep all) | Delete a repo's snapshots older than N days when it gets a new one; its newest always stays. |
| `HOLT_EVIDENCE_REUSE_HOURS` | `168` | `warm --stale-only` makes an outdated report again from a snapshot younger than its repo's refresh tier (a week or a month), or than this if longer, without GitHub. `0` = always read GitHub. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Where `holt-server` listens. |
| `LOG_LEVEL` | `INFO` | |

## How it fits together

| File | What |
|---|---|
| `holt_server/api.py` | The endpoints. Cache lookups, rate limits and the AI credit spend happen here, before a job is queued. |
| `holt_server/credits.py` | Credit balances in two pools: free (the welcome grant, the weekly claim, gifts) and purchased (lots from admin grants, and credit packs bought before passes). Taking and giving back credits, pack purchases, the `/v1/me/credits` routes and the admin CLI. |
| `holt_server/entitlements.py` | Can user U use feature F now, and what does it cost: `check` (read-only) and `charge`/`refund` (inside the caller's transaction). Plans, their expiry and monthly allowances. |
| `holt_server/pricing.py` | Loads and checks the catalogue (`pricing.json`). |
| `holt_server/admin.py` | The read-only `/v1/admin/*` view (balances, ledger, plans). |
| `holt_server/jobs.py` | The runner: claims queued jobs from Postgres (user jobs before badge refreshes), runs them in threads, publishes progress for SSE. Each runner heartbeats the jobs it holds every 15s; a `running` job with no heartbeat for 90s belonged to a dead process and is queued again. Several processes can share one database. |
| `holt_server/engine.py` | Calls `holt.agent.pipeline.analyze` / `analyze_without_model`. Wraps the provider and model to report stages; uses the engine's own progress callback when it has one. Maps failures to API error codes. Logs one line per AI report (`holt_server.engine`: repo, model, tokens, dollars, seconds per stage; never evidence text or keys). |
| `holt_server/report.py` | `Assessment` + `Trace` → the Report JSON. Landing areas and evidence URLs come from the records the run read. |
| `holt_server/llm.py` | Model clients (OpenRouter over the OpenAI API; an Anthropic-native client too) built per job from the server key. Every call carries the engine's per-stage output cap (`holt.model.max_output_tokens`); an answer cut off at the cap fails the job as an `upstream` error, never half a report. Nothing is written to disk. |
| `holt_server/budget.py` | The environment's hard cap on AI spend (`HOLT_AI_BUDGET_USD`): holds per run, the per-call check on an AI report's model, settling on the real cost, `/v1/admin/ai-spend` and `python -m holt_server.budget`. |
| `holt_server/starter.py` | Lazy adapter over `holt.starter`; the endpoints return 501 until that module exists. |
| `holt_server/pro.py` | Client for the optional paid-features service (`HOLT_PRO_URL`): the key header, 2 s connect / 10 s read timeouts, one retry on a failed connection or a 503, and its error envelope turned into this API's errors with plain messages. `Services.pro` is None when it is off, and `Services.require_pro()` then answers 501 "not available yet". |
| `holt_server/playbook.py` | The paid playbook: the teaser and unlock routes, charging (`entitlements.charge`) with a per-user unlock, the `playbook` job that calls the service, the per-repo cache, and refunds for everyone waiting on a job that fails. |
| `holt_server/preflight.py` | PR pre-flight: the state and start routes, charging (`entitlements.charge`, feature `preflight`) in the transaction that queues the `preflight` job, the job that calls the service, and results kept per user, target and head commit (a re-check of the same commit is refunded). A failed job is refunded by `refund_job`. |
| `holt_server/badge.py` | The README badge SVG. |
| `holt_server/cache.py` | Answers that are the same for every reader, kept in the process as they are sent: Discover's boards, the free report, Find's index part. Bounded (entries and bytes), 60 seconds at most, and dropped as soon as this process commits a write to a table they were built from (it counts every ORM session's writes, so code that writes doesn't have to say so). A read that hits costs no database session. Never anything per person. |
| `holt_server/discover.py` | `GET /v1/discover` and the "most welcoming <language> repos" boards, from the latest rules report per repo (never the model), plus `repo_meta`: language, stars, topics and description, which the warm pass reads a hundred repos per GraphQL query. The process keeps what it read from each report (reports never change) and each repo's details, so a request reads only what is new. |
| `holt_server/meta_refresh.py` | Reads a repo's `repo_meta` right after its report is stored (missing or a day old), best effort and batched, so a repo checked for the first time isn't bare on Discover. |

Identical requests share one job. That is enforced by a partial unique index
on `jobs.dedupe_key` (only over queued/running jobs), so two requests racing
each other still get one job and spend one credit.

AI reports run on the server's OpenRouter key and cost the user one credit.
Signed-in users get `HOLT_SIGNUP_AI_CREDITS` free credits once, on their first
visit, and can claim one more every `HOLT_CLAIM_EVERY_DAYS`; claims don't pile
up. The website doesn't take users' own API keys (the CLI does).

## AI budget

`holt_server/budget.py`. `HOLT_AI_BUDGET_USD` is a hard cap on everything
this environment spends on models, over its whole life: AI reports on the
server's key, and the playbooks and pre-flight summaries the paid-features
service writes. The service is only ever called by this server's jobs, so
its spend is counted here too; it has no budget of its own. `0`, the
default, turns AI off; production also needs `HOLT_AI_BUDGET_OWNER_OK=1`
(and `deploy/prod` passes neither unless the owner sets the `HOLT_PROD_*`
names).

- **Queueing** an AI job holds its most possible cost (`HOLT_AI_RUN_MAX_USD`,
  or `HOLT_AI_PRO_RUN_MAX_USD` for the service, or both for a merge plan) from the budget, in the
  transaction that charges the user's credit, with a guarded `UPDATE` on the
  single `ai_budget` row. A job that doesn't fit is refused with
  `ai_unavailable` ("The AI budget for this environment is used up ... Nothing
  was charged"), rolled back, and logged. Racing requests can't pass the
  budget: the holds already cover every run in flight.
- **Running** it claims that hold. A job run again (its process died and it
  was queued again) takes a new one, or fails and is refunded.
- An AI report's model client is wrapped (`budget.Capped`): a call is refused
  when what the run has spent, plus the worst case of calls still out, plus
  this call's worst case (its output cap from `holt.model.max_output_tokens`
  and a generous guess at its prompt's tokens) would pass the run's hold. A
  model with no known price (`holt.model.PRICES`) can't be capped, so AI stays
  off with it.
- **Ending** it records the real cost in `ai_runs` (the report's `cost.usd`;
  the service's `usage` when it sends one, else nothing for a cached answer)
  and gives back the rest of the hold. When the cost isn't known (a timeout:
  the run may still be going; a service answer that doesn't say) the whole
  hold is kept, marked `estimated`.

The spend so far, against the budget:

```sh
python -m holt_server.budget          # AI spend: $0.23 of $1.00
curl -s localhost:20130/v1/admin/ai-spend -H "$K" -H "X-Holt-User: <admin id>"
```

Staging runs with $1.00 for the server and the service together
(`deploy/staging/preview.sh`); production with 0.

## Credits, plans and passes

Payments are off in production; nothing is on sale there. This is the model the payment code
([Pass checkout](#pass-checkout)) plugs into.

**Catalogue.** `holt_server/pricing.json` (or `HOLT_PRICING_FILE`) lists the
paid features and what one use costs in credits (`free_credits`: whether free
credits may pay for it), the plans (`free`, `pro`: which features each
covers, unlimited or `per_month` uses per UTC month) and the passes that sell
Pro (`days` of Pro for one payment, `on_sale`, prices as `inr_paise` /
`usd_cents`). A pass never renews. `python -m holt_server.pricing` checks a
file.

**Balances.** Free credits are `users.ai_credits`. Purchased credits are
`credit_lots` rows, one per admin grant (or credit pack bought before
passes), each with an optional expiry; what is left in an expired lot is
written off the next time the user is seen. Every change writes a
`credit_events` row with its pool (`source`: free or purchased) and kind
(grant, claim, purchase, adjust, spend, refund, expire). Per user, the free
rows sum to `ai_credits` and the purchased rows to what the lots have left.

**Entitlements.** `entitlements.charge(session, svc, user, feature)` pays for
one use inside the caller's transaction: the plan (lapsed to free at
`plan_expires_at`) if it covers the feature and has uses left this month,
else the feature's credits, free first (when allowed), then the
soonest-expiring lot. Every step is a guarded `UPDATE`, so racing requests
can't overdraw or exceed an allowance; if it can't be paid for, it rolls back
and raises `quota_exceeded` or `needs_plan`. A job keeps what it was charged
in `params["charge"]`, and a failed job gives it back to the same pool in the
transaction that marks it failed. `entitlements.check` answers the same
question without charging (`GET /v1/me/entitlements`, the admin view).
Plans change only through `entitlements.set_plan` (or `write_plan`, its
in-transaction form), which writes `plan_events`.

**Admin.** Changes go through the CLI, which runs against `$DATABASE_URL` and
prints the user's state afterwards (in production, run it inside the API
container):

```sh
python -m holt_server.credits show  --user <id>
python -m holt_server.credits grant --user <id> --credits 5 --reason "tester" [--pool purchased] [--expires-days 90]
python -m holt_server.credits take  --user <id> --credits 2 --reason "mistake" [--pool purchased]
python -m holt_server.credits plan set --user <id> --plan pro --days 30 --reason "early tester"
python -m holt_server.credits plan set --user <id> --plan free --reason "ended"
```

`--pool free` (the default) gifts free credits; `--pool purchased` adds a lot
that pays for purchased-only features too. `take` never goes below zero.
Reading is `/v1/admin/*` (API.md), for users in `HOLT_ADMIN_USERS`.

## Pass checkout

`holt_server/payments.py`: Razorpay, INR, one-time payments for the passes in
the catalogue. **Off by default**: it needs `HOLT_PAYMENTS_ENABLED=1`, the
Razorpay keys, and a pass with `on_sale: true` and an `inr_paise` price.
Outside production, `HOLT_PASSES_ON_SALE=1` stands in for `on_sale: true` on
every pass (staging runs that way, on Razorpay test keys;
`deploy/README.md`). The server logs one `passes:` line at startup saying
what is on sale. The flow and the endpoints are in API.md ("Passes"); the
short version:

- An order (`orders` table) copies the pass and price from the catalogue when
  it is created (the pass id in `pack_id`, its days in `expires_days`,
  `credits` 0); the browser only names the pass.
- Pro is given only for a payment Razorpay vouches for: the Checkout
  callback's signature (then the payment is fetched from Razorpay), or a
  webhook's signature. The payment must be captured and match the order's
  amount and currency; a mismatch puts the order on `held`, gives nothing
  and logs an error.
- `orders.status` goes `created` → `paid` once, in the same transaction that
  sets the plan to `pro` (`write_plan`, `actor=payment`, `reference=<payment
  id>`) for the pass's days, counted from the end of the user's current Pro
  if it hasn't lapsed. So the callback, the webhooks and their retries give a
  pass exactly once, and passes stack. Pro an admin gave with no end is left
  alone.
- Orders for credit packs from before passes still settle as credits.

Webhook: in the Razorpay dashboard, point a webhook at
`https://<site>/api/payments/razorpay/webhook` (served by `web/`, which
forwards it here) for `payment.authorized`, `payment.captured`,
`payment.failed` and `order.paid`, and put its secret in
`RAZORPAY_WEBHOOK_SECRET`.

Trying it locally in test mode: use `rzp_test_` keys, `HOLT_ENV=dev`,
`HOLT_PASSES_ON_SALE=1` and `HOLT_PAYMENTS_ENABLED=1`. Razorpay can't reach
a local webhook (or staging's, behind Cloudflare Access), so the callback
does the giving.

Monthly subscriptions were replaced by passes. Their tables
(`subscriptions`, `subscription_charges`) are still in the schema, unused,
until a migration drops them.

Per process (fine for one server; revisit with more): rate-limit counters,
the badge lane's concurrency count and the repo-name cache are in memory. SSE
fan-out is in memory but falls back to re-reading the jobs table every 15s.

## PR watch

Alerts about a connected user's open pull requests, on the bell and by email
(`API.md`, "PR watch"). Four modules:

- `alerts.py`: the rules, pure. `events(old, new)` is what changed between two
  reads of a pull request; `overdue(pr, timing, now)` is what its wait says
  against the repository's report. Also the line each alert reads as, and who
  has access (a plan that covers `pr_watch`, or 14 free days from the first
  time alerts are turned on, kept on `users.alerts_trial_ends_at`).
- `watch.py`: the checker. Every `HOLT_PR_WATCH_MINUTES` it re-reads the open
  pull requests of everyone with alerts on and access, by node ID, as the
  GitHub App (about 5 points per 100), and stops reading GitHub under
  `HOLT_WARM_MIN_POINTS`. A contributions fetch makes the same alerts for what
  it sees change. Advisory lock 7406113.
- `mailer.py`: every 5 minutes, under its own advisory lock (7406114), it
  decides what to email (`plan`, pure) and sends through Resend. It reads no
  GitHub.
- `alert_email.py`: the two emails, HTML and text, built from `email_kit.py`,
  the template every Holt email shares.

**Turning it on.** It is off until the owner sets `HOLT_PR_WATCH=1` and
restarts the server. For email, also set `RESEND_API_KEY`, and verify the
sending domain with Resend first; without the key everything else works and no
email goes out. `HOLT_PR_WATCH=0` again stops both loops; stored alerts stay.

## Account emails

Five emails about the account itself (`API.md`, "Account emails"), and no
more: a welcome at an account's first sign-in, a receipt for each paid pass,
one two days before the free days of PR alerts end and one when they have,
and one three days before a paid pass ends.

- `account_mail.py`: who gets which. Every 15 minutes in the API process, and
  at once after a first sign-in or a paid order, it sends what is due. Each
  send first claims a row in `account_emails`, unique per user and email, so
  each goes out once however many runs and processes find it due; a claim the
  provider couldn't take is given back and tried again.
- `account_email.py`: the emails, HTML and text, built from `email_kit.py`.

The address is the one the user signed in with: `web/` reports it at every
sign-in (`POST /v1/me/sign-in`) and it is kept in `account_mail`. Until a
user's next sign-in reports it, their alert settings' address stands in;
with neither, nothing is sent to them. The receipt always goes out. The rest
respect one switch, `account_mail.product_on`, which the email's "Stop these
emails" link and one-click header turn off (the web page and route alert
emails use take both kinds of link).

**Turning it on.** `HOLT_ACCOUNT_EMAILS=1` and `RESEND_API_KEY`, then restart.
A welcome or a receipt is only sent within a day of the sign-in or payment, so
switching it on writes to nobody from before. Off, sign-ins still keep the
address in step, so the emails have somewhere to go once they are on.

**Reading them.** `/lab/emails` on staging (or a dev server) shows every Holt
email on made-up data. To get a real copy of each in your own inbox, outside
production:

```sh
python -m holt_server.account_mail samples <your user id>
```

It sends them to that user's sign-in address and to no other.

```sh
python -m holt_server.watch     # one check now
python -m holt_server.mailer    # one mailer run now
```

Watched repositories join the weekly refresh tier of the warm pass, so each
gets a report (the waits need its timing).

## Changing the schema

The tables are defined in `holt_server/db.py` and created and changed by
Alembic migrations in `holt_server/migrations/versions/` (inside the package,
so they ship in the server image). `python -m holt_server.migrate` brings
`$DATABASE_URL` to the latest revision; deploys run it as a one-shot service
before the new containers start, and the server runs it again on startup (a
no-op by then). `0001_baseline` is the schema production had when migrations
started; a database made before that (by `create_all`) is stamped at it, not
re-created.

To add a migration, from `server/`, with the dev Postgres running:

```sh
uv run python -m holt_server.migrate                        # dev database to the latest revision
# edit the models in holt_server/db.py, then:
uv run alembic revision --autogenerate -m "add feedback table"
# read and fix the new file in holt_server/migrations/versions/; name the
# revision id 0002, 0003, ... (--rev-id 0002) so the order is obvious
uv run python -m holt_server.migrate                        # apply it
uv run python -m holt_server.migrate check                  # exit 0: models and database agree
```

Rules:

- **The previous release must keep working on the new schema.** Deploys
  migrate first and then swap containers, and a rollback does not undo a
  migration. Add columns as nullable or with a server default; drop or rename
  in a later release, after nothing reads the old name.
- Migrations must run on SQLite too (the tests use it). Autogenerate writes
  column changes as `op.batch_alter_table`, which is a plain `ALTER` on
  Postgres and a table copy on SQLite; keep it that way in hand-written ones.
- Never edit a migration that has been deployed; add a new one.
- `tests/test_server_migrations.py` fails when the models and the migrations
  disagree, on SQLite locally and on Postgres in CI. To run the server tests
  on Postgres yourself: `HOLT_TEST_DATABASE_URL=postgresql+asyncpg://holt:holt@127.0.0.1:20131/holt uv run pytest server/tests`
  (its tables are dropped).

## Warm cache

`holt_server/warm.py` fills the caches before people arrive, so launch-day
traffic mostly costs no GitHub quota at request time:

1. **Reports** (7-day rules) for the ~10,000 repositories in `server/holt_server/seeds/repos.txt`,
   skipping any under 20 hours old.
2. **Starter issues** for the same repositories.
3. **`/v1/find`** for the searches the web app's own pages make: the nine
   `/hacktoberfest` tabs, and each `/find` language chip with and without
   Hacktoberfest (23 searches, 7-day budget). Reports go first because a find
   screens repositories through the report cache.

Everything goes through the normal job queue at badge priority, so user
requests always run first. The pass keeps `HOLT_WARM_PARALLEL` (3) report jobs
in flight, queueing the next seed's as one finishes; starter issues ride along
with each seed's report (one GraphQL query each), and repository details and
finds stay one step at a time. Before every report job the pass checks the
GitHub points left, less 20 for each report still in flight, and stops under
`HOLT_WARM_MIN_POINTS` (the reports in flight finish first);
`--wait-for-budget` waits for the points to come back instead, for a long
sweep left on its own.

Seeds that can't take outside work right now go last: their last report was
decided by the repository being archived, closed to outside pull requests in
GitHub's settings, or inactive, or `repo_meta` says archived or no push in 90
days. A pass that runs out of budget has done the useful ones first. This
reads only what Holt already has, never GitHub; the summary counts them.

A seed whose report fails is remembered (`warm_failures`) and not asked for
again for six hours, doubling with each failure in a row up to a week; when
its wait is over it goes to the back of the queue, and a report made any
other way forgets it. A repository GitHub says isn't there waits a month and
is listed under the summary until the seed list is fixed. So a pass spends
its time on seeds that can succeed. Five reports in a row failing on GitHub's
side (502, 504, a timeout) pause the pass for five minutes.

What GitHub's refusals mean (`holt_server/github.py`, `TokenPool`):

| GitHub answers | It is | What happens |
|---|---|---|
| 502 / 504 | that repository's failure (`upstream`): usually a query GitHub times out on | asked twice for background work, four times for a person's check; the token stays in |
| 403 with `x-ratelimit-remaining: 0` | the hourly points used up (`rate_limited`) | the token is left out until its reset |
| 403 or 429 with `Retry-After`, or a "secondary rate limit" message | "slow down": too much at once, with points to spare (`rate_limited`) | nothing is sent with that token until GitHub's wait is over, not even by reports in flight |
| any other 403 | that request's failure (`upstream`) | the token stays in, unless it gets three in a row and nothing else |
| `NOT_FOUND` | no such repository (`not_found`) | the token stays in |

A `rate_limited` report is never the repository's failure. With
`--wait-for-budget` the pass waits as long as GitHub asked (longer each time
it says so again), runs one report at a time for half an hour, and asks for
the same seed again; it ends only after six such waits with no report made,
and says so. Without the flag it ends at the first one and says when to run
again. The log line `GitHub answered 403: retry-after=… x-ratelimit-remaining=…`
records which kind it was.

The pass prints a `progress:` line every 25 seeds and, in its summary, how
many seeds were skipped as recently failed and how many are still without a
current report; `deploy/prod/warm.sh --status` shows the last of each.

```sh
uv run python -m holt_server.warm --dry-run           # what would run, and its GitHub points
uv run python -m holt_server.warm                     # the whole thing
uv run python -m holt_server.warm --limit 50 --no-find
```

A report takes about 45 seconds, mostly waiting on GitHub, and about 12
points on average, so three in flight do a cold sweep of the ~10,000 seeds
(about 120,000 points) in roughly 42 hours at about 2,900 points an hour (under
GitHub's 5,000). With starter issues too, add about 5 points a seed (about
170,000 points in all), about 4,100 points an hour: the
pass meets `HOLT_WARM_MIN_POINTS` within the hour, so run a long sweep with
`--no-starter` or `--wait-for-budget`.

Or set `HOLT_WARM_INTERVAL_HOURS` to run it inside the API on a schedule.

**Refresh tiers** (`--tier`): reports only, oldest first, skipping any younger
than `HOLT_WARM_MAX_AGE_HOURS`. `weekly` is every repo someone saved
(`saved_repos`) or viewed in the last 30 days (`repo_views`), seed or not;
`monthly` is the rest of the seed list. Production's refresh timer
(`deploy/prod/warm-refresh.sh`, off until the owner switches it on) runs both
daily with a week's and a month's age.

```sh
HOLT_WARM_MAX_AGE_HOURS=168 uv run python -m holt_server.warm --tier weekly --dry-run
HOLT_WARM_MAX_AGE_HOURS=720 uv run python -m holt_server.warm --tier monthly
```

## Evidence snapshots

With `HOLT_EVIDENCE_DIR` set, every finished report also writes the evidence
it read (`holt_server/evidence_store.py`): the pull requests with their
comments, reviews, merges and closes, the repository facts, README and
CONTRIBUTING, as `golden record` saves them, run through the same credential
redaction (`holt/evidence/redact.py`). Public GitHub data only; Holt's tokens
are never part of it. The file is written after the report is stored, and a
failed write is logged (`saving the evidence of … failed`) and never fails the
report. Not in Postgres: production keeps them in
`~/.local/share/holt-prod/evidence` on `/home` (`deploy/prod/README.md`).

Size, measured on the 73 golden recordings: 123 KB a snapshot on average
(median 70 KB, largest 821 KB), so **about 126 MB per 1,000 repos** each time
they are all read.

`python -m holt_server.warm --stale-only` (after an `ENGINE_VERSION` bump)
uses them: a repo whose newest snapshot is younger than its refresh tier (a
week for repos someone saved or viewed lately, a month for the other seeds; at
least `HOLT_EVIDENCE_REUSE_HOURS`), and not older than the report it replaces,
gets its report made again from the snapshot in the warm process, with no
GitHub call. The tier's age is how stale its report may get anyway. The new
report is dated like the evidence behind it, so the refresh tiers still see
its real age. Otherwise the repo is read from GitHub as before.

**GitHub cost, measured** (GraphQL points; a token has 5,000 an hour): a rules
report ~10 (up to ~20 for very busy repositories), starter issues ~5, a find
search ~60 when its repositories are not cached yet and much less when they
are. A cold full pass is therefore roughly 10,000 × ~17 + 23 × ~20–60 ≈
**170,000 points**: about 34 token-hours, so it takes two days on one token, or
proportionally less with more tokens in `GITHUB_TOKENS`, over as many runs as
it needs (each resumes where the last stopped, since finished reports are
skipped). Warming everything again each day would cost the same, because
reports expire after 20 hours; production refreshes by tier instead (above).

The seed list is built by `server/scripts/build_seeds.py` (the same sourcing as
`/v1/find`: the hacktoberfest topic, then beginner-friendly repositories in 12
languages; ~30 points). Re-run it to refresh the list and commit the result:

```sh
GITHUB_TOKEN=... uv run python server/scripts/build_seeds.py --total 300
```

Below its marker line, the list continues with blocks built by
`scripts/build_seed_list.py`: GSoC organisations 2023-2026 (CNCF through its
landscape), LFX Mentorship, Outreachy, goodfirstissue.dev,
awesome-for-beginners and up-for-grabs, all free public lists. With `--check`
it also searches GitHub (repositories with open good-first-issue and
help-wanted issues in 13 languages; the topics maintainers use to invite
newcomers, such as `good-first-issue` and `help-wanted`; repositories in any
language with at least three open good-first-issue issues; then the
hacktoberfest topic from the most-starred down until the list reaches
`--target`, 10,000 by default) and drops repos that are gone, archived, forks
or mirrors, under 20 stars, not pushed since June 2026 or closed to outside
pull requests (~160 points in all). It drops catalogues, farms, practice
repos and personal dotfiles by name and by description. A repo already in
the list stays, so its report keeps being refreshed, unless it is gone,
archived, a fork or mirror, or closed to outside pull requests; one that a
filter would now drop is printed for a person to decide. Each script keeps
the other's part:

```sh
GITHUB_TOKEN=$(gh auth token) uv run python scripts/build_seed_list.py --check
```

With ~10,000 seeds a cold pass is about 10,000 × ~12 ≈ 120,000 points, a
full day of one token's 5,000 an hour, so warm a new list with
`--wait-for-budget` or in `--limit` steps rather than in one burst.

## Metrics

`GET /metrics` serves this process's numbers in Prometheus's text format
(`holt_server/metrics.py`), for the optional monitoring stack in
`deploy/monitoring/`. It needs no key and is not part of the web app's API
(`API.md`): the server publishes no port, the web app proxies no such path,
so only the stack's own Docker network reaches it. Nothing in it names a
user, a repository or a token.

```sh
curl -s localhost:20130/metrics | grep '^holt_'
```

| Metric | What it says |
|---|---|
| `holt_http_requests_total{method,route,status}`, `holt_http_request_duration_seconds` | Requests and the time to the first byte, by route template (`/v1/reports/{owner}/{repo}`), never by URL. `/health` and `/metrics` aren't counted. |
| `holt_http_requests_in_flight` | Requests being answered now, open event streams included. |
| `holt_jobs{status,lane}`, `holt_jobs_oldest_queued_seconds{lane}` | The queue, read from the `jobs` table: jobs queued and running in every process, and how long the longest-waiting one has waited. `lane` is `user` (a person's job) or `background` (badges, warm passes). |
| `holt_job_wait_seconds{lane}`, `holt_job_duration_seconds{kind}`, `holt_jobs_finished_total{kind,lane,outcome}` | Each job this process ran: its wait, its run time, and how it ended (`done`, `error`, `timeout`). |
| `holt_job_workers{lane}`, `holt_job_workers_busy{lane}` | Workers per lane (`HOLT_JOB_CONCURRENCY`, `HOLT_BADGE_CONCURRENCY`) and how many are running a job. |
| `holt_db_pool_size`, `holt_db_pool_in_use`, `holt_db_pool_waiting`, `holt_db_pool_wait_seconds`, `holt_db_pool_timeouts_total` | The database pool: connections out, requests waiting for one, how long they waited, and waits that gave up at `HOLT_DB_POOL_TIMEOUT`. |
| `holt_github_points_left{token}`, `holt_github_points_reset_timestamp_seconds{token}`, `holt_github_token_usable{token}`, `holt_github_points_used_total` | GraphQL points as GitHub last reported them (no call is made to ask), when they come back, and points seen spent. Tokens are numbered, never shown. |
| `holt_ai_budget_usd`, `holt_ai_committed_usd`, `holt_ai_spent_usd{kind}` | AI spend against `HOLT_AI_BUDGET_USD`, by kind of run (`merge_plan`, `analysis`, ...). |
| `holt_emails_last_day{stream,status}`, `holt_email_daily_limit` | Alert and account emails handed to the provider in the last 24 hours, sent and failed. |
| `holt_repos_reported{engine}`, `holt_warm_pass_running` | Repos whose newest quick report is from this engine or an older one, and whether a warm pass holds its lock (Postgres only). |
| `holt_metrics_db_ok`, `holt_build_info{version,engine_version}`, `process_*` | Whether this scrape could read the database; the versions; the process's memory and CPU. |

The numbers read from the database come over a connection of their own
(`Database.stats`), like the health check's, so they still answer while every
pool connection is busy. It is opened by the first scrape and counted in the
budget in `deploy/prod/compose.yml`.

## Tests

```sh
uv run pytest server/tests -q
```

SQLite instead of Postgres, the GitHub lookup faked, no network. Most tests
fake the engine; `test_server_engine.py` runs the real one over the committed
`NixOS/nixpkgs` replay fixtures, in both rules and AI mode.

`scripts/pool_load.py` is the load check for the connection pool: a
prod-sized database, jobs on a slow fake GitHub and a crowd of page requests,
in one process with no network. It prints failed requests, how long
connections were held and whether `/health` kept answering, and exits 1 if
either went wrong. Run it against the dev Postgres after changing how a
request or a job uses the database:

```sh
uv run python server/scripts/pool_load.py --seed \
    --database-url postgresql+asyncpg://holt:holt@127.0.0.1:20131/holt
```
