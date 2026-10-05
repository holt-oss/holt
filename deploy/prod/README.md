# Holt production: https://githolt.com

The production stack on this box (until it moves to Hetzner): Postgres, the
API server, the web app in [several containers](#web-containers) and a small
nginx `edge`, compose project **`holt-prod`**, published only on
**127.0.0.1:8310**. Cloudflare's tunnel
is the public route ([TUNNEL.md](TUNNEL.md)). It is built **only from
`origin/main`**, and it **deploys itself**: every new commit on main goes
live once its CI is green and staging is running it
([Auto-deploy](#auto-deploy)). Merging to main is shipping. The owner can
pause it, and `deploy.sh` still works by hand.

| File | What |
|---|---|
| `compose.yml` | The stack. Images are tagged with the deployed commit (`holt-prod-web:<sha>`), everything is labelled `holt.stack=holt-prod`, memory limits web 768m each / server 1536m / db 256m / edge 32m ([Web containers](#web-containers)). |
| `follow.sh` | The auto-deploy: one tick checks origin/main against CI and staging and runs `deploy.sh` for it. `--status`, `--pause`, `--resume`, `--retry`. See [Auto-deploy](#auto-deploy). |
| `install-follow.sh` | One-time: the timer that runs `follow.sh` every 2 minutes (`--remove` takes it out). |
| `deploy.sh` | One deploy: build main's images, migrate, swap, health-check (every web container), roll back on failure, set the CPU shares, prune only this stack's images, stop the builder container. |
| `env.sh` | Sourced by `deploy.sh` and `warm.sh`: state paths, `secrets.env`, the GitHub App's settings and the GitHub token fallback (`load_prod_env`); makes the evidence directory. |
| `github-app.sh` | Who production reads GitHub as (the GitHub App or `GITHUB_TOKENS`), its points left, and a test read of a public repository. Prints no secret. Setup is in the maintainers' ops notes. |
| `make-env.sh` | Writes `~/.local/share/holt-prod/.env` once: fresh `AUTH_SECRET`, `HOLT_INTERNAL_KEY`, `HOLT_SECRET_KEY`, db password. Nothing shared with staging. |
| `install.sh` | One-time: the env file plus the nightly backup timer and the daily repo-details timer; writes the report refresh timer, off until `--refresh-on`. The deploy timer is `install-follow.sh`. |
| `backup.sh` | `pg_dump` of both databases to `~/backups/holt/<stamp>/`, keeps 14 days. |
| `warm.sh` | Runs `python -m holt_server.warm` detached in the server image (fills the caches), with the same secrets and token as a deploy. |
| `warm-refresh.sh` | The report refresh: weekly tier (saved or recently viewed repos), then monthly tier (the other seeds), in the foreground. Off until switched on. See [Report refresh](#report-refresh). |
| `warm-meta.sh` | The daily details-only warm pass (language, stars, topics for Discover), in the foreground, holding the deploy lock. See [Repository details](#repository-details). |
| `edge.conf` | nginx: keeps the port across deploys, spreads requests over the web containers, `/__build`, `www` → apex redirect, SSE-friendly proxy, the Umami paths. A deploy puts changes live with a reload ([Edge config](#edge-config)). |
| `../swap.sh` | Sourced by `deploy.sh` (and staging's `preview.sh`): `swap_service` starts a service's new containers beside the old ones (as many as `deploy.replicas` asks for) and retires the old ones once every new one is healthy. |
| `../edge.sh` | Sourced by `deploy.sh` (and staging's `preview.sh`): checks a changed `edge.conf` with `nginx -t` in the running edge and reloads it. |
| `migrate-web.sh`, `initdb/` | Auth.js tables migration (one-shot `migrate-web` service) and the `holt_web` database. The API's own migrations run in the one-shot `migrate-server` service. |
| `TUNNEL.md` | Steps for the user to route githolt.com here. |
| `umami.sh` | One-time: the analytics service (Umami): its database and role, `.env` keys, first start, admin password. See [Analytics](#analytics). |
| `stats.sh` | The product numbers from Holt's own database, per day. Read-only, no personal data. |

State lives in `~/.local/share/holt-prod/` (outside every checkout, so
removing a worktree can't delete secrets): `.env`, `src/` (a clone at the
deployed commit), `current` and `previous` (image tags), `build/build.json`
(served at `/__build`), `releases/<sha>/compose.yml` (the compose file
each kept release went live with, for rollbacks), `autodeploy.json`, `AUTODEPLOY_PAUSED`,
`follow/` (the follower's clone and its failed commits), `edge/default.conf` (the edge's live nginx config,
plus `default.conf.prev`), `logs/`.

## Environment

Fixed in `compose.yml`: `HOLT_ENV=production`, `NEXT_PUBLIC_SITE_HOST=githolt.com`
(build and run time), `HOLT_WEB_URL` and `AUTH_URL=https://githolt.com`,
`TRUST_PROXY_HEADERS=1`, no `ROBOTS_NOINDEX` (production is indexed), no
`MOCK_API`. From `.env`: the generated secrets, `HOLT_STARTER_CACHE_HOURS=24`,
`HOLT_JOB_CONCURRENCY=6`, `HOLT_PROD_PORT=8310`, and optionally
`HOLT_WEB_REPLICAS` (2) and `HOLT_PROD_CPU_SHARES` (8192): see
[Web containers](#web-containers).

Keys the user owns come from **`~/.config/holt/secrets.env`** (`KEY=value`
lines, `chmod 600`), read by `deploy.sh` and `warm.sh` on every run (`env.sh`) and mapped:

| In `secrets.env` | Becomes | When missing |
|---|---|---|
| `GITHUB_OAUTH_ID`, `GITHUB_OAUTH_SECRET` | `AUTH_GITHUB_ID/SECRET` | GitHub sign-in shows "isn't set up here" |
| `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | `AUTH_GOOGLE_ID/SECRET` | Google sign-in shows "isn't set up here" |
| `OPENROUTER_API_KEY` | the same | AI reports answer `needs_key`; BYOK still works |
| `HOLT_PROD_AI_BUDGET_USD`, `HOLT_PROD_AI_BUDGET_OWNER_OK` | `HOLT_AI_BUDGET_USD`, `HOLT_AI_BUDGET_OWNER_OK` | AI is off (budget 0), whatever key is set. A budget without `HOLT_PROD_AI_BUDGET_OWNER_OK=1` stops the deploy, and the server ignores one without `HOLT_AI_BUDGET_OWNER_OK`. `HOLT_AI_BUDGET_USD` itself (staging's) is never read here. See `server/README.md`, "AI budget" |
| `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY_FILE` | the same; the key file (a host path, `chmod 640`) is mounted read-only at `/run/secrets/github_app_key` | the server reads with `GITHUB_TOKENS`. With all three set, it reads as the GitHub App and `GITHUB_TOKENS` is not used; with only some, the run stops. Setup and rollback are in the maintainers' ops notes. |
| `GITHUB_TOKENS` | the same | falls back to `gh auth token`; with neither (and no GitHub App), the run stops (the server would have no API budget and a warm pass would end at "points left 0") |
| `CONTACT_EMAIL`, `CONTACT_CITY` | `NEXT_PUBLIC_CONTACT_EMAIL/CITY` (build arg and env) | **the deploy stops**: the policy pages must not show placeholders |

There is never a dev sign-in in production: it exists only with
`NODE_ENV=development`, and the image runs with `NODE_ENV=production`.
After changing the file: `FORCE=1 deploy/prod/deploy.sh` (re-ups the live
tag with the new values; no rebuild).

## First time

```sh
deploy/prod/install.sh        # .env + nightly backup (03:30 UTC) + repo details (05:00 UTC) timers
deploy/prod/deploy.sh         # clone, build, migrate, start; ~10 min
deploy/prod/warm.sh           # fill the empty cache (detached; --status / --logs)
```

Then the tunnel: [TUNNEL.md](TUNNEL.md), and the auto-deploy:

```sh
deploy/prod/install-follow.sh # the 2-minute timer (holt-prod-follow.timer)
```

## Web containers

One Next.js process renders on one core: about 23 pages a second, and it
reached 503 MB under 200 concurrent readers. So the site runs
`HOLT_WEB_REPLICAS` web containers, **2 by default**, each with a 768 MB
limit (512 MB of it heap). The API server and the database stay one each.

```sh
echo HOLT_WEB_REPLICAS=3 >> ~/.local/share/holt-prod/.env   # 1, 2 or 3
FORCE=1 deploy/prod/deploy.sh    # three new ones start, then the old ones go; no rebuild
```

More than 3 is refused: each web container can hold 5 database connections,
twice as many containers run during a swap, and the db's `max_connections`
(80) is sized for three (the budget is in `compose.yml`).

**Load balancing.** All of them answer to the name `web` on the stack's
network. The edge asks Docker's DNS for that name every 2 seconds, gets
every container's address, and starts each request at a random one.

**Health.**

- A deploy waits for the health check of *every* new web container before
  any old one is retired, then asks each one for the home page and a report
  from inside the container (`healthy()` in `deploy.sh`). One that fails
  either sends the whole release back.
- A container that crashes or is killed for memory is restarted by Docker
  (`restart: unless-stopped`). Meanwhile the edge skips it: a refused
  connection goes to the next address at once, a vanished one after 1
  second, and within 2 seconds DNS no longer lists it.
- Not covered: a container that still accepts connections but has stopped
  answering keeps getting its share of requests. `docker ps` shows it as
  `unhealthy`; restarting that one container fixes it, and the others
  carry on meanwhile.

**What each container keeps to itself** (all in `web/src/lib/`): the per-IP
limit on the public endpoints (`rate-limit.ts`: an IP can make up to
`HOLT_WEB_REPLICAS` times the limit; the API server's own limits are
unchanged), the 10-minute Find cache (`find-cache.ts`: at most one search
per query per container), and the short caches for the landing page's
report, recent checks and "does this repo exist". Sign-in sessions are in
the database, so a visitor can land on any container.

**Memory.** The limits add up to 3.7 GB with 2 web containers and 4.4 GB
with 3 (web 768 MB each, server 1536, db 256, edge 32, Umami 320); a limit
is a ceiling, not what is used. During the web swap of a deploy the new set
runs beside the old one for a few seconds.

**CPU priority.** Every deploy gives the db, server, web and edge containers
`HOLT_PROD_CPU_SHARES` CPU shares (default 8192; `docker update`, no
restart). It is a priority, not a cap: when the box is busy each gets about
five times the CPU time of a container with the default 1024 (staging, a
build), and when it isn't nothing changes. It is not in `compose.yml`
because that would make compose recreate the db and the edge. It decides
between Docker containers (and the system's own services) only. Programs
run from a login (the dev workers) are in systemd's `user.slice`, which
shares the CPU half and half with everything else however many of them
run; that split is a host setting (`CPUWeight` on `user.slice`), not this
stack's.

```sh
docker ps --filter label=com.docker.compose.project=holt-prod --filter label=com.docker.compose.service=web
docker inspect -f '{{.Name}} {{.HostConfig.CpuShares}}' $(docker ps -q --filter label=holt.stack=holt-prod)
```

## Auto-deploy

`holt-prod-follow.timer` runs `follow.sh` every 2 minutes (the copy in
`~/.local/share/holt-prod/bin/`, installed by `install-follow.sh`; re-run
that after changing `follow.sh`). It pulls: nothing on GitHub can reach
the box, and there is no self-hosted runner (the repository is public).

**One tick:**

1. Fetch `origin/main`. Same as the live commit (`current`)? Nothing to do.
2. **CI gate.** On that exact commit, GitHub must have at least one check
   run, and every check run and every workflow run must be completed with
   *success* or *skipped* (`gh api repos/holt-oss/holt/commits/<sha>/check-runs`
   and `.../actions/runs?head_sha=<sha>`, with the box's `gh` login).
   Still running: wait. Anything else (failure, cancelled, timed out): wait
   for a newer commit; a re-run that goes green counts.
3. **Staging gate.** Staging must be live on the same commit:
   `live.main.sha` on http://127.0.0.1:9110/__build. Staging follows main
   by itself, so this also means the commit built, migrated and started
   there.
4. Deploy: takes `deploy.sh` (and `compose.yml`, `warm.sh`) from that
   commit, in the follower's own clone, and runs `deploy.sh <sha>`: the
   usual build, migrate, swap, health check, roll back on failure. A
   manual deploy holding the lock, or a box too busy for 30 minutes, isn't
   a failure: the next tick tries again.
5. When `src/holt/engine_version.py` differs between the old and the new
   commit, stop a running warm pass and start `warm.sh --stale-only`.

It only ever deploys the tip of main, never a PR or an older commit.

**A failed deploy is not retried.** `deploy.sh` has already rolled back to
the last good commit; the follower records the commit in
`follow/failed` and leaves production there until main moves on (a fix
merged) or someone runs `follow.sh --retry`. A deploy that is killed
half-way counts as failed too.

**Where to look:**

```sh
curl -s https://githolt.com/__build | jq .autodeploy      # {state, sha, at, message}
~/.local/share/holt-prod/bin/follow.sh --status             # the same, plus failed commits and recent changes
systemctl --user list-timers holt-prod-follow.timer
journalctl --user -u holt-prod-follow -n 50                 # every tick
less ~/.local/share/holt-prod/logs/follow.log               # one line per change of state
ls -t ~/.local/share/holt-prod/logs/autodeploy-*.log        # one per deploy (last 20), next to deploy.sh's own
```

`state` is `up_to_date`, `waiting` (CI running, or staging not on it
yet), `blocked` (CI red), `deploying`, `deployed`, `failed`, `held` (a
failed commit, not retried), `busy` (another deploy or a busy box),
`paused` or `error` (GitHub or the fetch didn't answer; next tick).

**Pause and resume** (the timer keeps running and does nothing):

```sh
F=~/.local/share/holt-prod/bin/follow.sh
$F --pause "launch day, hands off"     # or: touch ~/.local/share/holt-prod/AUTODEPLOY_PAUSED
$F --resume                            # or: rm that file
```

Deploying an older commit by hand (a rollback, `deploy.sh <sha>`) pauses
it by itself, so the next tick doesn't put main straight back; `--resume`
once main has the fix.

**Deploying by hand** still works, with or without the timer: `deploy.sh`
([Deploying](#deploying)). They share a lock, so the two never run at
once. To turn the auto-deploy off for good: `install-follow.sh --remove`.

## Deploying

By hand (the auto-deploy does the first line for you):

```sh
deploy/prod/deploy.sh                 # origin/main; no-op if it is already live
deploy/prod/deploy.sh <sha>           # an older main commit (rollback); refuses anything not on main
FORCE=1 deploy/prod/deploy.sh         # re-up the live tag (after editing secrets); skips the load check
REBUILD=1 deploy/prod/deploy.sh       # rebuild the images for the tag
```

What one run does, in order:

1. Takes a lock (`~/.local/share/holt-prod/lock`); a second run exits
   (status 75, like a box that stays too busy: nothing was changed).
2. Reads `secrets.env`, fetches `origin/main`, checks the commit is on it.
3. Waits until the 1-minute load is under 6 and MemAvailable over 3 GB
   (up to 30 min; `FORCE=1` skips this).
4. Builds `holt-prod-server:<sha>` then `holt-prod-web:<sha>` (never both at
   once) on its own buildx builder `holt-prod` (3 GB cap).
5. Starts `db` if needed and runs the one-shot `migrate-web` (Auth.js SQL,
   each file once), then `migrate-server` (the API's Alembic migrations, with
   the new server image; see `server/README.md`). Either failing stops the
   deploy before anything is swapped. A rollback does not undo a migration,
   which is why migrations must keep working with the previous release.
6. The swap, with no gap ([`../swap.sh`](../swap.sh)): server, then web.
   The new containers start next to the old ones (`compose up --scale
   <old + new> --no-recreate`: one server, `HOLT_WEB_REPLICAS` web); once
   every one of them passes its health check, the old ones get SIGTERM and
   are removed. Meanwhile all of them answer to the service's name: the edge
   re-resolves `web` every 2 s and tries another address when one
   refuses, and web retries a dropped connection to `server` once
   (`web/src/lib/upstream-retry.ts`). If one new container never gets
   healthy, all the new ones are removed and the old ones keep serving. Then
   `compose up -d` for the rest (db, edge, umami), and the CPU shares
   ([Web containers](#web-containers)). If web still can't be reached, the edge
   shows the [updating page](#the-updating-page) instead of Cloudflare's 502.
   Compose's project directory is always the state clone
   (`src/deploy/prod`), whichever checkout runs `deploy.sh`: the db's
   `./initdb` mount then never changes path, so `follow.sh` and a person
   deploying by hand never make compose recreate the db. (The first deploy
   with this recreates the db once, a few seconds, because the mount moves
   from the checkout it was started from.)
7. Health check: `/` answers 200 and `GET /api/public/report/pallets/flask`
   (the extension's read-only proxy: open to signed-out callers, never starts
   an analysis) answers 200 or 404 ("no report yet"), through the edge and
   then from inside every web container, within 5 minutes. A 502
   there means web can't reach the server. (It no longer POSTs
   `/api/analyses`: since registered-users gating that answers 401 when
   signed out.)
8. On failure: the same swap back to the previous tag **with the previous
   release's own `compose.yml`** (kept in `releases/<sha>/` for the live and
   the previous release, or taken from that commit in git), so a commit that
   breaks `compose.yml` itself still rolls back. Every web container of the
   failed release is replaced, and their number goes back to what that file
   asks for (one, for a release from before this setting). Checks again, records
   the failure on `/__build`, exits 1. On success: records `current`/`previous`.
9. Edge config: when the deployed commit's `edge.conf` differs from the
   edge's, installs it, runs `nginx -t` in the running edge and reloads
   (never a restart; the port stays open), then runs the health check again.
   A rejected or unhealthy config is put back and the run fails loudly
   (`EDGE CONFIG NOT APPLIED` / `REVERTED`, and on `/__build`); the new
   release itself stays live. See [Edge config](#edge-config).
10. Prunes only this stack: untag image tags other than current and previous,
   `docker image prune --filter label=holt.stack=holt-prod`, and the builder's
   cache over 3 GB. Nothing else on the box is touched.

## Edge config

The edge (nginx) reads `~/.local/share/holt-prod/edge/default.conf`, a copy
of `deploy/prod/edge.conf` at the deployed commit. The whole directory is
mounted, not the file: a single-file bind mount pins the file's inode, so
after git replaced `edge.conf` the running edge kept the old one until it
was recreated, which deploys never do (the Umami paths from #76 answered
404 after the 28 Sep deploy for that reason).

Each deploy, after the swap and the health check:

- `edge.conf` unchanged: nothing happens (`edge config unchanged` in the log).
- Changed: the old file is kept as `default.conf.prev`, the new one goes
  in, `nginx -t` runs inside the running edge, then `nginx -s reload`.
  A reload is graceful: the port never closes and open requests finish.
  Then the health check runs again.
- `nginx -t` fails: the old file goes back (the running nginx never left
  it), `/__build` records the failure, and the run exits 1 with
  `EDGE CONFIG NOT APPLIED` and nginx's message. The new release is live;
  fix `edge.conf` on main and deploy again.
- The health check fails after the reload: `default.conf.prev` goes back,
  another reload, and the run exits 1 with `EDGE CONFIG REVERTED`.

On the first deploy that has this, compose sees the edge's new mount and
recreates the edge once (a second or so without the port); from then on
the edge is only ever reloaded. That deploy also puts any config the old
edge missed live, such as the `/stats/` paths.

By hand (the same checks deploy.sh makes):

```sh
docker exec holt-prod-edge-1 nginx -t
docker exec holt-prod-edge-1 nginx -s reload
```

## The updating page

When the edge can't reach web (nginx's own 502, 503 or 504; never the
app's own error pages), it answers with a small "Holt is updating. Back in
a few seconds." page instead: status 503, `Retry-After: 10`,
`Cache-Control: no-store`, light and dark, and it reloads itself once the
site answers (every 5 s; a meta refresh without JavaScript). Cloudflare
shows an origin's 5xx page as it is, so visitors see this instead of
Cloudflare's own error page. It lives in `edge.conf` (`location @updating`,
the same in staging's) and goes live with the edge config reload. A deploy
normally never shows it; it covers a web crash or a swap that goes wrong.

```sh
curl -sI -H 'Host: githolt.com' http://127.0.0.1:8310/  # 200 normally
```

## Status, logs, helpers

```sh
P=~/projects/holt/deploy/prod; S=~/.local/share/holt-prod
dc() { HOLT_SRC=$S/src HOLT_TAG=$(cat $S/current) HOLT_PROD_HOME=$S \
       docker compose -p holt-prod -f $P/compose.yml --project-directory $S/src/deploy/prod \
       --env-file $S/.env "$@"; }

curl -s http://127.0.0.1:8310/__build | jq '.live.main.short, .last_attempt'
dc ps
dc logs -f --tail 100 server web
ls -t $S/logs | head                     # deploy logs (last 20 kept)
dc stop; dc start                        # pause / resume (keeps data and the port)
```

## Backups and restore

`install.sh` enables `holt-prod-backup.timer` (daily 03:30 UTC, runs the
copy at `~/.local/share/holt-prod/bin/backup.sh`; re-run `install.sh` after
editing `backup.sh`). Each run writes
`~/backups/holt/<UTC stamp>/holt.dump`, `holt_web.dump` (pg_dump custom
format, compressed) and `globals.sql`, and deletes sets older than 14 days.

```sh
systemctl --user list-timers holt-prod-backup.timer
journalctl --user -u holt-prod-backup -n 20
deploy/prod/backup.sh                    # one now
```

Restore (into the running stack; stop web and server first so nothing
writes meanwhile):

```sh
B=~/backups/holt/<stamp>
DB=$(docker ps -q --filter label=com.docker.compose.project=holt-prod --filter label=com.docker.compose.service=db)
dc stop web server
docker exec -i $DB psql -U holt -d postgres -c 'DROP DATABASE IF EXISTS holt_restore'
docker exec -i $DB psql -U holt -d postgres -c 'CREATE DATABASE holt_restore'
docker exec -i $DB pg_restore -U holt -d holt_restore --no-owner < $B/holt.dump      # try it on a scratch db first
docker exec -i $DB psql -U holt -d holt_restore -c 'SELECT count(*) FROM reports'   # looks right?
# the real thing: swap the databases (nobody is connected: web and server are stopped)
docker exec -i $DB psql -U holt -d postgres -c 'ALTER DATABASE holt RENAME TO holt_old; ALTER DATABASE holt_restore RENAME TO holt'
# same for holt_web with holt_web.dump, then
dc start server web
# once happy: docker exec -i $DB psql -U holt -d postgres -c 'DROP DATABASE holt_old'
```

To restore on a new machine: start the stack once (`deploy.sh`), stop web
and server, drop and recreate `holt` and `holt_web`, `pg_restore` each dump,
start. `HOLT_SECRET_KEY` must be the same as when the BYOK keys were saved,
so keep `.env` with the backups (it is not in them).

## Warm pass

Production starts with an empty cache. `deploy/prod/warm.sh` runs
`python -m holt_server.warm` in a detached container (`holt-prod-warm`) with
the server's environment; jobs go through the queue at badge priority,
`HOLT_WARM_PARALLEL` (3) in flight at once, so people's requests always run
first. Seeds that are closed to outside pull requests or dormant go last. A
report costs about 12 GitHub GraphQL points, so a cold sweep of the ~10,000
seeds is about 120,000 points over about 42 hours. It stops by itself under
`HOLT_WARM_MIN_POINTS` (counting the reports in flight) and picks up where it
left off next time; with `--wait-for-budget` it waits for the points to come
back instead.

A seed whose report fails waits before it is asked for again (six hours,
doubling to a week) and then goes to the back, and a "slow down" from GitHub
pauses a `--wait-for-budget` pass instead of ending it (`server/README.md`,
"Warm cache"). `--status` says how many seeds were skipped as recently failed
and how many are to go; the summary lists the seeds that aren't on GitHub.

```sh
deploy/prod/warm.sh --dry-run
deploy/prod/warm.sh --no-find --wait-for-budget   # then --status or --logs
```

Only one pass runs at a time (an advisory lock, and `warm.sh` checks for the
container). A deploy doesn't touch a running pass unless the engine changed:
it keeps its old image and settings until it ends. To restart it on the new
image, `docker stop holt-prod-warm` (a report it was running is queued again
and finished by the server), then `warm.sh` again.

**After a deploy that changes the engine** (`ENGINE_VERSION` in
`src/holt/engine_version.py` went up), every stored report from the old
engine is out of date. Nobody is served one: report pages re-run it, the
badge and the extension say "updating", and Discover and recommendations
leave it out until it is redone. The auto-deploy starts the stale-only
pass by itself after such a deploy (stopping a pass that is still running).
After a deploy by hand, run it once the deploy is up:

```sh
deploy/prod/warm.sh --dry-run --stale-only   # "would analyse …" / "would make … again" per outdated seed
deploy/prod/warm.sh --stale-only             # then --status or --logs
```

A seed whose evidence was kept within its refresh tier's age (a week for repos
someone saved or viewed lately, a month for the rest; at least
`HOLT_EVIDENCE_REUSE_HOURS`, 168) is made again from that snapshot, with no
GitHub points; the summary line
counts them ("N made again from kept evidence"). The rest are read from
GitHub as before.

## Evidence snapshots

Every report also keeps the evidence it read, one gzipped file per report, in
`~/.local/share/holt-prod/evidence/<owner>__<name>/<UTC time>.json.gz`
(`server/README.md`, "Evidence snapshots"). It is on `/home`, bind-mounted
into the server at `/data/evidence`, never in the database volume on `/`.
`env.sh` makes the directory before each deploy or warm pass: group-writable
and setgid, and the server's user (uid 10001) joins its group
(`HOLT_EVIDENCE_GID`, compose.yml `group_add`), so the files stay readable
and removable by you. Staging keeps its own in
`~/.local/share/holt-staging/evidence` (preview.sh).

Every snapshot is kept. About 126 MB per 1,000 repos per round; with the
refresh timer on, 325 repos take about 0.5 GB a year if all are monthly
(12 rounds), plus a weekly repo's 52 rounds (6 MB a year each) and what
people's own checks add. To cap it, set `HOLT_EVIDENCE_KEEP_DAYS` in
`~/.local/share/holt-prod/.env` (a repo's newest snapshot always stays).

```sh
du -sh ~/.local/share/holt-prod/evidence
ls ~/.local/share/holt-prod/evidence/pallets__flask/
```

## Report refresh

`holt-prod-warm-refresh.timer` refreshes reports by interest, daily at 06:00
UTC (`warm-refresh.sh`, log `~/.local/share/holt-prod/logs/warm-refresh.log`):

- **weekly**: repos someone saved, or viewed on Holt in the last 30 days,
  whose report is over 168 hours old (`HOLT_REFRESH_WEEKLY_HOURS`);
- **monthly**: the rest of the seed list, over 720 hours old
  (`HOLT_REFRESH_MONTHLY_HOURS`).

Oldest first, through the job queue at badge priority (people first), and it
stops below `HOLT_WARM_MIN_POINTS`; what's left carries on the next day. Each
report it makes adds a snapshot. At about 12 GitHub points a report, a month
costs about 3,900 points at today's ~325 repos (4,900 if 25 of them are
weekly) and about 120,000 at the full ~10,000 seeds (about 128,000 with 200
weekly): 130 to 4,300 points a day, against 5,000 an hour.

**It ships off.** To switch it on (after a deploy that includes it):

```sh
deploy/prod/install.sh --refresh-on
```

`--refresh-off` switches it off. By hand, once: `~/.local/share/holt-prod/bin/warm-refresh.sh`.

## Repository details

Discover, the Hacktoberfest row and the repo cards show each repo's
language, stars, topics and description from `repo_meta`. They are read:

- **right after a repo's report is stored**, when it has none or they are a
  day old (`server/holt_server/meta_refresh.py`): best effort, after the
  report is already done, reports finishing within a few seconds share one
  query. A failure is logged (`repository details ... failed`) and the
  next report tries again;
- **once a day for every reported repo** by `holt-prod-warm-meta.timer`
  (05:00 UTC, installed by `install.sh`), which runs the copy at
  `~/.local/share/holt-prod/bin/warm-meta.sh`: the warm pass with
  `--no-reports --no-starter --no-find`, in a one-off container of the live
  server image. It works no jobs, costs about one GraphQL point per hundred
  repos (the summary line says how many), and stops below
  `HOLT_WARM_MIN_POINTS`. It holds `deploy.sh`'s lock while it runs (a
  deploy then exits busy and the auto-deploy retries two minutes later),
  waits for a running deploy or backup (`backup.lock`) for up to 45 minutes,
  else skips the day.

```sh
deploy/prod/install.sh                              # (re)install both timers; needs a deploy first
systemctl --user list-timers holt-prod-warm-meta.timer
tail ~/.local/share/holt-prod/logs/warm-meta.log    # "repo details N read (P GitHub points)"
~/.local/share/holt-prod/bin/warm-meta.sh           # one now
```

## Checks after a deploy

```sh
H=http://127.0.0.1:8310
curl -sI $H/ | head -3
curl -s $H/robots.txt                                # Allow: / … Sitemap: https://githolt.com/sitemap.xml
curl -s $H/sitemap.xml | head -5
curl -sI $H/hacktoberfest | head -1
curl -sI -H 'Host: www.githolt.com' $H/ | grep -i location     # https://githolt.com/
curl -s -o /dev/null -w '%{http_code}\n' $H/api/public/report/pallets/flask   # 200 (or 404: no report yet)
cd e2e && BASE_URL=$H npx playwright test --workers=1     # plain http on the port; Chromium refuses a Host override
cd e2e && BASE_URL=https://githolt.com npx playwright test --workers=1   # once the tunnel is up
```

## Rehearsing a change to these scripts

`HOLT_PROD_PROJECT` renames the project, the images, the label and the
builder, so a rehearsal can't touch the real stack. In a task worktree:

```sh
HOLT_PROD_PROJECT=$COMPOSE_PROJECT_NAME HOLT_PROD_HOME=/tmp/rehearsal HOLT_PROD_PORT=$PORT deploy/prod/deploy.sh
```

`cx done` takes that project down by name.

To watch a swap under load, deploy once, then add an empty commit to the
rehearsal's origin, tag the same images with its SHA (so nothing is
built), and deploy again with a loop of requests running against
`127.0.0.1:$PORT`: every answer should be what it was before the swap (a 200, or a 429 from
the rate limit), never a 502 or the updating page. A rehearsal's containers
keep the default CPU shares. When the box is busy with other work,
`HOLT_PROD_MAX_LOAD` raises the load the deploy will start under.

To force a rollback, run `deploy.sh` from a copy of `deploy/` whose
`compose.yml` gives web a wrong `HOLT_INTERNAL_KEY` (the containers get
healthy, the report check answers 401, both web containers go back), or tag
an image that exits at start as the new commit's web image (the new
containers are removed and the old ones never stop).

The follower on top: the same three variables, plus a fake origin (a bare
repository whose `main` you move), a stand-in for `gh` that prints the
check runs' TSV from files, and a fake staging `/__build`:

```sh
export HOLT_PROD_PROJECT=$COMPOSE_PROJECT_NAME HOLT_PROD_HOME=$R/home HOLT_PROD_PORT=$PORT
export HOLT_FOLLOW_REMOTE=$R/origin.git HOLT_FOLLOW_GH=$R/gh
export HOLT_FOLLOW_STAGING_URL=http://127.0.0.1:$((PORT+1))/__build
export HOLT_SECRETS_FILE=$R/secrets.env      # fake CONTACT_EMAIL / CONTACT_CITY
git clone $R/origin.git $R/home/src          # so deploy.sh fetches the fake origin too
deploy/prod/follow.sh                        # one tick
```

Never run it without `HOLT_PROD_HOME`: it would deploy the real stack.

The edge step alone needs no images: point `HOLT_PROD_HOME` at a scratch
directory with a `.env` (the `:?` variables set to anything,
`HOLT_PROD_PORT=$PORT`) and `src/deploy/prod/edge.conf`, source `edge.sh`,
define `compose` as `deploy.sh` does, then `edge_seed`, `compose up -d
--no-deps edge`, edit that `edge.conf` and `edge_apply`, with a `curl` loop
on the port to show it never drops.

## Removing it

```sh
deploy/prod/install-follow.sh --remove
systemctl --user disable --now holt-prod-backup.timer holt-prod-warm-meta.timer holt-prod-warm-refresh.timer
dc down            # add -v to drop the database too (take a backup first)
docker buildx rm holt-prod
docker image prune -af --filter label=holt.stack=holt-prod
rm -rf ~/.local/share/holt-prod ~/.config/systemd/user/holt-prod-backup.* ~/.config/systemd/user/holt-prod-warm-meta.* ~/.config/systemd/user/holt-prod-warm-refresh.*
```

## Analytics

Two sources, both on this box, neither a third party:

- **Holt's own database** (`deploy/prod/stats.sh`): the product numbers.
  Per UTC day: distinct people asking for a report (the reach number,
  signed in or not), requests, repositories, reports actually generated,
  AI reports, `/find` searches, new accounts. People are counted from
  `usage_events.who`, a hash of the user id or IP that changes every day
  (`server/holt_server/usage.py`), so the numbers are per day only.
  `generated` includes badge refreshes and the warm pass.
- **Umami** (compose service `umami`, image pinned to `3.4.0`): page views,
  referrers, countries, and the browser events `paste-submit`,
  `report-view` (with `verdict`), `starter-issue-click`, `find-run`,
  `sign-in` (with `provider`). Cookieless, nothing in browser storage, so
  no cookie banner. Only githolt.com builds load it
  (`web/src/lib/analytics.ts`); staging sends nothing.

```sh
deploy/prod/stats.sh          # last 14 days
deploy/prod/stats.sh 30
```

### Umami: first time

After a deploy that contains the `umami` service:

```sh
deploy/prod/umami.sh
```

It adds `UMAMI_DB_PASSWORD`, `UMAMI_APP_SECRET` and
`COMPOSE_PROFILES=analytics` to `.env` (so every later deploy's `compose up`
keeps Umami running), creates the `umami` role and database in the running
`db` (that role can't connect to `holt` or `holt_web`), starts `umami`,
**replaces the default `admin` / `umami` password** with a random one saved
to `~/.local/share/holt-prod/umami-admin` (`chmod 600`), and creates the
githolt.com site with the fixed id the web app sends. Safe to run again.
Nothing else in the stack is restarted.

Why the same Postgres: a second server would cost another ~50 MB and its
own backups for a few small tables. Umami gets its own role and database,
and `backup.sh` dumps it with the others.

### Where to see it

The dashboard is **not public**: it listens on `127.0.0.1:8311` only
(`HOLT_UMAMI_PORT`) and needs the admin login. The edge exposes just
`/stats/script.js` and `/stats/api/send` (the tracker and its endpoint, on
githolt.com's own origin, so the CSP needs no extra host). From the laptop:

```sh
ssh -N -L 8311:127.0.0.1:8311 aahil-server     # then http://localhost:8311
```

User `admin`, password on line 2 of `~/.local/share/holt-prod/umami-admin`.
Change it in the dashboard if you like (Settings, Profile); the file is only
what `umami.sh` set.

Memory: `umami` is capped at 320 MB. To turn it off: remove
`COMPOSE_PROFILES=analytics` from `.env` and `dc --profile analytics stop umami`;
the pages carry on (the script request just fails).

