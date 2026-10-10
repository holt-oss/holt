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
sight, holding plan and free AI credits. The website doesn't take users' own
API keys (the CLI does); every AI report runs on the server's key.

Response shapes are pydantic models in
`server/holt_server/schema.py`; the web's TypeScript types are generated from
them (`server/scripts/api_types.sh` writes `web/src/lib/api-schema.ts`, and CI
fails when it is stale). This file describes the fields; the models are exact.
Change a model, this file and the generated types in the same PR.

All bodies are JSON. Errors: `{"error": {"code": "<code>", "message": "<plain English for a beginner>"}}`
with codes: `unauthorized`, `not_found` (repo missing or private),
`invalid_repo`, `rate_limited` (ours or GitHub's; include `retry_after` seconds),
`quota_exceeded` (not enough credits, or a plan's monthly allowance is used up),
`needs_plan` (the feature comes only with a paid plan), `needs_key` (AI report requested without
signing in), `ai_unavailable` (AI is switched off: the server has no
model key or no AI budget, or the environment's AI budget is used up, which
also sends `"reason": "ai_budget_used_up"`; nothing is charged), `claim_not_ready` (a weekly claim before it is due),
`payments_off` (passes aren't on sale), `payment_unconfirmed` (a
payment's signature didn't check out; nothing was given),
`upstream` (GitHub/model failure), `internal`.

HTTP statuses: `unauthorized` 401, `not_found` 404, `invalid_repo` and
`invalid_request` (malformed body or query) 400, `rate_limited` 429 (also sent
as a `Retry-After` header), `quota_exceeded` 402, `needs_plan` 402, `needs_key` 403,
`claim_not_ready` 409, `payments_off` 403, `payment_unconfirmed` 400, `ai_unavailable` 503, `upstream` 502, `internal` 500, `not_implemented` 501 (starter issues and find,
until the engine side ships).

## Rate limits

Two separate hourly buckets, per IP for anonymous callers and per user when
signed in:

- **work** — new analyses (`POST /v1/analyses` that queues a job) and
  `POST /v1/find` searches that are not cached or already running. Small
  (anonymous: 10/h). Cached answers, and joining a running job, are free.
- **read** — cache misses on reads (`/starter-issues`, `/repos/search`). Generous (anonymous:
  120/h). Viewing, reloading and sharing report pages can never use up work.

`GET /v1/reports/…` reads only the cache and is not rate limited.
`POST /v1/feedback` has a small bucket of its own (see Feedback), and so do
saving and unsaving repos (see Saved repos).

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
  "verdict": "viable" | "long_shot" | "not_viable" | "insufficient_evidence" | "personal" | "catalogue",
  "headline": "Worth your time" | "Long shot" | "Not worth your time" | "Not enough evidence" | "Personal project" | "A list, not code",
  "tone": "good" | "warn" | "bad" | "neutral", // the verdict's colour
  "verdict_line": "string",           // line 1: the reason for the verdict, one sentence
  "numbers_line": "string",           // line 2: what happened to outside contributors, with dates
  "first_timer_line": "string | null", // "9 people got their first pull request merged here."
  "next_step": "string",              // line 3: what to do next
  "stat_line": "string | null",       // short count for the extension chip: "22 of 120 outside PRs merged"
  "counted": [ { "topic": "What we read", "text": "The newest 200 pull requests on GitHub, opened 3 Jun – 26 Sep 2026." } ],
  "how_long": [ { "topic": "first reply", "text": "Typically 14 hours. Most get one within 3 days." } ],
  "odds": { "level": "good" | "fair" | "long", "tone": "good" | "warn" | "bad",
            "text": "most outside pull requests get a reply, and plenty get merged" } | null,
  "bottom_line": "string | null",     // ai mode: at most two model-written sentences, the lead of the AI explanation
  "summary": "string | null",         // ai mode: short plain-English paragraph
  "stats": {
    "outsider_attempts": 100, "outsider_merged": 15, "distinct_outsiders": 72,
    "first_time_merged_authors": 15, "no_reply": 63,
    "median_first_response_hours": 0.8, "bot_share": 0.085,
    "still_open": 12, "closed_silently": 20, "closed_by_bot": 31, "withdrawn": 4,
    "too_old": 0,                    // opened more than a year ago: read, in no count (default 0)
    "timing": {                      // how long it takes here (engine 7); null before it
      "first_reply_half_hours": 5.0, "first_reply_slow_hours": 70.2,
      "merged_within_3_days": 0.41, "merged_within_7_days": 0.52, "merged_within_14_days": 0.6,
      "merged_within_30_days": 0.68, "merged_within_60_days": 0.72,
      "merge_typical_days": 4.1, "merge_slow_days": 38.0, "merge_half_days": 6.2,
      "merge_cohort_prs": 180, "merge_cohort_merged": 130,
      "merge_cohort_from": "2026-02-10", "merge_cohort_to": "2026-07-28",
      "merges_in_bursts": false, "last_outside_merge": "2026-09-27",
      "stale_bot": true, "stale_close_days": 37
    } | null
  },
  "decided_by": ["plain-English rule sentence", "..."],
  "rule_codes": ["merges", "rubber_stamp"], // stable code per decided_by line, same order
  "unknowns": ["plain-English sentence", "..."],
  "landing": [ { "path": "pkgs/by-name", "merged": 13, "attempted": 62, "is_file": false } ],
  "never_landed": [ { "path": "pkgs/applications", "attempted": 6, "is_file": false } ],
                                    // is_file: the path is one file, not a folder (default false)
  "evidence": [
    { "id": "pr:NixOS/nixpkgs#526518:opened", "url": "https://github.com/NixOS/nixpkgs/pull/526518",
      "kind": "onboarding", "value": "substantive", "text": "…", "quote": "string | null" }
  ],
  "evidence_until": "2026-06-01T00:00:00Z", // or null
  "generated_at": "2026-09-25T12:00:00Z",
  "sample": { "pull_requests": 200, "first_opened": "2026-06-03T10:00:00Z",
              "last_opened": "2026-09-26T09:00:00Z", "team_pull_requests": 40,
              "team_people": 9, "bot_pull_requests": 12 } | null,
  "asks": [ { "code": "ticket_first" | "no_ai_prs" | "ok_to_test" | "sig_team" | "cla" | "dco"
              | "issue_first" | "ai_disclosure" | "duplicates" | "stale_bot",
              "url": "https://github.com/…", "link": "https://code.djangoproject.com" | null,
              "days": 37 | null } ],
  "budget_independent": true,         // the verdict is the same for any `days` (see below)
  "cost": { "input_tokens": 9000, "output_tokens": 6000,
            "usd": 0.0123, "seconds": 48.2 }, // ai only, else null
  "holt_users": { "people": 9, "pull_requests": 12, "merged": 7, "closed": 2,
                  "waiting": 3, "window_days": 365, "computed_at": "…" } | null,
  "about": {                          // what the repo is; null until its details are read
    "description": "string | null", "readme_line": "string | null",
    "readme": "# Title\n\nMarkdown… | null",
    "homepage": "https://… | null", "stars": 91234, "forks": 1200 | null,
    "open_issues": 57 | null, "pull_requests": 4100 | null,
    "open_pull_requests": 12 | null, "contributors": 812 | null,
    "license": "MIT | null", "topics": ["cli"],
    "languages": [ { "name": "Python", "share": 0.92 } ],
    "created_at": "…Z | null", "pushed_at": "…Z | null",
    "default_branch": "main | null", "archived": false, "fork": false,
    "fork_of": "owner/repo | null",
    "links": [ { "kind": "contributing" | "discussions" | "docs" | "discord" | "slack"
                 | "gitter" | "matrix" | "zulip", "url": "https://…" } ],
    "latest_release": { "tag": "v3.1.0", "published_at": "…Z | null", "url": "https://…" } | null,
    "top_contributors": [ { "login": "davidism", "name": "David Lord" | null,
                            "url": "https://github.com/davidism",
                            "avatar_url": "https://avatars.githubusercontent.com/…" | null,
                            "contributions": 2500 | null } ],
    "fetched_at": "…Z"
  } | null
}
```

`bottom_line` and `summary` are null in rules mode (the headline and
`verdict_line` already are the rules report's bottom line). In AI mode they are
the model's words, checked by the engine before they are stored; either can be
null on a report where the model wrote nothing usable, and `bottom_line` is
null on AI reports cached before it existed. Show them as AI-written.

`cost` is for operators, not the product: `usd` is what the model calls cost
(from the engine's price table), `seconds` the whole run's wall time. Both are
null on reports cached before they were recorded. Per-stage timings go to the
server log, not the report. Which model wrote a report, playbook or summary is
never in a response; the server keeps it in its `ai_runs` table.

`holt_users` is what connected Holt users' public pull requests to this
repository came to (from My Contributions, the last `window_days`): counts only,
never who. It is filled only by `GET /v1/reports/{owner}/{repo}` (null on the
analysis endpoints and never stored with the report), and only when at least 5
different people make up the numbers: one person with many pull requests
counts once. Users who turned on `stats_opt_out` are never counted. The numbers
are recounted by the daily contributions refresh (and
`python -m holt_server.contributions stats`); opting out or disconnecting
recounts that user's repositories at once. Surfaces show them as they come and
never rank or name anyone.

`about` is GitHub's own description of the repository and its counters, plus
the README's first sentence (`readme_line`, plain text), as `repo_meta` last
read them: right after a repository's first report and daily by the warm pass,
many repositories per GraphQL query, never on the request path. Like
`holt_users` it is filled only by `GET /v1/reports/{owner}/{repo}` and never
stored with the report; it is null until the details have been read, and the
fields added with it (`forks` onwards, `readme_line`) are null on rows read
before they existed. `pull_requests` counts every pull request ever opened
(`open_pull_requests` those open now) and `contributors` the people who
committed, anonymous committers included, as GitHub's contributors list
counts them; all three are the whole repository, not Holt's sample.
`contributors` comes from one REST request per repository after the details
query and stays at its last value when that request fails. `languages` holds up to three, biggest first, `share` in
0..1. `homepage` is always an `http(s)` URL. `links` is where a newcomer
finds the rules and help, one per kind, in the order listed above: GitHub's
contributing guide, Discussions when the repository has them, then the docs and
chat rooms the README links to (never a badge's image); it is empty until the
details are read again, and every URL is `http(s)`. `latest_release` is GitHub's
latest release, null when there is none. `readme` is the top of the
repository's Markdown README (`README.md` or `readme.md`; a `.rst` one is
left out), at most about 6,000 characters, cut at a blank line and never inside
a code block, for the report's README section. It is untrusted text: render it
as Markdown without raw HTML, and open its links only when they are `http(s)`.
Nothing in it feeds the verdict. The public extension proxy passes it on.
`top_contributors` is the repository's most active committers in GitHub's own
order (most commits to the default branch first), at most ten, bots left out:
one REST request per repository after the details query, then one GraphQL
query per hundred people for their profile `name` (null when they haven't set
one, or when that query fails). `url` is always a `https://github.com/` profile
and `avatar_url` an `https` image. It is empty until the details are read
again, and keeps its last value when GitHub doesn't answer. It is GitHub's
public list, shown as GitHub orders it: Holt never ranks people.

### Engine version and `outdated`

Every stored report records the engine version that made it
(`ENGINE_VERSION` in `src/holt/engine_version.py`, bumped whenever the verdict
rules or the report's shape change; reports from before it was recorded count
as older). A report from an older version is never a cache hit: `POST
/v1/analyses` runs a fresh check, finds screen again, and Discover,
recommendations and My Contributions leave it out until it is redone. The
same goes for cached `/v1/find` results.

`outdated` (boolean) is filled only by `GET /v1/reports/{owner}/{repo}`, like
`holt_users`, and is never stored: `true` when an older engine made the report
returned. That endpoint still returns it (never a 404), so a client can fall
back to it; the web report page runs a fresh check instead and shows the old
report only if that check fails. The public extension proxy passes it on
(see below).

Every evidence item MUST have a clickable `url`.

In `stats`, an outsider is anyone not on the project's team. The team is the
repository's OWNER, MEMBER and COLLABORATOR accounts on GitHub, plus anyone the
sample shows merging or closing someone else's pull request, approving or
requesting changes on 3 or more other people's, or (in a project that labels
outside work, like PyTorch's "open source") never getting that label.
Returning outsiders count.
`first_time_merged_authors` is the number of those who were new to this repo
(nothing of theirs merged here before) and got a pull request merged. Reports
cached from evidence without GitHub's association use the earlier rule: an
outsider had nothing merged earlier in the sample.

`stats` counts are over **decided** newcomer pull requests: ones opened more
than 14 days (the settle window) before the report, whatever happened to them.
`outsider_attempts` is that decided total, so `outsider_merged /
outsider_attempts` and `no_reply / outsider_attempts` are the rates the verdict
was computed from. `no_reply` is still open, with no reply.
`still_open` (opened within the window, merged or not; in no rate; reports
cached before 30 Sep 2026 counted only the open ones) and `closed_silently` (closed by
a person with no reply, usually maintainers clearing out spam; not in `no_reply`) are shown
beside them; both are 0 on reports cached before they existed. `closed_by_bot`
(closed with no reply by a bot, soon after opening or later) and `withdrawn`
(closed by the person who opened it) are decided attempts that weren't merged,
in neither `no_reply` nor `closed_silently`; 0 on reports from before engine 6,
where they are inside `closed_silently`. Drafts and pull requests labelled or
retitled as spam or invalid are in no count.
`landing` and `never_landed` count the same decided pull requests, so every
number on a report is over one set.

`sample` is what the counts were read from: every pull request read, when the
oldest and newest were opened, and how many came from the team or from bots
(left out of every count). Null on reports cached before it existed. `asks` is
what the project asks of a contributor, where Holt could read it, blocking ones
first: `ticket_first` (the bot that closed outside pull requests says they need
a ticket in the project's tracker; `link` is the tracker it names),
`no_ai_prs` (outside pull requests closed and labelled or retitled as AI, or a
written rule against AI-written ones), `ok_to_test` and `sig_team` (most
outside pull requests carry `needs-ok-to-test`/`ok-to-test`, or a `sig/…`
label), `cla` (a CLA bot commented on outside pull requests), `dco` or
`issue_first` (CONTRIBUTING says so in as many words), `ai_disclosure` (a
written rule, or a closing bot, asks you to say whether you used AI; never
beside `no_ai_prs`), `duplicates` (5+ outside pull requests closed as
duplicates), `stale_bot` (a bot closes quiet pull requests: read from
actions/stale or probot's `.github/stale.yml` at the commit the report read,
`url` the config file and `days` its quiet days before a close; or, with no
config found, 2+ outside pull requests closed later by a bot with no reply,
`url` the newest and `days` null). `url` is where it was read; `link` is null except on
`ticket_first`; `days` is null except on `stale_bot`. An empty list means nothing was found, not that nothing is
asked. Neither affects the verdict. `next_step` carries one sentence per ask
under Worth your time, Long shot and Not enough evidence.

**`stats.timing`: how long it takes here (engine 7).** Facts for the reader and for My PRs, never read by the verdict. Null on
reports from before engine 7 (and on readings of the frozen benchmark); each
field is null under its minimum. All waits are measured from when a pull
request was opened.

- **First reply**: `first_reply_half_hours` and `first_reply_slow_hours` are
  the waits by which half, and 8 in 10, of the settled outside pull requests
  (opened 14+ days before the report, the ones `stats` counts) had an answer:
  a reply from the team, or a merge. One still open with no answer counts as
  not answered; one closed with no answer stopped waiting and leaves every
  longer wait. Null when fewer than 8 were answered, or when fewer than half
  (8 in 10) ever were. `stats.median_first_response_hours` (the typical wait,
  over the ones that got a reply) is unchanged.
- **Merges** come from a cohort nobody is still waiting on: outside pull
  requests opened 60 to 240 days before the report, so each had at least 60
  days to land. `merged_within_{3,7,14,30,60}_days` are the shares merged
  within that many days (open and closed-unmerged ones count as not merged);
  `merge_half_days` is the wait by which half were merged;
  `merge_typical_days` and `merge_slow_days` are the median and the 90th
  percentile among the merged ones. `merge_cohort_prs` and
  `merge_cohort_merged` are how many they are over, and `merge_cohort_from` /
  `merge_cohort_to` (dates) when the first and last were opened. On a busy
  repository the cohort is the newest 100 of the window plus the newest 100 of
  each older third of it (one light search, up to 3 GitHub points); a quieter
  one's own sample covers it. Outside means not on the team the sample shows,
and not anyone who merged a pull request in the cohort (merging takes write
access; staff often read as CONTRIBUTOR). Minimums: 8 outside pull requests for any
  merge number, 8 merges for `merge_slow_days`. All null when most outside
  work lands off GitHub's merge button (Gerrit, a merge bot, an internal
  sync): GitHub's merge time isn't the project's.
- **Rhythm**: `merges_in_bursts` is true when, over the last 26 weeks, there
  were 8+ outside merges, under 30% of weeks had one, and the busiest 4 weeks
  held 60%+ of them; false for a steadier flow; null when the sample doesn't
  reach back 26 weeks or has fewer merges. `last_outside_merge` is the date of
  the newest outside merge in the sample.
- **Stale bot**: `stale_bot` and `stale_close_days` as in the `stale_bot` ask
  (null days when only its closes were seen).

`how_long` is the block the report shows for it, derived from `stats` like
`counted`: up to four `{topic, text}` lines, in order `first reply`
("Typically 14 hours. Most get one within 3 days.", or "About half get one
within 2 days."), `merged` ("About half within a week, most within a month."),
`rhythm` (only when `merges_in_bursts`), and `closed if quiet` (the stale
bot). Empty when nothing cleared its minimum. Render the lines as given.

My PRs reads `stats.timing` through the report join (`verdict.timing` in My
Contributions), so it can say "Day 9, no reply yet. Most get one within 3 days
here." without another GitHub read.

`headline`, `tone`, `verdict_line`, `numbers_line`, `first_timer_line`,
`next_step`, `stat_line`, `counted`, `how_long` and `odds` are derived by the server from
`verdict`, `stats`, `sample`, `landing`, `asks` and
`decided_by`/`rule_codes`, every time a report is
served (so cached reports pick up wording changes). Every surface (web, OG
images, the extension) shows these fields and never works them out itself, so
they cannot disagree with each other or with the verdict:

- `tone` follows the verdict: `viable` → `good`, `long_shot` → `warn`,
  `not_viable` → `bad`, `insufficient_evidence`, `personal` and `catalogue`
  → `neutral`. (Before engine 4 `insufficient_evidence` was `warn`; `tone` is
  derived, so cached reports serve the new one.)
- `long_shot` ("Long shot"): outside work does get merged, but a given pull
  request probably won't be: fewer than 3 in 10 people getting their first
  pull request merged (from 8 people; engine 5), fewer than 1 in 10 merged, more than half never
  answered, a typical first reply over 3 weeks, or only one person's work
  merged among 20+ attempts. `personal` ("Personal project"): someone's own
  project or a small team's (a hackathon entry, coursework), with nothing from
  outside ever merged; Discover, Find and picks never list it. `catalogue`
  ("A list, not code"; engine 5): a list or a catalogue of entries, like
  links or package manifests, where a merged entry isn't code work (and
  whose merge odds aren't what the answer is about). Before engine 5 these were `not_viable`. All three come only from
  live readings.
- `verdict_line` never oversells: "Worth your time" with many unanswered pull
  requests says so. Under every other verdict it is the sentence of the rule
  that decided it (under "Long shot", the first of its reasons), never a
  catch-all.
- The top of a report is three lines, in order: `headline` + `verdict_line`
  (the verdict and one reason, without the counts), `numbers_line` (the
  counts with the dates they cover, e.g. "Of 120 pull requests from outside
  contributors (3 Jun – 26 Sep 2026), 22 were merged (18%). When a maintainer
  replied, it was typically within 6 hours. 25% sat open with no reply."), and
  `next_step` (where outside work lands, what the project asks, or where to go
  instead). `first_timer_line` is null when nobody outside tried.
- The rule that decided the verdict is the last `decided_by` line whose code
  is not informational (`awaiting_reply`, `landed_off_button`,
  `package_updates`, `kind_contested`, `kind_uncited`, `sample_period`,
  `dormant`, `excluded`, `still_open`, `closed_silently`, `closed_by_bot`,
  `closed_stale`, `withdrawn`, `too_old`).
- `counted` is "How this was counted": the sample and its dates, the team and
  how it was worked out, bots, each informational `decided_by` line, the
  rules that decided, and the fixed rule itself. Topics are plain English and
  may change; render them as given.
- `stat_line` is null when nobody outside tried. The extension chip shows it.
- `odds` is non-null only when the verdict is `viable` (and anyone tried): the
  worse of the merge rate (good ≥ 12%, fair ≥ 5%) and the no-reply rate (good
  ≤ 25%, fair ≤ 50%); its `text` names the weak part. The other verdicts are
  the answer on their own.
- `rule_codes` is `[]` on reports cached before it existed. Codes include
  `archived`, `prs_closed` (GitHub's settings switch pull requests off or
  limit them to collaborators; decides alone, like `archived`), `closed_kind`, `non_software_kind`, `no_attempts`, `ignored`,
  `merges`, `rubber_stamp`, `long_odds` (under 5% of outside pull requests
  merged, from 20 decided), `replies_no_merges` (20+ decided, most answered,
  none merged), `inactive` (nothing merged or pushed in 90 days; decides alone),
  `personal` (decides alone), `catalogue_shape` (the catalogue answer's
  reason), the Long shot reasons `few_newcomers_merged`, `few_merged`,
  `mostly_silent`, `slow_replies`, `one_merge`, `one_person`,
  `slow`, `too_few_attempts`, `few_merges`, `few_people`,
  `elsewhere` (a mirror or a fork; decides alone, like `archived`),
  `landed_off_button` (says how many merges GitHub shows as closed because
  they landed another way; never decides); new ones may appear. These never
  decide and come before the deciding rule: `sample_period` (the dates the
  sample's pull requests were opened; first on every live report), `dormant`
  (nothing merged in 90 days), `excluded` (drafts and spam left out),
  `too_old` (opened more than a year ago, left out),
  `still_open`, `closed_silently`, `closed_by_bot` (closed by a bot within
  three days of opening), `closed_stale` (closed later by a bot, with no
  reply), `withdrawn` (closed by its author), `slow_note` (under "Worth your time": the
  typical first reply takes longer than `days`; `verdict_line` ends with
  it; comes after the merge count). `awaiting_reply` appears only on reports
  cached before `still_open` replaced it.

`days` is the reader's time budget (1–90, the web offers 7, 14 and 30). Since
30 Sep 2026 a rules report's verdict doesn't depend on it: replies slower
than the budget add the `slow_note` line under "Worth your time", or a `slow`
line beside the reason under "Not enough evidence". Such reports carry
`budget_independent: true`, and the server answers another budget from them.
AI reports and older cached ones carry `false` and are only served for the
`days` they were made for.

New fields are added with a default, so older cached reports stay valid.

`kind` is a machine key: in AI mode the engine field the claim is about
(`onboarding`, `outsider_posture`, `repo_kind`, …) or `outcome` for what
happened on one pull request (`value` e.g. `merged_after_review`, with the
maintainer's words in `quote`). Rules mode has no model claims; it lists the
newest first-timer pull requests behind the counts instead, as
`kind: "outsider_pr"`, `value: "merged" | "no_reply"`.

## Endpoints

### `GET /health` → `{"ok": true, "version": "…"}` (no internal key needed)
503 with `{"ok": false, "database": false, …}` when the database doesn't
answer within 1.5 s. It asks on a connection of its own, so it answers while
the server is busy.

### `POST /v1/analyses`
Body: `{"repo": "owner/repo", "mode": "rules"|"ai", "days": 7, "refresh": false}`
- Model choice is server configuration (`OPENROUTER_MODEL`); a `model` field in
  the request is ignored. It is accepted (not a 400) for older clients, and it
  never reaches the engine, the job or the cache key.
- Returns `200 {"status":"done","report":Report}` immediately when a cached
  report exists (same repo/mode/days, younger than 24h, made by the current
  engine version) and `refresh` is false.
  For `mode:"rules"`, a report younger than 24h for **another** `days` counts
  too when it is `budget_independent`: it is served for the asked `days` with
  its reply-time note redone, and nothing is read from GitHub.
- Otherwise `202 {"status":"queued","job_id":"…"}`.
- `mode:"rules"` is free and allowed anonymously (rate-limited per IP).
- `mode:"ai"` requires `X-Holt-User` (else `needs_key`) and a server model key
  (else `ai_unavailable`, checked first, so nothing is spent or queued). A new
  job is charged for the `ai_report` feature (see Credits and plans below; else
  `quota_exceeded`); a cached report or joining a running job costs nothing. A
  job that fails gives back what it was charged, to the pool it came from.

### `GET /v1/analyses/{job_id}` → `{"status":"queued"|"running"|"done"|"error", "stage": "Reading pull requests", "progress": 0.4, "report": Report|null, "error": Error|null}`

### `GET /v1/analyses/{job_id}/events` — Server-Sent Events
Events: `stage` `{"stage": "…", "progress": 0.0–1.0}`, then exactly one of
`done` `{"report": Report}` or `error` `{"error": Error}`. `stage` strings are
plain English ("Fetching pull requests", "Reading threads", "Checking evidence",
"Writing the report"). While the job waits to start, `stage` events also carry
`"queue_position": n` (1 = next to start) with a matching stage such as
"In the queue: 3 checks ahead of yours", sent again each time the queue moves.
The same applies to `/v1/find/{job_id}/events`. A job that runs past its time
limit ends with `error` code `upstream` and a "took too long" message.

### `GET /v1/reports?limit=500` (internal key, like other reads)
The latest 7-day rules report per repository, newest first, for sitemaps:
`{"reports": [{"repo": "owner/repo", "mode": "rules", "generated_at": "…",
"verdict": "viable"}]}`. `limit` 1–5000, default 500.

### `GET /v1/reports/{owner}/{repo}?mode=rules|ai&days=7`
Latest cached report or 404 `not_found`. With `mode=rules` and no fresh
report for this `days`, a fresh `budget_independent` one made for another
`days` is served for this one (as for `POST /v1/analyses`). `outdated: true`
when an older engine version made it (see "Engine version and `outdated`"). Public via the BFF: no user needed
(used for shareable pages and OG images), but it still requires the internal
key like every `/v1` route.

The free report (`mode=rules`) is the same for every reader, so the server
keeps it as sent, in the process, for up to 60 seconds. A report, the repo's
details or Holt users' numbers written by the same process show on the next
read; written by another process (a warm pass run from the command line),
within those 60 seconds. `GET /v1/discover` and the index part of `POST
/v1/find` are kept the same way. Nothing that depends on who is asking is
kept. This endpoint and `GET /v1/discover` send an `ETag` and answer `304`
with no body to a matching `If-None-Match`.

### `GET /v1/repos/{owner}/{repo}/starter-issues?limit=20`
Open issues in this repo that suit a newcomer and nobody has taken, best
first (issues nobody is on before the rest; with 3 or more of those, the ones
someone is on are left out):
`{"repo": "…", "issues": [StarterIssue]}`. Cached per repository for 1 hour;
a cache hit costs no GitHub call and no rate limit. A miss counts against the
**read** limit, never the work limit (see Rate limits).

### `GET /v1/repos/search?q=excalidraw`
Which repository does a bare name mean? Public repositories whose *name*
matches `q`, most starred first, at most five, forks left out:
`{"query": "excalidraw", "results": [{"repo": "excalidraw/excalidraw", "description": "…"|null, "stars": 90000}]}`.
`q` is a name, 1–60 characters of letters, digits, `.`, `_`, `-` and single
spaces (it is lower-cased; anything else, such as `owner/name`, is
`invalid_request`). No match is an empty `results`, not an error. It reads
GitHub's REST search (a budget of its own, apart from the GraphQL points
reports use) and nothing is stored; an answer is kept in memory for 10
minutes, and only a miss counts against the **read** limit. GitHub
rate-limiting it answers `rate_limited`. The compare page uses it to turn a typed name
into a repo; pick the result whose name equals `q` first, else the top one.

### `POST /v1/find`
Body: `{"languages": ["python"], "topics": [], "days": 7, "hacktoberfest": true, "limit": 20}`
Returns `{"results": [ { "repo": "owner/repo", "headline": "…", "tone": "good", "verdict": "…",
"description": "string | null", "language": "string | null", "languages": ["…"],
"stars": 123 | null, "open_issues": 57 | null, "pull_requests": 4100 | null,
"open_pull_requests": 12 | null, "contributors": 812 | null,
"stats": {…subset}, "issues": [StarterIssue] } ]}`, only repos whose rules
verdict is `viable`. `description`, `language`, `stars` and the four counts (as
on Discover) come from `repo_meta`, the same details Discover shows; no GitHub
call. They are null for a repo the warm pass hasn't read yet (the warm pass
reads every repo in a search from the last day). `stats` leaves out counts it
doesn't have rather than sending null; when a fresh 7-day report counted the
same pull requests, `closed_silently`, `closed_by_bot`, `withdrawn` and
`still_open` come from it, so the odds bar is drawn as on Discover, and without
them the bar has one "weren't merged" segment.

Results come from two places, in this order, with no repo twice:

1. **Holt's index**: every repo whose latest 7-day rules report (current
   engine) says "Worth your time", as Discover's welcoming board ranks them
   (best odds, merged share, reply time, sample). Matched through `repo_meta`:
   any picked language as the main language or a real second share
   (`languages`), any picked topic, the `hacktoberfest` topic when
   `hacktoberfest` is true; archived repos and forks left out (a repo closed
   to outside pull requests is left out by its verdict). The typical first
   reply must fit in `days`. Only repos with starter issues Holt already knows
   (read within the last 72 hours; up to 5, best first) are listed, those
   with an issue nobody is on before those whose issues are all taken. Read
   from the database: no GitHub call, no rate limit.
2. **The GitHub search**: repos found by searching GitHub for these filters and
   screened with the rules, ordered by starter-issue quality.

- **Search cached** (same search, finished within 6 hours): `200
  {"status": "done", "results": [...], "complete": true}` at once, with no rate
  limit: the index as it is now, then the cached search. "Same search" means
  the same languages and topics (order, case and duplicates ignored),
  `hacktoberfest` and `days`; `limit` is a slice of one answer (searches are
  computed for at least 20).
- **Already running** for someone else: `202 {"status": "queued", "job_id":
  "…", "results": [...]}` with that search's `job_id`, also free. `results` is
  the index part, to show while the search runs.
- Otherwise the same `202` for a new search, which costs one unit of the work
  bucket; poll or stream under `/v1/find/{job_id}` like analyses. Polling a
  find job returns `results` instead of `report`; the SSE `done` event carries
  `{"results": [...]}`, the index then the search. While it runs, the search
  also reads the starter issues of the first few index matches that have none
  known, so they can join the answer, and reads again those of the first 12
  listed that were read more than 6 hours ago (one GitHub query each), so the
  issues shown first aren't ones closed or taken since. If the search fails (an `error` event),
  the index part from the `202` is still the answer to show.
- **Over the work limit** with index results: `200 {"status": "done",
  "results": [...], "complete": false}`, the index part only (no search ran
  for this caller). Don't keep it for other callers. With no index results the
  usual `429`.

### `POST /v1/find/index`
Body: `{"languages": ["python"], "topics": [], "days": 7, "hacktoberfest": true, "limit": 24, "cursor": "…" | null}`
The index part of a find (1. above) and nothing else, in parts, for a list
that loads more as it is scrolled: `{"results": [FindResult], "total": 87,
"next": "…" | null}`. The same repos in the same order as the index part of
`POST /v1/find` with these filters; `limit` 1–100, default 24; `next` goes
back as `cursor` (as on Discover, below) and is `null` at the end. It never
starts or waits for a search, calls GitHub, or counts against a limit, and
the search's own repos are not in it.

StarterIssue:
```jsonc
{ "number": 123, "title": "…", "url": "https://github.com/o/r/issues/123",
  "labels": ["good first issue"], "created_at": "…", "comments": 2,
  "why": ["Labelled good first issue", "Touches docs/, where 8 of 10 outsider PRs were merged"],
  "people": 0,               // distinct people already on it; null from an older cache
  "open_prs": 0,             // its open pull requests; null from an older cache
  "on_it": "Nobody on it yet", // those two in words; null when they are
  "beginner": true,          // labelled for first-timers ("good first issue" and its spellings)
  "areas": ["docs"] }        // which of code/docs/tests/design/translations it looks like
```
`people` counts distinct people with an open pull request that closes or
mentions the issue, a "can I work on this?" comment in the last 45 days, or an
assignment that went quiet. `on_it` is the line the web and `holt start` both
show: "Nobody on it yet", "1 open pull request", "2 people already on it" or
"2 people already on it, 1 open pull request". Issues already solved (a merged
linked pull request), taken (an assignee active in the last 45 days, or a
"taken" label), or not tasks at all (calls for maintainers, tracking and meta
issues, epics) are never listed. Starter issues cached before these fields
existed are fetched again rather than served. An issue is **taken** when
`people` or `open_prs` is above 0. Wherever issues are sent (here, find
results, Discover cards) the ones nobody is on come first, and taken ones are
left out when 3 or more are free; this is applied on every send, so cached
lists follow it too. A list whose issues are all taken is still sent: the web
says "No free starter issue right now" over it.
`beginner` and `areas` are worked out from the labels and title every time an
issue is sent, so cached issues have them too. The web uses them with a
profile (see Profile); they never change a verdict or which repos are listed.

### `GET /v1/discover?sort=welcoming|stars|trending&language=python&topic=cli&hacktoberfest=true&limit=24&cursor=…`
Browse the repositories Holt has checked, built only from each repo's latest
7-day **rules** report (never the model) and ranking repositories, never
people. Reads only the database: no GitHub call and no rate limit.

- `sort=welcoming` (default; the "Most welcoming <language> repos" boards):
  only repos whose verdict is `viable`, best odds first (good, fair, long),
  then the share of outside pull requests merged (a small sample is pulled
  toward a typical share, so 6 of 8 doesn't outrank 60 of 105), the median
  reply time and how many outsiders tried.
- `sort=stars`: GitHub stars, every verdict but `personal`.
- `sort=trending`: people who asked for the repo's report on Holt in the last
  7 days (each person counted once per UTC day), only repos with at least
  `trending_min` (5). The counts (`checked_this_week` too) are up to a minute
  old.
- `language` and `topic` filter case-insensitively (`c++`, `Python`). `limit`
  1–100, default 24.
- A board comes in parts. Each answer has `total` (every repo on the board
  under this sort and these filters) and `next`: send it back as `cursor`,
  with the same sort and filters, for the part after this one; `null` at the
  end. Without `cursor` the answer is the first `limit` repos, as before. A
  cursor names the last repo already sent, so when the board changes between
  two parts the next one still starts right after it: no repo twice, none
  skipped below it. A cursor Discover didn't give out is `400
  invalid_request`. The server keeps each ranked board for up to 60 seconds
  and cuts every part from it; a part already built costs no database read.
- `hacktoberfest=true` keeps only repos tagged with the `hacktoberfest` GitHub
  topic (how a project takes part; a Hacktoberfest find searches the same
  topic) that aren't archived, under any sort and alongside the other filters.
  `languages` then counts those repos only. For a "Hacktoberfest" row use
  `?hacktoberfest=true&limit=20`: "Worth your time" repos, best first; add
  `sort=stars` to include every verdict. Reads only the database, like the rest
  of Discover, so it is as fast as the boards.

```jsonc
{ "sort": "welcoming", "language": "Python", "topic": null, "hacktoberfest": false,
  "trending_min": 5, "total": 312, "next": "MjQ6b3duZXIvcmVwbw" | null,
  "repos": [ { "repo": "owner/repo", "verdict": "viable", "headline": "Worth your time",
    "tone": "good", "reason": "…the report's verdict_line…", "stats": Stats,
    "standout": "A first reply typically comes within 3 hours."|null,  // see below
    "description": "…"|null, "language": "Python"|null, "stars": 123|null,
    "open_issues": 57|null, "pull_requests": 4100|null,
    "open_pull_requests": 12|null, "contributors": 812|null,  // as in `about`
    "topics": ["cli"], "pushed_at": "…"|null,
    "checked_this_week": 12|null,     // null below trending_min
    "generated_at": "…",
    "issues": [StarterIssue] } ],     // cached only; [] when none, see below
  "languages": [ { "name": "Python", "repos": 40 } ] }  // filter chips, most repos first
```

`standout` is what a card shows in place of `reason` when the reason is the
one every "Worth your time" repo shares ("Outside contributors get real
replies here, and their work gets merged."): the number where this repo
stands best among the repos on this board (this sort and these filters, the
whole board, not the part), as a sentence. The numbers are the first reply
time, the share merged, first-timers merged, the typical days to merge and
the date of the last outside merge, all from `stats`. A repo in the better
half of the board on none of them gets the reply time. `null` when the reason
already says something of its own, when the report has none of the numbers,
and on a card sent anywhere but a board.

`issues` are the repo's starter issues as `GET /v1/repos/{o}/{r}/starter-issues`
(or the warm pass) last cached them (at most 5, nobody-on-it first), when that
was within 72 hours and by the current starter rules; otherwise `[]`. Taken
issues are left out when 3 or more are free, as everywhere. Discover
never reads GitHub for them.

`description`, `language`, `stars`, the four counts, `topics` (all of them,
up to GitHub's 20) and `pushed_at` come from `repo_meta`, read from GitHub right after a
repository's report is stored (when it has none, or they are more than a day
old) and again once a day for every reported repository. A report job reads
its repo's details before it is announced (waiting at most 8 seconds), so a
report's `about` is the same in the job's `done` event, in `GET
/v1/analyses/{job_id}`, in a cached `200` from `POST /v1/analyses` and in `GET
/v1/reports/{owner}/{repo}`. The read is best effort: if GitHub is slow it
happens a few seconds after the report instead (so `about` can be null on the
report as announced), and if GitHub didn't answer, `about` stays null until
the next report or daily read.

### `GET /badge/{owner}/{repo}.svg` (no internal key; public; `Cache-Control: public, max-age=3600, stale-while-revalidate=86400`)
Shields-style SVG badge. Maintainers embed it in READMEs; it links back to the
report page at `{HOLT_WEB_URL}/{owner}/{repo}`. Uses the latest 7-day rules
report:
- `viable`: a positive, factual line in green from `stats`, e.g.
  "Holt | merges outsiders · replies in ~6h" ("merges outsiders" when
  `outsider_merged` > 0; the reply time when the median first reply is within
  72h; "worth your time" if neither).
- any other verdict (`long_shot`, `personal` and `catalogue` included): neutral grey
  "Holt | see report", never a red or amber verdict.
- no report yet: neutral grey "Holt | not checked yet".
- the report is from an older engine version: neutral grey "Holt | updating",
  never its old verdict, sent with `Cache-Control: public, max-age=300` so
  the new verdict shows soon.

When there is no report, or it is over 24h old or outdated, it shows what it
has and queues a rules check behind it. Badge-queued checks have their own rate
limits (per client IP and in total, separate from user limits), run at most
one at a time, and wait behind every user request.

### Account
- `GET /v1/me` → `{"plan": "free"|"…", "plan_expires_at": "…"|null, "credits": Credits}`.
  `plan` is the plan in force: `free` once a paid plan has lapsed.
- `GET /v1/me/credits` → `Credits`:
  `{"balance": 3, "free": 3, "purchased": 0, "can_claim": false, "next_claim_at": "…", "claim_every_days": 7, "ai_available": true}`.
  `balance` is every credit the user can spend (`free` + `purchased`); `free` is
  welcome, weekly and gifted credits, `purchased` credits an admin granted (or
  a credit pack bought before passes). `next_claim_at` is when the weekly claim
  opens (`can_claim` is true once it has passed). `ai_available` is false while
  the server has no model key.
- `GET /v1/me/entitlements` → `{"plan": "free", "plan_expires_at": null, "features": [Access]}`,
  one `Access` per paid feature in the pricing catalogue:
  `{"feature": "playbook", "name": "Contribution playbook", "allowed": false, "via": null, "cost": 1, "left_this_month": null, "code": "quota_exceeded", "message": "…", "left": null}`.
  `via` is how a use would be paid for now (`plan` or `credits`), `cost` the
  credits one use takes (0 when the plan covers it), `left_this_month` the
  plan's monthly allowance left (null when unlimited or none), `left` the
  plan's allowance left whether monthly or in all (the free merge plans; null
  when unlimited or none). When
  `allowed` is false, `code`/`message` are the error the paid request would get
  (`quota_exceeded` or `needs_plan`). Informational: the paid route decides
  again, atomically, when it charges.
- `POST /v1/me/credits/claim` → `Credits` with one more credit, or 409
  `claim_not_ready` (the message says the date).
- `GET /v1/me/history?limit=50` → recent analyses by this user:
  `{"items": [{"job_id", "repo", "mode", "days", "status", "verdict", "headline", "tone", "created_at"}], "cards": [...]}`
  (`verdict`/`headline`/`tone` are null until the job is done). `cards` holds
  Holt's current card (a Discover repo card, from the latest 7-day rules
  report) for each repo in `items` that has one, in no order; Your repos
  shows their numbers.

`/v1/me*` without `X-Holt-User` → 401 `unauthorized`. Free AI credits: every
signed-in user gets `HOLT_SIGNUP_AI_CREDITS` once, the first time the server
sees them (users from before credits get them on their next request), then can
claim one more whenever `HOLT_CLAIM_EVERY_DAYS` (7) have passed since the last
claim; the welcome grant starts that clock. Claims don't accumulate: at most one
is ever due. Spending, claiming and refunds are atomic on the server.
`HOLT_SIGNUP_AI_CREDITS` is 0 now that the free merge plans replace them: a new
account gets no AI credits and nothing to claim (`next_claim_at` null), and
accounts welcomed before keep their credits and their weekly claim.

#### Credits, plans and passes

Payments are off: nothing is on sale. What exists is the model they plug
into, all on the server, never taken from the client, and a checkout for
passes that stays switched off (below):

- **Features** (`ai_report`, `playbook`, `preflight`, `guidance`,
  `merge_plan`, `pr_watch`, `repo_watch`, `issue_watch`)
  and what one use costs in credits, **plans** (`free`, `pro`: what each
  covers, unlimited, N uses per UTC month, or N uses in all) and **passes** (days of Pro for
  one payment, with INR and USD prices) are defined in a JSON catalogue
  (`server/holt_server/pricing.json`, or `HOLT_PRICING_FILE`).
- The free plan covers 3 merge plans in all (every account, new or old);
  Pro covers 30 a month while a pass is active. Pro's uses don't touch the
  free three.
- A use is paid for by the plan when it covers the feature (free), else with
  the feature's credits: free credits first when the feature accepts them,
  then purchased credits, soonest-expiring first. A feature with no credit
  price needs a plan (`needs_plan`).
- Two credit pools, one ledger: free credits (welcome, weekly claim, gifts)
  and purchased credits (admin grants, and credit packs bought before passes;
  they never expire, or expire when the grant says). Every change is a ledger
  row saying which pool.
- Admins change credits and plans with a CLI (`python -m holt_server.credits`,
  server/README.md), not over HTTP.

#### Passes (checkout)

A pass is one payment for a fixed number of days of Pro (`pro_1m` 30 days,
`pro_3m` 90, `pro_12m` 365). It never renews. Razorpay, INR. **Switched
off** unless the server has `HOLT_PAYMENTS_ENABLED=1` and its Razorpay keys,
and a pass in the catalogue has `on_sale: true` and an INR price (outside
production, `HOLT_PASSES_ON_SALE=1` puts every pass on sale: staging, in
Razorpay test mode). While off,
`GET /v1/passes` offers nothing and `POST /v1/me/orders` answers 403
`payments_off`. The price and the days always come from the server's
catalogue.

- `GET /v1/passes` (internal key; no user needed) → `{"on_sale": false, "passes": [Pass], "features": [PassFeature]}`,
  `Pass`: `{"id": "pro_1m", "name": "1 month", "days": 30, "amount": 9900, "currency": "INR"}`
  (`amount` in paise), `PassFeature`: `{"id": "merge_plan", "name": "Merge plan", "per_month": 30, "unlimited": false}`
  (what Pro unlocks; every pass gives the same Pro). `on_sale` is false and
  both lists empty while payments are off or no pass is on sale.
- `POST /v1/me/orders {"pass": "pro_1m"}` → `Checkout`:
  `{"order_id", "provider": "razorpay", "key_id", "provider_order_id", "amount", "currency", "name", "description", "item", "days"}`,
  everything Razorpay Checkout needs (`key_id` is the public key id; `item` is
  the pass id). Any other field in the body is ignored. 400
  `invalid_request` for a pass not on sale, 403 `payments_off`, 502
  `upstream` when Razorpay fails. Counts against the user's hourly work limit.
- `POST /v1/me/orders/confirm {"razorpay_order_id", "razorpay_payment_id", "razorpay_signature"}`
  (exactly what Checkout's success handler receives) →
  `{"order": Order, "plan": "pro", "plan_expires_at": "…" | null}` (the plan
  in force afterwards). The server checks the signature, then asks Razorpay
  for the payment, and gives the pass only when the payment is captured (it
  captures an authorized one) for the order's exact amount and currency.
  `order.status` is `paid`, or still `created` while Razorpay is processing
  (the webhook finishes it; poll `GET /v1/me/orders`), or `held` when the
  amount didn't match (nothing given; a person checks it). 400
  `payment_unconfirmed` for a bad signature, 404 for an order that isn't this
  user's. Safe to repeat.
- `GET /v1/me/orders?limit=50` → `{"orders": [Order]}`, newest first, the
  purchase history. `Order`: `{"id", "item", "name", "days", "amount", "currency", "status", "created_at", "paid_at"}`,
  `item` the pass id (or a credit pack's, for purchases from before passes,
  with `days` null), `status` one of `paid`, `failed` (the payment was
  declined), `held`. Checkouts that were opened and never paid are left out.
- `POST /v1/payments/razorpay/webhook` (internal key; no user). `web/` serves
  Razorpay's webhook URL (`/api/payments/razorpay/webhook`) and forwards the
  request body byte for byte with its `X-Razorpay-Signature` header. The
  server verifies that signature (`RAZORPAY_WEBHOOK_SECRET`) before reading the
  body: 400 `payment_unconfirmed` if it doesn't match. Signed events answer 200
  `{"ok": true, "result": "paid"|"already_paid"|"held"|"failed"|"pending"|"unknown_order"|"ignored"}`
  (the result is for logs). Handled: `payment.authorized` (captured),
  `payment.captured` and `order.paid` (given), `payment.failed`. Anything
  else, including `subscription.*`, is `ignored`.

What a pass does (`Me.plan`, `Me.plan_expires_at`): the plan becomes `pro`
for the pass's days, counted from when the user's current Pro ends if it
hasn't yet (so passes stack), else from the payment. Pro that an admin gave
with no end stays as it is. A pass is given once per order, whichever of the
confirm call and the webhooks arrives first, however often they repeat:
marking the order paid and extending the plan happen in one transaction, and a
payment id can pay only one order. With payments switched off, orders that
already exist are still confirmed, so someone who paid just before the switch
gets their pass.

### Admin (read-only)

Internal key plus an `X-Holt-User` listed in `HOLT_ADMIN_USERS`; anyone else
gets 404 `not_found`. There is no admin UI.

- `GET /v1/admin/users?limit=100&plan=pro` → `{"users": [AdminUserSummary]}`,
  newest first: `{"id", "plan", "effective_plan", "plan_expires_at", "free", "purchased", "created_at"}`.
- `GET /v1/admin/users/{user_id}?ledger_limit=200` → `AdminUser`: the summary
  plus `lots` (purchased credits), `ledger` (newest first: kind, source,
  amount, lot, feature, job, reason, actor), `plan_history`, `plan_usage`
  (uses per feature and month) and `access` (an `Access` per feature). 404
  for an unknown user.
- `GET /v1/admin/pricing` → the catalogue this server loaded.
- `GET /v1/admin/ai-spend` → `AdminAiSpend`: `{"budget_usd", "spent_usd",
  "held_usd", "runs", "running", "line"}`, this environment's AI spend against
  `HOLT_AI_BUDGET_USD` (0 = AI off); `line` is `"AI spend: $0.23 of $1.00"`.

### Connect GitHub

Free and optional. `web/` sends the numeric GitHub account id from the user's
own Auth.js GitHub account (signed in with GitHub, or linked from the Connect
screen), never from user input. The server looks up the login with its own
token pool (`GET https://api.github.com/user/{id}`, public data); it never gets
the user's GitHub token. Stored in `github_connections` and `repo_views`.

`GitHubConnection` = `{"connected": true, "account": {"id": 583231, "login": "octocat",
"connected_at": "…", "adult_confirmed_at": "…", "stats_opt_out": false}}`, or
`{"connected": false, "account": null}`.

- `GET /v1/me/github` → `GitHubConnection`.
- `POST /v1/me/github` body `{"github_id": 583231, "adult_confirmed": true, "stats_opt_out": false}`
  → `GitHubConnection`. Connects, or updates the connection (the login is looked
  up again; `connected_at` is kept unless the GitHub account changes).
  `adult_confirmed` must be true (the user ticked "I'm 18 or older"; its time is
  stored), else 400 `invalid_request`. A GitHub id connected to another user →
  409 `invalid_request`. An id GitHub doesn't know → 400 `invalid_request`.
  GitHub trouble → `rate_limited` / `upstream`.
- `PATCH /v1/me/github` body `{"stats_opt_out": true}` → `GitHubConnection`. The
  "Don't include me in statistics" switch. 404 `not_found` when not connected.
- `DELETE /v1/me/github` → `{"connected": false, "account": null}`. Deletes the
  connection, every `repo_views` row and every fetched pull request (My
  Contributions) for the user.
- `POST /v1/me/activity` body `{"repo": "owner/name"}` → 204. `web/` sends it when
  a signed-in user opens a report page. Recorded (repo, first and last viewed,
  count) only while the user is connected; otherwise ignored. Bad repo → 400
  `invalid_repo`.

A connected user's public contributions may be counted, anonymously, in
cross-user repo statistics (the report's `holt_users`, shown only when 5+
people contribute) unless `stats_opt_out` is true. Turning it on (PATCH, or a
POST that changes it) or disconnecting takes them out of every repository's
numbers in the same request.

### Merging accounts

A person who signed in with GitHub once and with Google later has two
accounts. When they connect GitHub from the second, `web/` finds the GitHub
account is the first one's sign-in and offers to merge. `web/` asks for this
only while it holds proof of both accounts from the same browser: the session
of the account being kept, and a GitHub sign-in for exactly that GitHub id that
succeeded in the last 10 minutes. `from_user` is the owner of that GitHub
sign-in in `web/`'s own Auth.js tables, never user input; `web/` moves the
sign-in to the caller in the same step.

- `POST /v1/me/merge` body `{"from_user": "<user id>", "github_id": 583231}` → 204.
  Everything `from_user` has moves to the caller, in one transaction (all of
  it, or nothing), and `from_user`'s `users` row is deleted:
  - orders, credit lots and the credit ledger, plan events, analyses (the
    history), pre-flights, sent alert emails: all change owner;
  - saved repos, viewed repos, pull requests and their counting choices, muted
    pull requests, alerts, merge plans, playbooks, the sent-log of account
    emails, feedback: the union; where both have the same thing, the caller's
    stays;
  - the GitHub connection comes along (the caller has none yet);
  - profile, alert settings, account-email settings: the caller's; `from_user`'s
    only where the caller has none (with new unsubscribe links);
  - the plan that runs longer stays; credit balances add up; anything free takes
    the more-used value, so merging never hands it back: each allowance counter
    (`plan_usage`), the earlier `alerts_trial_ends_at`, the later weekly claim.

  Asked again after it worked, nothing is left to move: 204, no change. 400
  `invalid_request` when `from_user` is the caller. 409 `invalid_request`, with
  nothing moved, when `github_id` is connected to a third account, when either
  account is connected to a different GitHub account, or when the two can't be
  one (both have a running monthly plan from before passes).

### My Contributions

A connected user's public pull requests, each with Holt's verdict for its
repository. Read with the server's token pool from GitHub's public search
(`is:pr is:public author:<login> -user:<login>`, the last 365 days, at most
200, newest first; the user's own repositories and anything private are left
out, and so is every repository they help run: GitHub calls them its owner,
a member or a collaborator on any of their pull requests there, or they merged
one of their own). Fetched when GitHub is connected, again once a day in the
background (`HOLT_CONTRIBUTIONS_REFRESH_HOURS`, 24; 0 = off), and on refresh. Stored in
`contributions` and `contribution_syncs`; each fetch replaces the user's rows.
Nothing here starts an analysis.

A person can leave a repository out of their numbers (a friend's project, their
team's repo, a hackathon): its pull requests stay in the list with `counted:
false`, and `summary` counts only the rest. The choice is per repository, kept
in `contribution_choices` across fetches, and deleted on disconnect. Without a
choice, a repository Holt finds is the person's own or their team's project is
left out (`not_counted_because: "own_project"`); counting it again overrides
that. It changes only this page's numbers, not the product metric or any
repository's statistics.

`Contributions` =
```jsonc
{
  "login": "octocat",
  "fetched_at": "…",            // when GitHub was last read
  "next_refresh_at": "…" | null, // refresh works again from then; null = now
  "window_days": 365, "truncated": false, // true: GitHub had more than 200
  "summary": { "opened": 12, "merged": 6, "waiting": 3, "closed": 3,
               "landed_share": 0.5,  // merged / (merged + closed); null if none decided
               "found_via_holt": 2,
               "not_counted": 1 },   // pull requests left out of the numbers above
  "pull_requests": [
    { "repo": "pallets/flask", "number": 5432, "title": "…",
      "url": "https://github.com/pallets/flask/pull/5432",
      "state": "open" | "merged" | "closed", "draft": false,
      "created_at": "…", "closed_at": "…" | null, "merged_at": "…" | null,
      "verdict": { "verdict": "viable", "headline": "Worth your time", "tone": "good",
                   "checked_at": "…",
                   "first_reply_hours": 15.0 | null, // typical wait for an outside PR's first reply
                   "timing": { … } | null  // the report's `stats.timing` (engine 7), as is
                 } | null,   // latest cached 7-day rules report
      "found_via_holt": true,
      "counted": true,                  // in `summary`; all of a repo's PRs, or none
      "not_counted_because": null | "you" | "own_project",
      // Where an open one stands (below). "unknown" and nulls on merged and closed ones.
      "turn": "yours" | "theirs" | "unknown",
      "turn_at": "…" | null,           // when the turn last changed hands
      "first_reply_at": "…" | null,    // the project's first comment or review
      "last_activity_at": "…" | null,  // the newest push, comment or review by a person
      "review_decision": "approved" | "changes_requested" | "review_required" | null,
      "reply_by": "davidism" | null,   // who on the team spoke last after your last move
      "reply_kind": "changes" | "approved" | "reply" | null, // and what that was
      // PR watch (below). null when the person gets no alerts now, and on
      // merged, closed and uncounted ones.
      "watch": "on" | "muted" | null,
      "unread_alert": false }          // it has an alert the person hasn't opened
  ]
}
```

**Where an open pull request stands.** Right after the search, the open ones
are read again by node ID, 100 per query (`nodes(ids:)`): the review decision,
the first and last 5 comments and reviews, and the last commit. GitHub charges
1 point for up to 20 open pull requests (about 5 per 100), so a refresh costs
the search's 1–2 points plus 1. If that read fails, the list still refreshes
and each open pull request keeps its last known state (`unknown` the first
time).

- The **project's team** here: not the author, not automation (the engine's
  bot test), and someone GitHub calls an owner, member or collaborator, or who
  approved or asked for changes on this pull request. Another user's "+1" is
  activity, not a reply.
- `turn` is `yours` when someone on the team commented or reviewed after your
  last push or comment (asking for changes included); `theirs` when you acted
  last (opening it counts), or the team's last word was an approval; `unknown`
  when it couldn't be read. `turn_at` is the team's last word when it's
  yours, your last push or comment when it's theirs.
- `first_reply_at` is the team's first comment or review. `last_activity_at`
  is the newest push, comment or review by anyone but a bot.
- `reply_by` is the team member who spoke last after your last push or comment,
  and `reply_kind` what that was: `changes` (a review asking for changes; it
  stands until an approval, so a comment after it doesn't change it),
  `approved`, or `reply` (any other comment or review). Both null when you
  acted last.

PR watch alerts reuse these fields. My PRs words each open row from them and
`verdict.timing` (the web's `web/src/lib/home.ts`): "Day 9, no reply yet. Most
get one within 3 days here."

- `GET /v1/me/contributions` → `Contributions`. Reads GitHub only when the
  user has never been fetched (or their login changed); otherwise the stored
  list. Not connected → 404 `not_found`. GitHub trouble on that first read →
  `rate_limited` / `upstream`.
- `POST /v1/me/contributions/refresh` → `Contributions`. Reads GitHub again,
  unless the last read is under 15 minutes old: then the stored list comes back
  unchanged (200) with `next_refresh_at`. Reads that reach GitHub are also
  limited to 6 per user per hour (429 `rate_limited`), which only matters when
  GitHub keeps failing.
- `PUT /v1/me/contributions/repos/{owner}/{name}` body `{"counted": bool}` →
  `Contributions`: count that repository's pull requests, or leave them out.
  `DELETE` on the same path forgets the choice (back to the default). Only
  repositories in the person's list; anything else → 404 `not_found`. Not
  connected → 404.
- `found_via_holt`: the user opened the pull request within 30 days after
  opening that repository's report page on Holt while connected (`repo_views`
  keeps the first and the last view of each repository; a pull request within
  30 days after either counts). Only verifiable data; never self-reported.
- `GET /v1/metrics/contributions?since=YYYY-MM-DD` (internal key, no user) →
  `{"since": "" | "YYYY-MM-DD", "window_days": 30, "connected_users",
  "users_with_pull_requests", "users_with_pr_after_holt", "prs_after_holt",
  "prs_after_holt_merged"}`: counts only, over connected users who did not turn
  on `stats_opt_out`, of pull requests opened on or after `since` (default:
  all stored). Also `python -m holt_server.contributions metric [--since DATE]
  [--json]`.

### PR watch (alerts)

Holt watches a connected user's open pull requests and tells them, on the bell
and by email, when it's their turn, when one has waited longer than most do in
that repository, before a stale bot closes it, and when it is approved, merged
or closed. Rules only, no model; everything is read as the Holt GitHub App,
public data only. Stored in `alert_settings`, `watch_mutes`, `alerts` and
`alert_emails`; alerts are deleted after 90 days, and all of it when GitHub is
disconnected.

**Switched off by default.** With `HOLT_PR_WATCH` unset, nothing checks pull
requests or sends email, `access.state` is `unavailable` for everyone, and
turning alerts on answers 501 `not_implemented`. The web hides the feature then.

**Access.** `AlertAccess` = `{"state": "unavailable" | "off" | "trial" | "pro" | "ended", "until": "…" | null}`.

- `pro`: the plan in force covers the `pr_watch` feature. `until` is the plan's expiry (null: none).
- `trial`: the free taste, 14 days from the first time alerts are turned on (not from signup), once per account. `until` is when it ends.
- `ended`: the taste is over and no pass covers it. `until` is when it ended. Old alerts stay listed; none are made.
- `off`: never turned on (or a pass lapsed with the taste unused). Turning alerts on starts the taste.

**What's watched.** Every open pull request in My Contributions that counts
(not a repository left out of the numbers), unless its author muted it. Drafts
get replies, merges and closes, but no "past normal" or stale-bot alert.

**The alerts.** `kind` is one of:

| `kind` | When | `text` |
|---|---|---|
| `changes` | Someone on the team asked for changes after your last move. | Your turn. @reviewer asked for changes on click #2811. |
| `reply` | Someone on the team commented or reviewed after your last move. | Your turn. @reviewer replied on click #2811. |
| `approved` | A team member approved, or the review decision became approved. | Nice. @reviewer approved click #2811. |
| `late_reply` | No team reply yet, and the wait passed the repository's **slow** first reply (`timing.first_reply_slow_hours`, the wait within which 8 in 10 get one). Never the typical one. | Day 6 and still no reply on p5.js #7120. Most get one within 4 days here. |
| `late_merge` | There has been a reply, it's their turn, and the wait passed `timing.merge_slow_days`. | Day 20 on efcore #3310. Most merged PRs land within 2 weeks here. |
| `stale_soon` | The repository's stale bot has a known day count (`timing.stale_close_days`) and the pull request has been quiet for all but 5 of those days (and at least half of them). | It's been quiet for 25 days on free-programming-books #11020. The bot closes it at 30. |
| `merged` | It was merged. | kubernetes #128811 was merged. |
| `closed` | It was closed without merging. | moment #6120 was closed without merging. |

`text` is rendered by the server, so the bell and the extension say the same
thing; the emails phrase the same alert their own way. Without a name to give,
it says "A reviewer". The three waits
need the repository's current rules report; with no report, or numbers under
the engine's minimums, they don't fire. Each event alerts once. A "your turn"
fires again only when the team speaks again (a comment after a request for
changes that still stands reads as `reply`). `late_reply` and `late_merge` fire
once per pull request, and again only after the old alert is deleted at 90 days.

**How they're made.** A checker runs every 30 minutes (`HOLT_PR_WATCH_MINUTES`)
for users with alerts on and access: it re-reads their open pull requests by
node ID (about 5 GraphQL points per 100), searches a user's list again when it
is over 6 hours old (which finds new pull requests), and works out the waits
from stored times. It stops reading GitHub under `HOLT_WARM_MIN_POINTS`. Every
contributions fetch (the daily one, and the refresh button) makes the same
alerts for what it sees change, so a refresh never swallows one.

**Email.** Sent to `email` while `email_on`, by `email_mode`:

- `turn` (default): `changes` and `reply` right away, the rest in one daily email.
- `daily`: only the daily email.
- `all`: every kind right away.

"Right away" is the next 5-minute mailer run after the alert is 5 minutes old
(alerts from one check share an email), and at most one such email per pull
request in 24 hours; a later one waits for the daily email. The daily email
goes out at 8:00 in the user's `tz` with everything not emailed from the last
36 hours, and is skipped when empty. No email between 22:00 and 8:00 their
time. Each email carries `List-Unsubscribe` (one click, RFC 8058). Without
`RESEND_API_KEY` no email is sent at all (`email_available: false`); alerts
still reach the bell.

`AlertItem` = `{"id": 41, "kind": "reply", "text": "Your turn. @davidism replied on click #2811.",
"repo": "pallets/click", "number": 2811, "title": "Fix shell completion",
"pr_url": "https://github.com/pallets/click/pull/2811", "report_path": "/pallets/click",
"created_at": "…", "read_at": "…" | null}`.

`AlertSettings` = `{"enabled": true, "email": "you@example.com" | null, "email_on": true,
"email_mode": "turn" | "daily" | "all", "tz": "Asia/Kolkata", "access": AlertAccess,
"watching": 3, "email_available": true}`.

- `GET /v1/me/alerts?limit=20&before=<id>` → `{"unread": 2, "access": AlertAccess,
  "enabled": true, "watching": 3, "items": [AlertItem], "next_before": 17 | null}`.
  Newest first; `limit` 1–50; `next_before` is the `before` for the next page
  (null on the last). `unread` counts every unread alert, and is 0 without
  access. `enabled` is the person's own switch (as in settings). `watching` is
  how many open pull requests are being watched now.
- `GET /v1/me/alerts/count` → `{"unread": 2}`. Cheap, for the top bar on every
  page. 0 without access.
- `POST /v1/me/alerts/read` body `{"ids": [41, 40]}` or `{"all": true}` → 204.
  Only the caller's own alerts change. Neither given → 400 `invalid_request`.
- `GET /v1/me/alerts/settings` → `AlertSettings` (the defaults before anything is saved).
- `PUT /v1/me/alerts/settings` body `{"enabled"?, "email"?, "email_on"?, "email_mode"?, "tz"?}`
  → `AlertSettings`. Only the fields sent change.
  - `enabled: true` needs GitHub connected (404 `not_found` otherwise). In state
    `off` it starts the 14 days. In `ended` → 402 `needs_plan`. In `unavailable`
    → 501 `not_implemented`. Turning off and on again never restarts the 14 days.
  - `email` is the signed-in account's verified address: `web/` sends the one
    from the sign-in provider, never free text from the user (there is no
    confirm-link flow yet). `null` clears it. Not an address → 400.
  - `tz` is an IANA name from the browser (older names like `Asia/Calcutta`
    are fine); unknown → 400 `invalid_request`.
- `PUT /v1/me/contributions/{owner}/{name}/{number}/mute` → 204: no alerts for
  that pull request (its row on My PRs is unchanged, `watch: "muted"`).
  `DELETE` on the same path → 204, watched again. Not one of the caller's pull
  requests → 404 `not_found`.
- `POST /v1/alerts/unsubscribe` body `{"token": "…"}` (internal key, no user) →
  `{"email_on": false, "emails": "alerts"}`. The email's "Stop these emails"
  link and its one-click header: turns email off for the token's owner with no
  sign-in; the bell and `enabled` stay. `POST /v1/alerts/resubscribe` with the
  same body → `{"email_on": true, "emails": "alerts"}` (the page's "undo").
  The same two routes take the token from an account email (see "Account
  emails"): they switch that user's product emails instead and answer
  `"emails": "product"`, so the page can say which emails stopped. A token that isn't current → 404
  `not_found`. The token is derived from the server's secret and a per-user
  value, never stored, and changes when the address changes. It travels in the
  body so it stays out of the server's access log.

The emails link to the web app, so `web/` serves:

- `{HOLT_WEB_URL}/alerts/unsubscribe?t=<token>`: the footer link's page. It
  sends the token to `POST /v1/alerts/unsubscribe` and offers an undo. Do that
  from the browser (a button, or on load), not while rendering on the server:
  mail scanners and link previews fetch the links in an email, and a fetch
  alone must not unsubscribe anyone.
- `{HOLT_WEB_URL}/api/alerts/unsubscribe?t=<token>`: a `POST` route for mail
  clients' one-click unsubscribe (RFC 8058). It passes the token on the same
  way and answers 200.
- `{HOLT_WEB_URL}/settings/alerts` and `{HOLT_WEB_URL}/me/contributions`.

### Account emails

Five emails about the account itself, and no more: a welcome at an account's
first sign-in; a receipt for each paid pass; one 2 days before the 14 free
days of PR alerts end and one when they have (for someone whose alerts were
on and whom no pass covers); and one 3 days before a paid pass ends. Each is
sent once (`account_emails` is the log). Stored in `account_mail` and
`account_emails`.

**Switched off by default.** With `HOLT_ACCOUNT_EMAILS` unset none is sent;
with it on they also need `RESEND_API_KEY`. The receipt always goes out. The
rest respect one switch, `product_emails`, on by default.

- `POST /v1/me/sign-in` body `{"email": "…" | null, "first": false}` → 204.
  `web/` calls it at every sign-in (the Auth.js `signIn` event). `email` is
  the address the sign-in provider gave for the account, never free text from
  the user: account emails go there and nowhere else. `first: true` when this
  sign-in created the account: the welcome email is sent then, once per
  account, ever. Not an address → 400. The address is kept with the emails
  switched off too.
- `GET /v1/me/emails` → `{"email": "…" | null, "product_emails": true}`.
  `PUT /v1/me/emails` body `{"product_emails": false}` → the same shape.
- `GET /v1/lab/emails` (internal key, no user) → `{"emails": [LabEmail]}`,
  `LabEmail` = `{"kind", "name", "subject", "preheader", "html", "text"}`:
  every email Holt sends (these, and PR watch's two) on made-up data, for the
  web's `/lab/emails` page. 404 `not_found` when `HOLT_ENV=production`.

The product emails carry the same two unsubscribe links as alert emails
(`{HOLT_WEB_URL}/alerts/unsubscribe?t=<token>` and the one-click
`{HOLT_WEB_URL}/api/alerts/unsubscribe?t=<token>`); `POST /v1/alerts/unsubscribe`
tells the two kinds of token apart. They also link to `/find`,
`/settings/alerts`, `/me`, `/me/contributions`, `/pricing` and `/refunds`.

### Profile

What a signed-in user tells Holt once, so `/find` and `/hacktoberfest` start
from it. Stated, never inferred. Stored in `profiles`.

`ProfileOut` = `{"profile": ProfilePrefs | null, "adult_confirmed": true}`, where
`ProfilePrefs` = `{"languages": ["python"], "topics": ["cli"], "days": 7,
"contributions": ["docs", "tests"], "level": "newcomer", "updated_at": "…"}`.
`adult_confirmed` is true once the user has confirmed they're 18 or older,
here or by connecting GitHub.

- `GET /v1/me/profile` → `ProfileOut` (`profile` is null until saved).
- `PUT /v1/me/profile` body `{"languages", "topics", "days", "contributions",
  "level", "adult_confirmed"}` (all optional) → `ProfileOut`. Replaces the whole
  profile. Languages and topics are lower-cased and deduplicated, at most 10
  each; topics are GitHub topics (letters, numbers, dashes; spaces become
  dashes). `days` 1–90. `contributions` from `code`, `docs`, `tests`,
  `design`, `translations`. `level` is `newcomer` or `experienced`. The first
  save needs `adult_confirmed: true` unless GitHub is connected, else 400
  `invalid_request`; its time is stored.
- `DELETE /v1/me/profile` → `ProfileOut` with `profile: null`.

What each answer changes: languages, topics and days go into the find search
(days is the time budget the verdict uses). `level: newcomer` shows only
issues with `beginner: true`, and drops repos left with none; `experienced`
also shows issues asking for help and small unlabelled fixes. Issues whose
`areas` match `contributions` come first. The web applies `level` and
`contributions` to find results itself, so they don't change the find search
or its cache.

### Saved repos

Repositories a signed-in user saved to come back to later. Stored in
`saved_repos`: the user, the repository and when it was saved, nothing else.
Every route needs a signed-in user (401 `unauthorized` otherwise). Nothing
here calls GitHub.

`SavedState` = `{"repo": "owner/repo", "saved": true, "saved_at": "…"|null}`.
`SavedList` = `{"saved": [SavedItem], "max_saved": 500}`, newest first, where
`SavedItem` = `{"repo": "owner/repo", "saved_at": "…", "card": DiscoverRepo | null}`.
`card` is what `/v1/discover` shows for the repo (verdict, reason, stats,
description, language, stars, topics), read fresh from its latest 7-day rules
report and `repo_meta`; null while Holt has no current report for it.

- `GET /v1/me/saved` → `SavedList`. Not rate limited.
- `GET /v1/me/saved/{owner}/{repo}` → `SavedState` (is this one saved?).
- `PUT /v1/me/saved/{owner}/{repo}` (no body) → `SavedState`. Idempotent:
  saving again keeps the first `saved_at`. The name is stored with GitHub's
  casing when Holt already knows the repo. Bad name → 400 `invalid_repo`; a
  new save past `max_saved` → 400 `invalid_request`.
- `DELETE /v1/me/saved/{owner}/{repo}` → `SavedState` with `saved: false`,
  also when it wasn't saved.
- `DELETE /v1/me/saved` → `SavedList` with `saved: []`: removes every saved
  repo (part of deleting a user's data).

Writes (`PUT` and both `DELETE`s) have a bucket of their own, 300 an hour per
user, apart from work and read; over it → 429 `rate_limited`.

### Playbook: "How to get merged here" (paid)

For one repository: what its merged pull requests have in common, how big
they are, who reviews, why outside pull requests were closed (with quotes from
the project, linked), and a checklist. It is written by a model from counted
facts about the last 365 days of pull requests, and every claim is checked
against those facts before it is kept. It has no verdict and never changes the
report's. It exists only when the server runs with its paid features
(`HOLT_PRO_URL`); without them the GET says `available: false` and the POST is
501 `not_implemented`.

- `GET /v1/playbook/{owner}/{repo}` (anonymous or signed in; reads only the
  database) → `PlaybookState`:
  `{"repo", "available": true, "teaser": PlaybookTeaser|null, "playbook": Playbook|null, "unlocked": false, "access": Access|null, "on_sale": false, "job": PlaybookJob|null}`.
  - `teaser` is for everyone, once anyone has had this repository's playbook
    written: `{"sections": [{"key": "must_do", "count": 3}, …], "first": PlaybookItem|null, "generated_at"}`,
    the sections that have items (in display order) and the first must-do.
  - `playbook` is the whole playbook, only for a signed-in user who unlocked
    this repository (`unlocked: true`). Unlocks don't expire.
  - `access` (signed in only) is the `playbook` feature's `Access` (see
    Account): whether unlocking now is allowed and what it costs. `on_sale`
    says whether any plan or credit pack that pays for it is on sale; while
    it is false, a user who isn't allowed can't do anything about it yet.
  - `job` is the job writing this user's playbook for this repository while it
    runs (`{"job_id", "status", "stage", "progress"}`), so a reloaded page can
    follow it again.
- `POST /v1/me/playbook/{owner}/{repo}` (signed in; no body) unlocks it:
  - A playbook written in the last `HOLT_PLAYBOOK_CACHE_HOURS` (168) →
    `200 {"status": "done", "playbook": Playbook}`, charged once per user and
    repository (free when already unlocked).
  - Otherwise `202 {"status": "queued", "job_id"}`: a job writes it (usually
    1–3 minutes, stopped after `HOLT_JOB_TIMEOUT_AI`). People unlocking the same
    repository at once share one job; each is charged once. Someone who
    already unlocked it gets the newer one free.
  - Charged for the `playbook` feature before anything runs (402
    `quota_exceeded` or `needs_plan` otherwise, and nothing is queued). A job
    that fails gives back what everyone waiting on it was charged, and their
    unlock with it; its error message says so. An unknown or private
    repository is 404 `not_found` before any charge.
- `GET /v1/playbook-jobs/{job_id}` → `{"status", "stage", "progress", "playbook": Playbook|null, "error": Error|null}`,
  and `GET /v1/playbook-jobs/{job_id}/events` (SSE, as for analyses; `done`
  carries `{"playbook": Playbook}`).

`Playbook`: `{"repo", "generated_at", "note", "window_days", "archived", "sections"}`.
`note` is plain English to show once near the top when present (e.g. the counts
cover everyone's pull requests because too few outside ones were merged).
`sections` always has five lists, in display order; show nothing for an empty
one:
- `must_do`, `size_and_scope`, `reviewers`, `checklist`: `PlaybookItem`s,
  `{"text", "sources": [{"statement", "seen", "of", "links": ["https://github.com/…"]}]}`.
  `text` is plain English and may contain Markdown code spans (check names,
  paths), never HTML. Each source is a counted fact: "seen in `seen` of `of`"
  pull requests, with example links; `seen`/`of` are null for a fact from a
  document (the contributing guide, CODEOWNERS).
- `closing_reasons`: `{"reason", "explanation", "seen", "of", "examples": [{"number", "url", "title", "who", "quote"}]}`,
  most common first: `seen` of the `of` closed outside pull requests read
  showed it, each example a closed pull request with the exact words `who`
  (someone in the project) wrote on it.

### Merge plan (paid)

The paid AI report for one repository: the call (one sentence on what to do
here, next to the report's verdict and its numbers), your first pull request
as numbered steps, what gets merged, why outside pull requests get closed (in
the maintainers' words) and who reviews, plus what the AI found reading the
pull request threads. It is written from the repository's AI report and its
starter issues: rules build it, a model words the call and the steps, and
every claim is checked against its sources before it is kept. The verdict is
the report's, computed by rules; the model never picks it, and no field names
the model.

The AI report is a fresh one if there is one (made for anyone, by the current
engine, within `HOLT_CACHE_HOURS`); otherwise the job reads the threads
itself, as an AI report does, and keeps that report for the next plan. Either
way the plan costs one merge plan, never an AI report credit. If reading the
threads fails, the plan is still made, from the rules report: `ai` is null
and `note` says so.

Merge plans can be made only when the server runs with its paid features
(`HOLT_PRO_URL`) **and** AI is on (an AI budget, `HOLT_AI_BUDGET_USD`);
otherwise the GET says `available: false`, and the POST is 501
`not_implemented` (no paid features) or 503 `ai_unavailable` (AI off), with
nothing charged.

- `GET /v1/merge-plan/{owner}/{repo}` (anonymous or signed in; reads only the
  database) → `MergePlanState`:
  `{"repo", "available": true, "access": Access|null, "plan": MergePlan|null, "job": MergePlanJob|null}`.
  - `access` (signed in, when `available`) is the `merge_plan` feature's
    `Access` (see Account): whether one can be made now; `left` is how many
    are left (the free three, or this month's thirty on Pro).
  - `plan` (signed in) is this user's latest plan for this repository. It is
    theirs and kept, so it is returned even while `available` is false.
  - `job` (signed in) is the job making one for this user while it runs
    (`{"job_id", "status", "stage", "progress"}`), so a reloaded page can
    follow it again.
- `POST /v1/me/merge-plan/{owner}/{repo}` (signed in; no body) →
  `202 {"status": "queued", "job_id"}`: a job makes a new plan (usually two to
  four minutes when it reads the threads itself, about one when a fresh AI
  report exists; stopped after `HOLT_JOB_TIMEOUT_AI` plus 330 s). Its `stage`
  says what it is doing in plain words ("Reading the pull request threads").
  Asking again while one is being made returns that job, charged once.
  - One use of `merge_plan` is taken before anything runs (402
    `quota_exceeded` otherwise, and nothing is queued). An unknown or private
    repository is 404 `not_found`, and one with no report yet 404 `not_found`
    ("Check the repository first"), both before any charge.
  - A job that fails gives the use back; its error message says so. A plan
    made without "what the AI found" (reading the threads failed) is not a
    failure.
  - Asking again when nothing has changed returns the same plan (same
    `generated_at`) and gives the use back. A plan that changed, or that was
    made earlier for someone else, costs a use.
- `GET /v1/merge-plan-jobs/{job_id}` → `{"status", "stage", "progress", "plan": MergePlan|null, "error": Error|null}`,
  and `GET /v1/merge-plan-jobs/{job_id}/events` (SSE, as for analyses; `done`
  carries `{"plan": MergePlan}`).

`MergePlan`:

```json
{"repo": "pallets/click",
 "recorded_on": "2026-09-27T20:04:55+00:00", "generated_at": "2026-09-30T12:00:00+00:00",
 "window": {"days": 365, "since": "2025-09-27"},
 "sample": {"merged": 50, "closed": 25, "merged_outside": 5, "closed_outside": 25},
 "note": "Only 5 merged pull requests from people outside the project turned up …",
 "verdict": {"verdict": "viable", "headline": "Worth your time", "tone": "good", "line": "…",
             "numbers": [{"value": "5 of 8", "label": "outside PRs merged"}]},
 "call": {"text": "Pick a small change in `tests/` …", "sources": [Source]},
 "steps": [{"title": "Pick #3696, or a small fix in `tests/`", "detail": "…"|null,
            "link": {"label": "#3696 on GitHub", "url": "https://github.com/…"}|null,
            "copy": {"label": "Comment to post", "text": "Hi! …"}|null,
            "sources": [Source]}],
 "merged": [{"value": "72", "unit": "lines", "label": "typical merged pull request, in about 3 files",
             "seen": 38, "of": 50, "sources": [Source]}],
 "closed": [{"reason": "Written with AI tools", "seen": 8, "of": 25,
             "quote": {"text": "…", "who": "davidism", "url": "https://github.com/…", "number": 3874}|null,
             "examples": [{"number": 3874, "url": "https://github.com/…"}]}],
 "reviewers": {"people": [{"login": "Rowlando13", "reviewed": 27, "of": 50, "areas": ["tests/", "src/"]}],
               "sources": [Source]},
 "ai": {"read_on": "…", "threads": 12,
        "signals": [{"kind": "outsider_posture", "value": "welcoming", "headline": "Welcoming",
                     "text": "…", "tone": "good", "url": "https://github.com/…"|null}],
        "outcomes": [{"value": "merged_after_review", "count": 9}],
        "quotes": [{"text": "…", "url": "https://github.com/…", "number": 3701,
                    "outcome": "closed_with_guidance"}]}|null}
```

- A `Source` is the playbook's: `{"statement", "seen", "of", "links"}`.
- `verdict` is the report's (`line` is its `verdict_line`), with up to three
  numbers from its stats; a number with nothing to count is left out.
- `steps`: at most 6, in order. `detail`, `link` and `copy` may each be null;
  `copy` is a comment the person may post themselves (Holt never posts).
- `merged`: at most 6 figures (`value` and `unit` read together: "72 lines",
  "50 of 50"). `closed`: at most 5 reasons, most `seen` first, each with its
  first quote (`who` is the project member who wrote it) and up to 5
  examples. `reviewers.people`: the 3 most active reviewers and the folders
  each reviews most.
- `ai` is null when the plan was written without an AI report (reading the
  threads failed; `note` then ends with a sentence saying so). `signals` (`kind`
  one of `outsider_posture`, `onboarding`, `repo_kind`; `tone` one of `good`,
  `warn`, `bad`, `neutral`), `outcomes` (the engine's values, most common
  first, for the web to word) and up to 3 `quotes` from the threads.
- `call.text`, step titles and details, `merged[].label` and `closed[].reason`
  are plain English and may contain Markdown code spans, never HTML.
  `recorded_on` is when the pull requests were read from GitHub.
- `window.days` is the window asked for; `window.since` is the date the oldest
  pull request the counts read was opened (on a busy repository, well inside
  the window). Say "since" with this date, never with `days`.

### Recommendations for you

`GET /v1/me/recommendations?limit=10&offset=0` → `Recommendations`: a ranked
list of repositories (with starter issues) picked for the signed-in user, a
part at a time. Reads only the database: no GitHub call, no model, no rate
limit. Free for every signed-in user.

- **Parts**: `limit` is 1 to 30 (default 10) and `offset` is where the part
  starts (default 0); outside those, 400 `invalid_request`. `next` is the
  `offset` to ask for next, or `null` when this part is the last. `total` is
  how many picks there are in all. At most **60** picks are ranked for one
  person; an `offset` past the end returns no picks and `next: null`. The
  order is the same on every request while the data behind it is, so parts
  don't repeat or skip a repo. It is computed per request, so when a report
  or a profile changes between two requests a repo can show up twice or be
  missed: drop repeats by `repo`.

- **Which repos**: only ones whose latest 7-day rules report (checked in the
  last 14 days) says `viable`, plus `viable` find results from the last 7 days
  that Holt has no report for, where maintainers are still answering (median
  first reply within 7 days, at most half of outside pull requests with no
  reply). Archived repos, forks, the user's own repos and every repo they
  already sent a pull request to (My Contributions) are left out.
- **Matching**: a pick must share a language with the profile, a language
  the user's pull requests were merged in (connected users), or a profile
  topic. Newcomers never get "long odds" repos, see only issues labelled for
  first-timers, and a repo whose known issues have none is dropped.
- **Nothing to match on** (no profile languages or topics, no merged pull
  requests: a new account): the picks are repos written in a popular language
  (Python, JavaScript, TypeScript, Java, Go, Rust, C++), under the newcomer
  rules, the best of each language first. Their `why` lines never mention the
  user. `basis.languages`, `basis.topics` and `basis.history_languages` are
  all empty then, which is how a client tells these picks from matched ones.
- **Ranking** is fixed points, never a model: stated language 4, merged-in
  language 3 (both: 8), 2 per shared topic (up to 2), odds good 3 / fair 1,
  first-timers merged recently 2 (newcomers), fitting starter issues 2, one of
  the user's contribution types 1. Ties: merged share, reply time, sample.

```jsonc
{ "picks": [ { "repo": "owner/repo", "verdict": "viable", "headline": "Worth your time",
    "tone": "good", "odds": Odds | null, "reason": "…the report's verdict_line…",
    "standout": "…"|null,         // as on Discover, among all of the user's picks
    "numbers_line": "Of 42 pull requests from outside contributors, 19 were merged (45%). …",
    "why": ["Written in Python, one of your languages.",
            "Maintainers usually reply within 3 hours.",
            "6 people had their first pull request merged here recently."],
    "stats": Stats, "description": "…"|null, "language": "Python"|null,
    "stars": 123|null, "topics": ["cli"],
    "open_issues": 57|null, "pull_requests": 4100|null,
    "open_pull_requests": 12|null, "contributors": 812|null,  // as on Discover
    "issues": [StarterIssue],     // up to 3, fitted to level and contribution types; [] when none known
    "checked_at": "…"|null } ],
  "total": 37, "next": 10,        // next: the offset of the part after this one, or null
  "basis": { "languages": ["python"], "topics": ["cli"], "level": "newcomer",
             "contributions": ["docs"], "history_languages": ["Rust"],
             "already_contributing": 4, "has_profile": true, "connected": true },
  "computed_at": "…" }
```

Empty `picks` with `total: 0` means nothing fits right now (or Holt has no
repos to offer yet). Starter issues older than 72 hours aren't shown.

### Feedback: "Was this verdict right?"
- `POST /v1/feedback` body `{"repo": "owner/repo", "mode": "rules"|"ai", "days": 7,
  "generated_at": "<the report's generated_at>", "vote": "up"|"down", "reason": "…"|null}`
  → `200 {"repo", "generated_at", "verdict", "vote", "reason"}`.
- Anonymous or signed in. The person is `X-Holt-User` when present, else
  `X-Holt-Client-Ip` (required then; 400 `invalid_request` without it). The
  server stores a salted hash of the IP, never the IP itself.
- `generated_at` (with repo, mode and days) names the exact report version on
  screen; `404 not_found` if the server has no such report. The stored verdict
  is that report's, not anything the browser sends.
- One answer per person per report version: answering again replaces the
  vote and reason (a missing or blank `reason` clears it). Reasons are trimmed
  to 500 characters.
- Its own hourly limit, separate from work and read: 30 answers per IP
  anonymously, 120 per user; over it, 429 `rate_limited`.
- For the engine's golden set, `python -m holt_server.feedback export
  [--format csv|json] [--out FILE] [--since YYYY-MM-DD]` writes every answer
  with the report's key numbers and a pseudonymous voter id (no user ids or IP
  hashes). There is no HTTP export.

### PR pre-flight (paid)

For one public pull request, or a branch not opened as one yet: how it
compares with what gets merged in its repository. Each check says **looks
fine**, **worth fixing** or **can't tell yet**, computed by rules, with the
evidence behind it (example merged pull requests, the contributing guide's own
line), plus the merged pull request most like it. There is no overall verdict,
and it never changes the report's. Guidance only: Holt never posts to GitHub
and never writes code. It exists only when the server runs with its paid
features (`HOLT_PRO_URL`); without them the GET says `available: false` and the
POST is 501 `not_implemented`.

A target is either a pull request (`pr`: a link like
`https://github.com/o/r/pull/12`, anything after the number ignored, or
`o/r#12`) or a repository and a branch (`repo` + `branch`, `owner:branch` for
one in that person's fork, with an optional `base` to compare with; the default
branch otherwise). A link that isn't a pull request, a bad branch name, or both
kinds at once is 400 `invalid_request` with a plain message.

- `GET /v1/preflight?pr=…` or `?repo=…&branch=…&base=…` (anonymous or signed
  in; the target is optional; reads only the database) → `PreflightState`:
  `{"available": true, "on_sale": false, "access": Access|null, "target": {"repo", "number", "branch", "base"}|null, "result": Preflight|null, "job": PreflightJob|null}`.
  - `access` (signed in only) is the `preflight` feature's `Access` (see
    Account). `on_sale` says whether any plan or credit pack that pays for it
    is on sale.
  - `result` (signed in only) is this user's latest check of `target`;
    results are kept per user, target and head commit.
  - `job` is a check of `target` still running for this user
    (`{"job_id", "status", "stage", "progress"}`), so a reloaded page can
    follow it again.
- `POST /v1/me/preflight` (signed in) body
  `{"pr_url": "https://github.com/o/r/pull/12"}` or
  `{"repo": "o/r", "branch": "me:fix", "base": "main"}`, plus optional
  `"summary": true` (also a short written summary, same price). Unknown fields
  are 400. → `202 {"status": "queued", "job_id"}`. Every check reads GitHub
  again, so there is no instant answer.
  - Charged for the `preflight` feature before anything runs (402
    `quota_exceeded` or `needs_plan` otherwise, and nothing is queued). An
    unknown or private repository is 404 `not_found` before any charge.
  - A second request for the same target while one runs joins it, uncharged.
  - A check of a commit this user already had checked is free: the charge is
    given back when it finishes, and the result says `free_recheck: true`.
  - A job that fails gives the charge back; its error message says so. A pull
    request or branch GitHub doesn't have (or a branch with no new commits) is
    `not_found`; GitHub trouble is `upstream`. Usually a few seconds, up to a
    few minutes when the repository's history must be read first; stopped
    after `HOLT_JOB_TIMEOUT_AI`.
- `GET /v1/preflight-jobs/{job_id}` → `{"status", "stage", "progress", "preflight": Preflight|null, "error": Error|null}`,
  and `GET /v1/preflight-jobs/{job_id}/events` (SSE, as for analyses; `done`
  carries `{"preflight": Preflight}`).

`Preflight`: `{"repo", "checked_at", "window_days", "archived", "note", "target", "checks", "counts", "similar", "summary", "free_recheck"}`.
- `target`: `{"kind": "pull_request"|"branch", "number", "url", "title", "author", "outside", "state", "draft", "head", "base", "head_sha", "additions", "deletions", "lines", "files"}`.
  For a branch, `number`, `state` and `outside` are null and `url` is GitHub's
  compare page. `outside` is whether GitHub gives the author no role in the
  repository.
- `checks`, in display order: `{"id", "title", "verdict": "ok"|"worth_fixing"|"unknown", "statement", "links", "quote": {"text", "path", "url"}|null}`.
  Show `title` and the verdict in words ("looks fine", "worth fixing", "can't
  tell yet"), never the values. `statement` is plain English and may contain
  Markdown code spans; `links` are example merged pull requests (up to 8).
  A check that doesn't apply to the repository is left out; ids today are
  `ci`, `tests`, `size`, `template`, `issue`, `cla`, `signoff`, `changelog`.
- `counts`: `{"ok", "worth_fixing", "unknown"}`, counted from `checks`.
- `similar`: the merged pull request that changed the most of the same files,
  then folders (one from someone outside the project when any shares
  something), `{"number", "url", "title", "author", "outside", "lines", "files", "touched_tests", "why"}`,
  or null. `why` is plain English and may contain code spans.
- `note`: plain English to show once near the top when present (the
  comparison covers everyone's pull requests because too few outside ones were
  merged).
- `summary` (when asked for): `{"sentences": [{"text", "checks": ["issue"]}]}`,
  at most 3 sentences, each checked against the checks it cites; it never says
  whether the pull request will be merged.

## Public proxy for the browser extension (implemented by `web/`)

The browser extension (`extension/`) cannot hold `HOLT_INTERNAL_KEY`, so
`web/` exposes two read-only, anonymous proxy routes on the public host
(default `githolt.com`). They only read the cache; they never start an
analysis or call GitHub.

### `GET /api/public/report/{owner}/{repo}`
Proxies `GET /v1/reports/{owner}/{repo}?mode=rules&days=7`.
- `200` → the Report object (above), `mode: "rules"`. The extension reads only
  `headline`, `tone` and `stats.outsider_attempts` / `stats.outsider_merged`,
  so the proxy may strip `evidence` to keep responses small.
- `outdated: true` on a `200` means an older engine version made the report.
  The proxy never starts a check for it; it sends `max-age=300` instead of
  900, and the extension shows "Holt: updating" (not the old verdict) and
  links to the report page, which re-runs it.
- `404` → `{"error": {"code": "not_found", ...}}` when nothing is cached yet
  (or the repo is missing/private). The extension then shows "Check with Holt"
  and links to `/{owner}/{repo}`, whose page starts the rules analysis for
  any visitor who isn't a bot (signed out: rate-limited per IP by
  `HOLT_ANON_RATE_PER_HOUR`, and over the limit it asks them to sign in first).
  Signed out, that page shows a report as a teaser (verdict, reason, odds and
  one number) unless it is one of the curated examples; these proxies are
  unaffected.
- `429` `rate_limited` / `5xx` → shown as "Check with Holt" too.

### `GET /api/public/starter-issues/{owner}/{repo}`
Proxies `GET /v1/repos/{owner}/{repo}/starter-issues?limit=20` →
`{"repo": "…", "issues": [StarterIssue]}`. The extension reads `number`,
`why` and `on_it`. `404` when nothing is known.

Both routes:
- Accept `GET` and `OPTIONS` only, no cookies or auth. Forward the caller's
  IP as `X-Holt-Client-Ip` like any anonymous request. A `501` from the
  server (starter issues not shipped yet) may pass through; the extension
  just shows no marks.
- Send `Cache-Control: public, max-age=900` (15 min) on `200` and
  `max-age=300` on `404`, so a new analysis shows up soon.
- Send `Access-Control-Allow-Origin: *`. The extension fetches from its
  background worker (which its host permission covers), but open CORS keeps
  other read-only clients simple; the data is public.
- Normalise `{owner}/{repo}` as in "Repo identifiers"; reject anything else
  with `400 invalid_repo`.
