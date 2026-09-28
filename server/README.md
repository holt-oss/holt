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
| `HOLT_INTERNAL_KEY` | *(empty)* | Shared secret with `web/`. Every `/v1` request must send it as `X-Holt-Internal-Key`. Empty means every `/v1` request is refused. |
| `HOLT_SECRET_KEY` | *(empty)* | Server secret for keyed hashes (usage counting). Use 32 random bytes, base64: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`. |
| `HOLT_WEB_URL` | `https://githolt.com` | The badge links to `{HOLT_WEB_URL}/{owner}/{repo}`. |
| `GITHUB_TOKENS` | *(empty)* | Comma-separated GitHub tokens, used round-robin, one per analysis. A token GitHub refuses is left out for 10 minutes, and one that is rate-limited or nearly used up (points left, read from every reply) until it resets; logs name tokens by position (`token #2`), never by value. Read-only public access is enough (a fine-grained token with no extra permissions). |
| `HOLT_PRO_URL` | *(empty)* | Base URL of the optional internal service that runs paid features (a separate program on the server's private network, e.g. `http://pro:8000`). Empty means paid features are off and answer "not available yet". At startup the server pings it once and logs one line, `holt-pro: ok at ...` or `holt-pro: not working at ...`; `python -m holt_server.pro` does the same on demand. |
| `HOLT_PRO_KEY` | *(empty)* | Shared key for that service, sent as `X-Holt-Pro-Key` on every call. Never logged. |
| `HOLT_PLAYBOOK_CACHE_HOURS` | `168` | How long a written playbook ("How to get merged here") is served before the next unlock asks the service for a new one. Playbook jobs are stopped after `HOLT_JOB_TIMEOUT_AI`. |
| `OPENROUTER_API_KEY` | *(empty)* | The server's model key; every AI report runs on it. Empty means AI reports are off: requests get `ai_unavailable` and spend nothing. |
| `OPENROUTER_MODEL` | `openai/gpt-5-mini` | Model id on OpenRouter for server-paid AI reports. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. Point it at `https://api.openai.com/v1` (with `OPENROUTER_MODEL=gpt-5-mini` and an OpenAI key) to use OpenAI directly. |
| `HOLT_MODEL_PROVIDER` | *(read from the endpoint)* | `openrouter`, `openai` or `gemini`: which parameter names the endpoint takes (`max_tokens` and `reasoning` for OpenRouter; `max_completion_tokens` and `reasoning_effort` for OpenAI). Set it only for a proxy whose URL doesn't say. |
| `HOLT_MODEL_REASONING_EFFORT` | *(empty)* | `minimal`, `low`, `medium` or `high` for reasoning models (gpt-5, o-series). Empty sends nothing and the provider's default applies. |
| `HOLT_JOB_CONCURRENCY` | `2` | User lane: people's analyses and finds running at once in this process. Each holds a thread and some memory. |
| `HOLT_JOB_TIMEOUT_RULES` | `180` | Seconds a rules report may run before it is stopped and fails with a plain "took too long" error. |
| `HOLT_JOB_TIMEOUT_AI` | `480` | The same, for AI reports and PR pre-flight checks (refunded when stopped). |
| `HOLT_JOB_TIMEOUT_FIND` | `300` | The same, for `/v1/find`. |
| `HOLT_CACHE_HOURS` | `24` | How long a finished report is served instead of re-running. |
| `HOLT_SIGNUP_AI_CREDITS` | `3` | Free AI reports every signed-in user gets once, on their first visit. |
| `HOLT_CLAIM_EVERY_DAYS` | `7` | After that, one more can be claimed each time this many days have passed since the last claim (or the welcome grant). |
| `HOLT_PRICING_FILE` | the catalogue shipped in the package (`holt_server/pricing.json`) | Features, plans and credit packs, with prices (TBD) in INR and USD. See [Credits and plans](#credits-and-plans). A file that doesn't parse stops startup. |
| `HOLT_PAYMENTS_ENABLED` | `0` | `1` switches the credit-pack checkout on (it also needs the Razorpay keys and a pack on sale). See [Credit-pack checkout](#credit-pack-checkout). |
| `HOLT_SUBSCRIPTIONS_ENABLED` | `0` | `1` switches monthly plans on (it also needs the Razorpay keys and a plan on sale with a `razorpay_plan_id`). Separate from `HOLT_PAYMENTS_ENABLED`. See [Monthly plans](#monthly-plans-subscriptions). |
| `HOLT_SUBSCRIPTION_GRACE_DAYS` | `7` | How long a paid plan outlives its billing period while Razorpay retries a failed renewal. |
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
| `HOLT_BADGE_CONCURRENCY` | `1` | Background lane: workers of their own, on top of `HOLT_JOB_CONCURRENCY`, for badge refreshes and warm-pass jobs. They take a waiting person's job before any badge work. `0` turns badge and warm work off. |
| `HOLT_FIND_CACHE_HOURS` | `6` | How long a finished `/v1/find` search is served to anyone asking the same thing. |
| `HOLT_WARM_INTERVAL_HOURS` | `0` (off) | Run a warm pass in the API process every N hours (one process at a time; Postgres advisory lock). Each pass also refreshes Discover's repository details (`repo_meta`) once a day, about one GraphQL point per hundred repos. |
| `HOLT_CONTRIBUTIONS_REFRESH_HOURS` | `24` | Re-read connected users' public pull requests (My Contributions) every N hours in the API process; stops when GitHub points drop below `HOLT_WARM_MIN_POINTS`. `0` = off. |
| `HOLT_WARM_SEEDS` | the list shipped in the package (`holt_server/seeds/repos.txt`) | The warm pass's seed list. |
| `HOLT_WARM_MAX_AGE_HOURS` | `20` | A warm pass skips repos whose report is younger than this. |
| `HOLT_WARM_MIN_POINTS` | `1500` | A warm pass stops when any GitHub token has fewer GraphQL points left. |
| `HOLT_MAX_PAGES` | `8` | Pull-request pages crawled per analysis (25 PRs a page). |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Where `holt-server` listens. |
| `LOG_LEVEL` | `INFO` | |

## How it fits together

| File | What |
|---|---|
| `holt_server/api.py` | The endpoints. Cache lookups, rate limits and the AI credit spend happen here, before a job is queued. |
| `holt_server/credits.py` | Credit balances in two pools: free (the welcome grant, the weekly claim, gifts) and purchased (lots from packs). Taking and giving back credits, pack purchases, the `/v1/me/credits` routes and the admin CLI. |
| `holt_server/entitlements.py` | Can user U use feature F now, and what does it cost: `check` (read-only) and `charge`/`refund` (inside the caller's transaction). Plans, their expiry and monthly allowances. |
| `holt_server/pricing.py` | Loads and checks the catalogue (`pricing.json`). |
| `holt_server/admin.py` | The read-only `/v1/admin/*` view (balances, ledger, plans). |
| `holt_server/jobs.py` | The runner: claims queued jobs from Postgres (user jobs before badge refreshes), runs them in threads, publishes progress for SSE. Each runner heartbeats the jobs it holds every 15s; a `running` job with no heartbeat for 90s belonged to a dead process and is queued again. Several processes can share one database. |
| `holt_server/engine.py` | Calls `holt.agent.pipeline.analyze` / `analyze_without_model`. Wraps the provider and model to report stages; uses the engine's own progress callback when it has one. Maps failures to API error codes. Logs one line per AI report (`holt_server.engine`: repo, model, tokens, dollars, seconds per stage; never evidence text or keys). |
| `holt_server/report.py` | `Assessment` + `Trace` → the Report JSON. Landing areas and evidence URLs come from the records the run read. |
| `holt_server/llm.py` | Model clients (OpenRouter over the OpenAI API; an Anthropic-native client too) built per job from the server key. Every call carries the engine's per-stage output cap (`holt.model.max_output_tokens`); an answer cut off at the cap fails the job as an `upstream` error, never half a report. Nothing is written to disk. |
| `holt_server/starter.py` | Lazy adapter over `holt.starter`; the endpoints return 501 until that module exists. |
| `holt_server/pro.py` | Client for the optional paid-features service (`HOLT_PRO_URL`): the key header, 2 s connect / 10 s read timeouts, one retry on a failed connection or a 503, and its error envelope turned into this API's errors with plain messages. `Services.pro` is None when it is off, and `Services.require_pro()` then answers 501 "not available yet". |
| `holt_server/playbook.py` | The paid playbook: the teaser and unlock routes, charging (`entitlements.charge`) with a per-user unlock, the `playbook` job that calls the service, the per-repo cache, and refunds for everyone waiting on a job that fails. |
| `holt_server/preflight.py` | PR pre-flight: the state and start routes, charging (`entitlements.charge`, feature `preflight`) in the transaction that queues the `preflight` job, the job that calls the service, and results kept per user, target and head commit (a re-check of the same commit is refunded). A failed job is refunded by `refund_job`. |
| `holt_server/badge.py` | The README badge SVG. |
| `holt_server/discover.py` | `GET /v1/discover` and the "most welcoming <language> repos" boards, from the latest rules report per repo (never the model), plus `repo_meta`: language, stars, topics and description, which the warm pass reads a hundred repos per GraphQL query. |

Identical requests share one job. That is enforced by a partial unique index
on `jobs.dedupe_key` (only over queued/running jobs), so two requests racing
each other still get one job and spend one credit.

AI reports run on the server's OpenRouter key and cost the user one credit.
Signed-in users get `HOLT_SIGNUP_AI_CREDITS` free credits once, on their first
visit, and can claim one more every `HOLT_CLAIM_EVERY_DAYS`; claims don't pile
up. The website doesn't take users' own API keys (the CLI does).

## Credits and plans

Payments are off; nothing is on sale. This is the model the payment code
([Credit-pack checkout](#credit-pack-checkout)) plugs into.

**Catalogue.** `holt_server/pricing.json` (or `HOLT_PRICING_FILE`) lists the
paid features and what one use costs in credits (`free_credits`: whether free
credits may pay for it), the plans (which features each covers, unlimited or
`per_month` uses per UTC month, `period_days`) and the credit packs (`credits`,
`expires_days`, null = never). Prices are `inr_paise` / `usd_cents`, null
while TBD, and `on_sale` is false everywhere. `python -m holt_server.pricing`
checks a file.

**Balances.** Free credits are `users.ai_credits`. Purchased credits are
`credit_lots` rows, one per pack (`credits.purchase_pack`, idempotent on the
payment's reference) or admin grant, each with an optional expiry; what is
left in an expired lot is written off the next time the user is seen. Every
change writes a `credit_events` row with its pool (`source`: free or
purchased) and kind (grant, claim, purchase, adjust, spend, refund, expire).
Per user, the free rows sum to `ai_credits` and the purchased rows to what the
lots have left.

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

## Credit-pack checkout

`holt_server/payments.py`: Razorpay, INR, one-time payments for the packs in
the catalogue. **Off by default**: it needs `HOLT_PAYMENTS_ENABLED=1`, the
Razorpay keys, and a pack with `on_sale: true` and an `inr_paise` price. The
flow and the endpoints are in API.md ("Credit packs"); the short version:

- An order (`orders` table) copies the pack, credits and price from the
  catalogue when it is created; the browser only names the pack.
- Credits are added only for a payment Razorpay vouches for: the Checkout
  callback's signature (then the payment is fetched from Razorpay), or a
  webhook's signature. The payment must be captured and match the order's
  amount and currency; a mismatch puts the order on `held`, credits nothing
  and logs an error.
- `orders.status` goes `created` → `paid` once, in the same transaction that
  adds the `credit_lots` row (its `reference` is the payment id, unique), so
  the callback, the webhooks and their retries credit a pack exactly once.

Webhook: in the Razorpay dashboard, point a webhook at
`https://<site>/api/payments/razorpay/webhook` (served by `web/`, which
forwards it here) for `payment.authorized`, `payment.captured`,
`payment.failed` and `order.paid`, and put its secret in
`RAZORPAY_WEBHOOK_SECRET`.

Trying it locally in test mode: use `rzp_test_` keys, a pricing file with a
pack on sale (copy `pricing.json`, set `on_sale: true` and a price, point
`HOLT_PRICING_FILE` at it) and `HOLT_PAYMENTS_ENABLED=1`. Razorpay can't reach
a local webhook, so the callback does the crediting; test the webhook on
staging.

## Monthly plans (subscriptions)

`holt_server/subscriptions.py`: Razorpay subscriptions, INR. **Off by
default, with its own switch**, separate from credit packs:
`HOLT_SUBSCRIPTIONS_ENABLED=1`, the Razorpay keys, and a plan with
`on_sale: true`, an `inr_paise` price and a `razorpay_plan_id`. Create that
plan in the Razorpay dashboard (Subscriptions → Plans, monthly, the same
price); the server fetches it before each new subscription and refuses if its
price differs. Endpoints and behaviour are in API.md ("Plans"); the short
version:

- A `subscriptions` row per subscription (at most one live per user, a partial
  unique index), and a `subscription_charges` row per payment (unique payment
  id: the billing history, and what makes a replayed `subscription.charged`
  a no-op).
- The plan is set with `entitlements.write_plan` (the in-transaction form of
  `set_plan`), `actor=razorpay`, `reference=<Razorpay subscription id>`, to the
  end of the period Razorpay says was paid for plus
  `HOLT_SUBSCRIPTION_GRACE_DAYS` (7). Halted/paused ends it now;
  cancelled/completed ends it with the paid period. Only the subscription
  named on the user's latest `plan_events` row can end their plan, so admin
  grants are never undone by a webhook.
- Events about an older period than the row holds are ignored; a cancelled,
  completed or expired subscription never comes back.
- Cancelling from Settings stops renewal at the end of the paid period
  (Razorpay `cancel_at_cycle_end=1`); an unpaid subscription, or one whose
  renewal is failing, is cancelled at once.
- With the switch off, existing subscriptions still renew, lapse and can be
  cancelled.

Webhook: the same Razorpay webhook as the packs; also tick
`subscription.authenticated`, `.activated`, `.charged`, `.pending`, `.halted`,
`.paused`, `.resumed`, `.cancelled` and `.completed`.

Trying it locally in test mode: as for packs, plus a test-mode plan in the
Razorpay dashboard, its id as `razorpay_plan_id` in your pricing file, and
`HOLT_SUBSCRIPTIONS_ENABLED=1`. Sign webhooks yourself with a local
`RAZORPAY_WEBHOOK_SECRET` to try renewals and failures.

Per process (fine for one server; revisit with more): rate-limit counters,
the badge lane's concurrency count and the repo-name cache are in memory. SSE
fan-out is in memory but falls back to re-reading the jobs table every 15s.

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

1. **Reports** (7-day rules) for the ~300 repositories in `server/holt_server/seeds/repos.txt`,
   skipping any under 20 hours old.
2. **Starter issues** for the same repositories.
3. **`/v1/find`** for the searches the web app's own pages make: the nine
   `/hacktoberfest` tabs, and each `/find` language chip with and without
   Hacktoberfest (23 searches, 7-day budget). Reports go first because a find
   screens repositories through the report cache.

Everything goes through the normal job queue at badge priority (user requests
always run first; one warm job at a time) and the pass checks the GitHub
points left before each step, stopping under `HOLT_WARM_MIN_POINTS`.

```sh
uv run python -m holt_server.warm --dry-run           # what would run
uv run python -m holt_server.warm                     # the whole thing
uv run python -m holt_server.warm --limit 50 --no-find
```

Or set `HOLT_WARM_INTERVAL_HOURS` to run it inside the API on a schedule.

**GitHub cost, measured** (GraphQL points; a token has 5,000 an hour): a rules
report ~10 (up to ~20 for very busy repositories), starter issues ~5, a find
search ~60 when its repositories are not cached yet and much less when they
are. A cold full pass is therefore roughly 300 × ~15–30 + 23 × ~20–60 ≈
**5,000–10,000 points**: about two token-hours, e.g. two tokens in
`GITHUB_TOKENS` for one hour, or one token over two runs (the second resumes
where the first stopped, since finished reports are skipped). A daily re-warm
costs about the same, because reports expire after 20 hours.

The seed list is built by `server/scripts/build_seeds.py` (the same sourcing as
`/v1/find`: the hacktoberfest topic, then beginner-friendly repositories in 12
languages; ~30 points). Re-run it to refresh the list and commit the result:

```sh
GITHUB_TOKEN=... uv run python server/scripts/build_seeds.py --total 300
```

## Tests

```sh
uv run pytest server/tests -q
```

SQLite instead of Postgres, the GitHub lookup faked, no network. Most tests
fake the engine; `test_server_engine.py` runs the real one over the committed
`NixOS/nixpkgs` replay fixtures, in both rules and AI mode.
