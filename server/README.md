# Holt API server

The HTTP API behind the Holt web app. It wraps the engine in `src/holt` and
implements [`API.md`](../API.md), which is the contract with `web/`.

FastAPI, Postgres (SQLAlchemy async + asyncpg), and an in-process jobs runner.
No Redis: jobs live in a Postgres table and up to `HOLT_JOB_CONCURRENCY` run at
once in worker threads.

## Run it locally

```sh
export PATH="$HOME/.local/bin:$PATH"
uv sync                                   # from the repo root; installs holt-server too

docker compose -f server/compose.yml up -d   # Postgres on 127.0.0.1:${HOLT_DB_PORT:-20131}
cp server/.env.example server/.env           # then fill it in (see below)

cd server
PORT=20130 uv run holt-server              # http://127.0.0.1:20130, docs at /docs
curl localhost:20130/health
```

`holt-server` reads `server/.env` when started from `server/`, plus the process
environment (which wins). The schema is created on startup (`create_all`).
Stop Postgres with `docker compose -f server/compose.yml down` (add `-v` to
drop the data).

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
| `HOLT_SECRET_KEY` | *(empty)* | Encrypts saved BYOK keys (AES-256-GCM). Use 32 random bytes, base64: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`. Changing it makes saved keys unreadable (users are asked to save them again). |
| `HOLT_WEB_URL` | `https://holt.dev` | The badge links to `{HOLT_WEB_URL}/{owner}/{repo}`. |
| `GITHUB_TOKENS` | *(empty)* | Comma-separated GitHub tokens, used round-robin, one per analysis. Read-only public access is enough (a fine-grained token with no extra permissions). |
| `OPENROUTER_API_KEY` | *(empty)* | The server's model key, used for users' free AI reports. Empty means AI reports need BYOK. |
| `OPENROUTER_MODEL` | `openai/gpt-5-mini` | Model id on OpenRouter for server-paid AI reports. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. |
| `HOLT_JOB_CONCURRENCY` | `2` | Analyses running at once in this process. Each holds a thread and some memory. |
| `HOLT_CACHE_HOURS` | `24` | How long a finished report is served instead of re-running. |
| `HOLT_PLANS_FILE` | *(bundled `holt_server/plans.toml`)* | Plans, allowances, packs and prices. See [Billing](#billing). |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | *(empty)* | Razorpay API keys (test or live). Empty turns payments off: `/v1/billing/*` answer 501 and `/v1/plans` reports `"provider": null`. |
| `RAZORPAY_WEBHOOK_SECRET` | *(empty)* | The secret set on the Razorpay webhook. Empty means every webhook is rejected. |
| `RAZORPAY_PLAN_<PLAN>_<CURRENCY>` | *(empty)* | Razorpay plan id per plan and currency, e.g. `RAZORPAY_PLAN_STUDENT_INR=plan_…`. Overrides `razorpay_plan_id` in the plans file. |
| `HOLT_BILLING_GRACE_HOURS` | `24` | How long a paid plan stays on past its period end while the renewal webhook arrives. |
| `HOLT_SUBSCRIPTION_CYCLES` | `120` | Billing cycles a Razorpay subscription is created for (Razorpay requires a count). |
| `HOLT_ANON_RATE_PER_HOUR` | `10` | New jobs / starter-issue lookups per hour per IP for anonymous callers (`X-Holt-Client-Ip`). Cached answers are free. |
| `HOLT_USER_RATE_PER_HOUR` | `60` | The same, per signed-in user. |
| `HOLT_BADGE_RATE_PER_IP` | `20` | Rules checks a single client can trigger per hour by loading badges (client = `CF-Connecting-IP`, else the socket address). |
| `HOLT_BADGE_RATE_TOTAL` | `60` | The same, across all clients. |
| `HOLT_BADGE_CONCURRENCY` | `1` | Badge-triggered checks running at once; always fewer than `HOLT_JOB_CONCURRENCY`, and they queue behind user jobs. |
| `HOLT_MAX_PAGES` | `8` | Pull-request pages crawled per analysis (25 PRs a page). |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Where `holt-server` listens. |
| `LOG_LEVEL` | `INFO` | |

## How it fits together

| File | What |
|---|---|
| `holt_server/api.py` | The endpoints. Cache lookups, rate limits, quota and BYOK checks happen here, before a job is queued. |
| `holt_server/jobs.py` | The runner: claims queued jobs from Postgres (user jobs before badge refreshes), runs them in threads, publishes progress for SSE. Each runner heartbeats the jobs it holds every 15s; a `running` job with no heartbeat for 90s belonged to a dead process and is queued again. Several processes can share one database. |
| `holt_server/engine.py` | Calls `holt.agent.pipeline.analyze` / `analyze_without_model`. Wraps the provider and model to report stages; uses the engine's own progress callback when it has one. Maps failures to API error codes. |
| `holt_server/report.py` | `Assessment` + `Trace` → the Report JSON. Landing areas and evidence URLs come from the records the run read. |
| `holt_server/llm.py` | Model clients (OpenRouter/OpenAI/Gemini over the OpenAI API, Anthropic native) built per job from the server key or a decrypted BYOK key. Nothing is written to disk. |
| `holt_server/starter.py` | Lazy adapter over `holt.starter`; the endpoints return 501 until that module exists. |
| `holt_server/badge.py` | The README badge SVG. |

Identical requests share one job. That is enforced by a partial unique index
on `jobs.dedupe_key` (only over queued/running jobs), so two requests racing
each other still get one job and one quota charge.

Who pays for an AI report: a saved BYOK key if the user has one (free and
unlimited); otherwise the server's OpenRouter key, charged to the plan's
allowance first and then to pack credits (`holt_server/quota.py`), each an
atomic `UPDATE` in the same transaction as the job insert. The job records
which pool paid; a report that fails goes back to that pool.

Per process (fine for one server; revisit with more): rate-limit counters,
the badge lane's concurrency count and the repo-name cache are in memory. SSE
fan-out is in memory but falls back to re-reading the jobs table every 15s.

The schema is made with `create_all`, which adds missing tables but never
alters existing ones. Pre-launch, after a schema change, recreate the dev
database (`docker compose -f server/compose.yml down -v`).

## Billing

Plans and packs live in `holt_server/plans.toml` (or `HOLT_PLANS_FILE`):
allowances, whether a plan gets the priority queue, and prices in minor units
(paise/cents). Changing a price is a config change, not a code change.

The payment provider sits behind `billing/provider.py` (`PaymentProvider`);
`billing/razorpay.py` implements it with the Orders API (packs) and the
Subscriptions API (plans). Adding Stripe or Lemon Squeezy means another class
with the same methods, plus its webhook route; `billing/service.py` (what a
payment grants) stays as it is.

Entitlements change only in `billing/service.py`, called from the
signature-checked `/v1/billing/verify` and the HMAC-checked webhook. Payments
and subscriptions are stored with provider ids, minor-unit amounts, currency
and status; no card data is ever seen.

Setting up Razorpay (once the account exists):

1. Create a Plan in the dashboard for each paid plan and currency (monthly,
   same amount as `plans.toml`), and put the ids in `RAZORPAY_PLAN_<PLAN>_<CURRENCY>`.
2. Add a webhook to `https://<api host>/webhooks/razorpay` with a secret
   (`RAZORPAY_WEBHOOK_SECRET`) and these events: `payment.captured`,
   `payment.failed`, `order.paid`, and all `subscription.*`.
3. Set `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`. Use test-mode keys first.

## Tests

```sh
uv run pytest server/tests -q
```

SQLite instead of Postgres, the GitHub lookup faked, no network. Most tests
fake the engine; `test_server_engine.py` runs the real one over the committed
`NixOS/nixpkgs` replay fixtures, in both rules and AI mode.
