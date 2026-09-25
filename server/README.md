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
| `HOLT_FREE_AI_LIMIT` | `3` | AI reports per user per calendar month on the server's key (plan `free`). `0` turns free AI reports off. |
| `HOLT_PLAN_AI_LIMIT` | `100` | The same, for any other plan (set by hand in the `users` table for now). |
| `HOLT_ANON_RATE_PER_HOUR` | `10` | Work bucket: new analyses and find per hour per IP for anonymous callers (`X-Holt-Client-Ip`). Cached answers are free. |
| `HOLT_USER_RATE_PER_HOUR` | `60` | The same, per signed-in user. |
| `HOLT_ANON_READ_RATE_PER_HOUR` | `120` | Read bucket, per IP: starter-issue lookups that miss the cache. Separate from the work bucket above, so page views never block analyses. |
| `HOLT_USER_READ_RATE_PER_HOUR` | `600` | The same, per signed-in user. |
| `HOLT_STARTER_CACHE_HOURS` | `1` | How long starter issues per repository are served from the cache. |
| `HOLT_BADGE_RATE_PER_IP` | `20` | Rules checks a single client can trigger per hour by loading badges (client = `CF-Connecting-IP`, else the socket address). |
| `HOLT_BADGE_RATE_TOTAL` | `60` | The same, across all clients. |
| `HOLT_BADGE_CONCURRENCY` | `1` | Badge refreshes and warm-pass jobs running at once. Fewer than `HOLT_JOB_CONCURRENCY` when there are several workers; with a single worker they share it, but only when no user job is waiting. `0` turns them off. |
| `HOLT_FIND_CACHE_HOURS` | `6` | How long a finished `/v1/find` search is served to anyone asking the same thing. |
| `HOLT_WARM_INTERVAL_HOURS` | `0` (off) | Run a warm pass in the API process every N hours (one process at a time; Postgres advisory lock). |
| `HOLT_WARM_SEEDS` | the list shipped in the package (`holt_server/seeds/repos.txt`) | The warm pass's seed list. |
| `HOLT_WARM_MAX_AGE_HOURS` | `20` | A warm pass skips repos whose report is younger than this. |
| `HOLT_WARM_MIN_POINTS` | `1500` | A warm pass stops when any GitHub token has fewer GraphQL points left. |
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

Who pays for an AI report: a saved BYOK key if the user has one (it does not
use up free reports); otherwise the server's OpenRouter key, counted against the
monthly quota (an atomic `UPDATE`, in the same transaction as the job insert).
A report that fails is refunded, again atomically and only against the month
it was charged to.

Per process (fine for one server; revisit with more): rate-limit counters,
the badge lane's concurrency count and the repo-name cache are in memory. SSE
fan-out is in memory but falls back to re-reading the jobs table every 15s.

The schema is made with `create_all`, which adds missing tables but never
alters existing ones. Pre-launch, after a schema change, recreate the dev
database (`docker compose -f server/compose.yml down -v`).

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
