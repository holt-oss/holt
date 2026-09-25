# Holt HTTP API (contract between `server/` and `web/`)

Version: v0 (pre-launch). The server is FastAPI in `server/`. The browser
never calls it directly. `web/` calls it from Next.js server code (route
handlers, server components) — a BFF. So:

- Every request carries `X-Holt-Internal-Key: <shared secret>` (env
  `HOLT_INTERNAL_KEY` on both sides). Requests without it get 401.
- Requests made for a signed-in user also carry `X-Holt-User: <user id>`.
  The server trusts it because of the internal key. Anonymous requests omit it.
- Anonymous requests carry `X-Holt-Client-Ip` for rate limiting. An anonymous
  request that needs rate limiting (new analyses, find, starter issues) without
  it gets 400 `invalid_request`; the server never falls back to the BFF's own
  address.
- Base URL for web: env `HOLT_API_URL` (e.g. `http://127.0.0.1:$PORT`).

Users, sessions and OAuth (GitHub + Google) live in `web/` (Auth.js). The
server keeps its own `users` table keyed by the same id, created on first
sight, holding plan, quota usage and the encrypted BYOK key.

All bodies are JSON. Errors: `{"error": {"code": "<code>", "message": "<plain English for a beginner>"}}`
with codes: `unauthorized`, `not_found` (repo missing or private),
`invalid_repo`, `rate_limited` (ours or GitHub's; include `retry_after` seconds),
`quota_exceeded`, `needs_key` (AI report requested with no plan and no BYOK),
`upstream` (GitHub/model failure), `internal`.

HTTP statuses: `unauthorized` 401, `not_found` 404, `invalid_repo` and
`invalid_request` (malformed body or query) 400, `rate_limited` 429 (also sent
as a `Retry-After` header), `quota_exceeded` 402, `needs_key` 403 (also for an
anonymous AI request, and when a saved BYOK key is rejected by its provider),
`upstream` 502, `internal` 500, `not_implemented` 501 (starter issues and find,
until the engine side ships).

## Repo identifiers

`{owner}/{repo}`, case-insensitive, normalised to GitHub's canonical casing in
responses. The server also accepts and normalises full URLs
(`https://github.com/o/r`, `github.com/o/r.git`, `…/tree/main`, `?tab=…`).

## Report object

```jsonc
{
  "repo": "pallets/flask",
  "mode": "rules" | "ai",            // rules = no model; ai = model-written report
  "days": 7,                          // contributor time budget used
  "verdict": "viable" | "not_viable" | "insufficient_evidence",
  "headline": "Worth your time" | "Not worth your time" | "Not enough evidence",
  "summary": "string | null",         // ai mode: short plain-English paragraph
  "stats": {
    "outsider_attempts": 100, "outsider_merged": 15, "distinct_outsiders": 72,
    "first_time_merged_authors": 15, "no_reply": 63,
    "median_first_response_hours": 0.8, "bot_share": 0.085
  },
  "decided_by": ["plain-English rule sentence", "..."],
  "unknowns": ["plain-English sentence", "..."],
  "landing": [ { "path": "pkgs/by-name", "merged": 13, "attempted": 62 } ],
  "never_landed": [ { "path": "pkgs/applications", "attempted": 6 } ],
  "evidence": [
    { "id": "pr:NixOS/nixpkgs#526518:opened", "url": "https://github.com/NixOS/nixpkgs/pull/526518",
      "kind": "onboarding", "value": "substantive", "text": "…", "quote": "string | null" }
  ],
  "evidence_until": "2026-06-01T00:00:00Z",
  "generated_at": "2026-09-25T12:00:00Z",
  "cost": { "model": "…", "input_tokens": 9000, "output_tokens": 6000 } // ai only, else null
}
```

Every evidence item MUST have a clickable `url`.

`kind` is a machine key: in AI mode the engine field the claim is about
(`onboarding`, `outsider_posture`, `repo_kind`, …) or `outcome` for what
happened on one pull request (`value` e.g. `merged_after_review`, with the
maintainer's words in `quote`). Rules mode has no model claims; it lists the
newest first-timer pull requests behind the counts instead, as
`kind: "outsider_pr"`, `value: "merged" | "no_reply"`.

## Endpoints

### `GET /health` → `{"ok": true, "version": "…"}` (no internal key needed)

### `POST /v1/analyses`
Body: `{"repo": "owner/repo", "mode": "rules"|"ai", "days": 7, "refresh": false}`
- Returns `200 {"status":"done","report":Report}` immediately when a cached
  report exists (same repo/mode/days, younger than 24h) and `refresh` is false.
- Otherwise `202 {"status":"queued","job_id":"…"}`.
- `mode:"rules"` is free and allowed anonymously (rate-limited per IP).
- `mode:"ai"` requires `X-Holt-User`, and either an active plan with quota
  left (uses the server's OpenRouter key) or a stored BYOK key. Else `needs_key`
  / `quota_exceeded`.

### `GET /v1/analyses/{job_id}` → `{"status":"queued"|"running"|"done"|"error", "stage": "Reading pull requests", "progress": 0.4, "report": Report|null, "error": Error|null}`

### `GET /v1/analyses/{job_id}/events` — Server-Sent Events
Events: `stage` `{"stage": "…", "progress": 0.0–1.0}`, then exactly one of
`done` `{"report": Report}` or `error` `{"error": Error}`. `stage` strings are
plain English ("Fetching pull requests", "Reading threads", "Checking evidence",
"Writing the report").

### `GET /v1/reports/{owner}/{repo}?mode=rules|ai&days=7`
Latest cached report or 404 `not_found`. Public via the BFF: no user needed
(used for shareable pages and OG images), but it still requires the internal
key like every `/v1` route.

### `GET /v1/repos/{owner}/{repo}/starter-issues?limit=20`
Open, unassigned issues in this repo that suit a newcomer, best first:
`{"repo": "…", "issues": [StarterIssue]}`.

### `POST /v1/find`
Body: `{"languages": ["python"], "topics": [], "days": 7, "hacktoberfest": true, "limit": 20}`
Returns `{"results": [ { "repo": "owner/repo", "headline": "…", "verdict": "…",
"description": "string | null", "language": "string | null", "stars": 123 | null,
"stats": {…subset}, "issues": [StarterIssue] } ]}` (`description`, `language`
and `stars` are null when the finder did not supply them), only repos whose rules
verdict is `viable`, ordered by starter-issue quality. May return `202` with a
`job_id` like analyses if it takes long; same polling/SSE endpoints under
`/v1/find/{job_id}`. (The server always answers `202`. Polling a find job
returns `results` instead of `report`; the SSE `done` event carries
`{"results": [...]}`.)

StarterIssue:
```jsonc
{ "number": 123, "title": "…", "url": "https://github.com/o/r/issues/123",
  "labels": ["good first issue"], "created_at": "…", "comments": 2,
  "why": ["Labelled good first issue", "Touches docs/, where 8 of 10 outsider PRs were merged"] }
```

### `GET /badge/{owner}/{repo}.svg` (no internal key; public; `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`)
Shields-style SVG badge showing the rules verdict ("Holt | newcomer-friendly").
Maintainers embed it in READMEs; it links back to the report page at
`{HOLT_WEB_URL}/{owner}/{repo}`. Uses the latest 7-day rules report; when
there is none, or it is over 24h old, it shows what it has ("not checked yet")
and queues a rules check behind it. Badge-queued checks have their own rate
limits (per client IP and in total, separate from user limits), run at most
one at a time, and wait behind every user request.

### Account
- `GET /v1/me` → `{"plan": "free"|"…", "quota": {"ai_used": 1, "ai_limit": 3, "resets_at": "…"}, "byok": {"provider": "openrouter"|"openai"|"anthropic"|"gemini", "model": "…", "set": true} | null}`
- `PUT /v1/me/byok` body `{"provider": "…", "api_key": "…", "model": "…"}` → stored
  encrypted (AES-GCM, key from env `HOLT_SECRET_KEY`); the key is never returned.
  Returns the same body as `GET /v1/me`.
- `DELETE /v1/me/byok` → the `GET /v1/me` body.
- `GET /v1/me/history?limit=50` → recent analyses by this user:
  `{"items": [{"job_id", "repo", "mode", "days", "status", "verdict", "headline", "created_at"}]}`
  (`verdict`/`headline` are null until the job is done).

`/v1/me*` without `X-Holt-User` → 401 `unauthorized`. AI reports use the
user's BYOK key when one is saved (not counted against quota); otherwise the
server's key, counted per calendar month (UTC). Failed AI jobs are not counted.

Plans and payments are not implemented yet; `plan` is set manually in the DB
for now. Free-tier quota values come from env.

## Public proxy for the browser extension (implemented by `web/`)

The browser extension (`extension/`) cannot hold `HOLT_INTERNAL_KEY`, so
`web/` exposes two read-only, anonymous proxy routes on the public host
(default `holt.aahil-khan.xyz`). They only read the cache; they never start an
analysis or call GitHub.

### `GET /api/public/report/{owner}/{repo}`
Proxies `GET /v1/reports/{owner}/{repo}?mode=rules&days=7`.
- `200` → the Report object (above), `mode: "rules"`. The extension reads only
  `verdict` and `stats.outsider_attempts` / `stats.outsider_merged`, so the
  proxy may strip `evidence` to keep responses small.
- `404` → `{"error": {"code": "not_found", ...}}` when nothing is cached yet
  (or the repo is missing/private). The extension then shows "Check with Holt"
  and links to `/{owner}/{repo}`, whose page starts the analysis.
- `429` `rate_limited` / `5xx` → shown as "Check with Holt" too.

### `GET /api/public/starter-issues/{owner}/{repo}`
Proxies `GET /v1/repos/{owner}/{repo}/starter-issues?limit=20` →
`{"repo": "…", "issues": [StarterIssue]}`. The extension reads `number` and
`why`. `404` when nothing is known.

Both routes:
- Accept `GET` and `OPTIONS` only, no cookies or auth. Rate-limit per IP.
- Send `Cache-Control: public, max-age=900` (15 min) on `200` and
  `max-age=300` on `404`, so a new analysis shows up soon.
- Send `Access-Control-Allow-Origin: *`. The extension fetches from its
  background worker (which its host permission covers), but open CORS keeps
  other read-only clients simple; the data is public.
- Normalise `{owner}/{repo}` as in "Repo identifiers"; reject anything else
  with `400 invalid_repo`.
