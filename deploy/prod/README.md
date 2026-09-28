# Holt production: https://githolt.com

The production stack on this box (until it moves to Hetzner): Postgres, the
API server, the web app and a small nginx `edge`, compose project
**`holt-prod`**, published only on **127.0.0.1:8310**. Cloudflare's tunnel
is the public route ([TUNNEL.md](TUNNEL.md)). It is built **only from
`origin/main`** and **never updates on its own**: the orchestrator runs
`deploy.sh` when the user approves a deploy.

| File | What |
|---|---|
| `compose.yml` | The stack. Images are tagged with the deployed commit (`holt-prod-web:<sha>`), everything is labelled `holt.stack=holt-prod`, memory limits web 512m / server 512m / db 256m / edge 32m. |
| `deploy.sh` | One deploy: build main's images, migrate, swap, health-check, roll back on failure, prune only this stack's images, stop the builder container. |
| `env.sh` | Sourced by `deploy.sh` and `warm.sh`: state paths, `secrets.env` and the GitHub token fallback (`load_prod_env`). |
| `make-env.sh` | Writes `~/.local/share/holt-prod/.env` once: fresh `AUTH_SECRET`, `HOLT_INTERNAL_KEY`, `HOLT_SECRET_KEY`, db password. Nothing shared with staging. |
| `install.sh` | One-time: the env file plus the nightly backup timer. No deploy timer, on purpose. |
| `backup.sh` | `pg_dump` of both databases to `~/backups/holt/<stamp>/`, keeps 14 days. |
| `warm.sh` | Runs `python -m holt_server.warm` detached in the server image (fills the caches), with the same secrets and token as a deploy. |
| `edge.conf` | nginx: keeps the port across deploys, `/__build`, `www` → apex redirect, SSE-friendly proxy, the Umami paths. A deploy puts changes live with a reload ([Edge config](#edge-config)). |
| `../swap.sh` | Sourced by `deploy.sh` (and staging's `preview.sh`): `swap_service` starts a service's new container beside the old one and retires the old one once the new one is healthy. |
| `../edge.sh` | Sourced by `deploy.sh` (and staging's `preview.sh`): checks a changed `edge.conf` with `nginx -t` in the running edge and reloads it. |
| `migrate-web.sh`, `initdb/` | Auth.js tables migration (one-shot `migrate-web` service) and the `holt_web` database. The API's own migrations run in the one-shot `migrate-server` service. |
| `TUNNEL.md` | Steps for the user to route githolt.com here. |
| `umami.sh` | One-time: the analytics service (Umami): its database and role, `.env` keys, first start, admin password. See [Analytics](#analytics). |
| `stats.sh` | The product numbers from Holt's own database, per day. Read-only, no personal data. |

State lives in `~/.local/share/holt-prod/` (outside every checkout, so
removing a worktree can't delete secrets): `.env`, `src/` (a clone at the
deployed commit), `current` and `previous` (image tags), `build/build.json`
(served at `/__build`), `edge/default.conf` (the edge's live nginx config,
plus `default.conf.prev`), `logs/`.

## Environment

Fixed in `compose.yml`: `HOLT_ENV=production`, `NEXT_PUBLIC_SITE_HOST=githolt.com`
(build and run time), `HOLT_WEB_URL` and `AUTH_URL=https://githolt.com`,
`TRUST_PROXY_HEADERS=1`, no `ROBOTS_NOINDEX` (production is indexed), no
`MOCK_API`. From `.env`: the generated secrets, `HOLT_STARTER_CACHE_HOURS=24`,
`HOLT_JOB_CONCURRENCY=6`, `HOLT_PROD_PORT=8310`.

Keys the user owns come from **`~/.config/holt/secrets.env`** (`KEY=value`
lines, `chmod 600`), read by `deploy.sh` and `warm.sh` on every run (`env.sh`) and mapped:

| In `secrets.env` | Becomes | When missing |
|---|---|---|
| `GITHUB_OAUTH_ID`, `GITHUB_OAUTH_SECRET` | `AUTH_GITHUB_ID/SECRET` | GitHub sign-in shows "isn't set up here" |
| `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | `AUTH_GOOGLE_ID/SECRET` | Google sign-in shows "isn't set up here" |
| `OPENROUTER_API_KEY` | the same | AI reports answer `needs_key`; BYOK still works |
| `GITHUB_TOKENS` | the same | falls back to `gh auth token`; with neither, the run stops (the server would have no API budget and a warm pass would end at "points left 0") |
| `CONTACT_EMAIL`, `CONTACT_CITY` | `NEXT_PUBLIC_CONTACT_EMAIL/CITY` (build arg and env) | **the deploy stops**: the policy pages must not show placeholders |

There is never a dev sign-in in production: it exists only with
`NODE_ENV=development`, and the image runs with `NODE_ENV=production`.
After changing the file: `FORCE=1 deploy/prod/deploy.sh` (re-ups the live
tag with the new values; no rebuild).

## First time

```sh
deploy/prod/install.sh        # .env + nightly backup timer (03:30 UTC)
deploy/prod/deploy.sh         # clone, build, migrate, start; ~10 min
deploy/prod/warm.sh           # fill the empty cache (detached; --status / --logs)
```

Then the tunnel: [TUNNEL.md](TUNNEL.md).

## Deploying

```sh
deploy/prod/deploy.sh                 # origin/main; no-op if it is already live
deploy/prod/deploy.sh <sha>           # an older main commit (rollback); refuses anything not on main
FORCE=1 deploy/prod/deploy.sh         # re-up the live tag (after editing secrets); skips the load check
REBUILD=1 deploy/prod/deploy.sh       # rebuild the images for the tag
```

What one run does, in order:

1. Takes a lock (`~/.local/share/holt-prod/lock`); a second run exits.
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
   Each new container starts next to the old one (`compose up --scale 2
   --no-recreate`); once its health check passes, the old one gets SIGTERM
   and is removed. Meanwhile both answer to the service's name: the edge
   re-resolves `web` every 2 s and tries the other address when one
   refuses, and web retries a dropped connection to `server` once
   (`web/src/lib/upstream-retry.ts`). A new container that never gets
   healthy is removed and the old one keeps serving. Then `compose up -d`
   for the rest (db, edge, umami). If web still can't be reached, the edge
   shows the [updating page](#the-updating-page) instead of Cloudflare's 502.
7. Health check: `/` answers 200 and `POST /api/analyses` for
   `pallets/flask` is accepted (200/202), within 5 minutes.
8. On failure: the same swap back to the previous tag, checks again, records
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
       docker compose -p holt-prod -f $P/compose.yml --env-file $S/.env "$@"; }

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
the server's environment; jobs go through the queue at badge priority, one
at a time, so people's requests always run first. Costs roughly 5,000 to
10,000 GitHub GraphQL points (about two token-hours); it stops by itself
under `HOLT_WARM_MIN_POINTS` and picks up where it left off next time.

```sh
deploy/prod/warm.sh --dry-run
deploy/prod/warm.sh                 # then --status or --logs
```

**After a deploy that changes the engine** (`ENGINE_VERSION` in
`src/holt/engine_version.py` went up), every stored report from the old
engine is out of date. Nobody is served one: report pages re-run it, the
badge and the extension say "updating", and Discover and recommendations
leave it out until it is redone. To redo the seed list's reports straight
away rather than as people visit, run the stale-only pass once the deploy
is up:

```sh
deploy/prod/warm.sh --dry-run --stale-only   # "would analyse …" per outdated seed
deploy/prod/warm.sh --stale-only             # then --status or --logs
```

## Checks after a deploy

```sh
H=http://127.0.0.1:8310
curl -sI $H/ | head -3
curl -s $H/robots.txt                                # Allow: / … Sitemap: https://githolt.com/sitemap.xml
curl -s $H/sitemap.xml | head -5
curl -sI $H/hacktoberfest | head -1
curl -sI -H 'Host: www.githolt.com' $H/ | grep -i location     # https://githolt.com/
curl -s -XPOST $H/api/analyses -H 'content-type: application/json' -d '{"repo":"pallets/flask"}'
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
`127.0.0.1:$PORT`: every answer should be a 200/202 (or a 429 from the rate
limit), never a 502 or the updating page.

The edge step alone needs no images: point `HOLT_PROD_HOME` at a scratch
directory with a `.env` (the `:?` variables set to anything,
`HOLT_PROD_PORT=$PORT`) and `src/deploy/prod/edge.conf`, source `edge.sh`,
define `compose` as `deploy.sh` does, then `edge_seed`, `compose up -d
--no-deps edge`, edit that `edge.conf` and `edge_apply`, with a `curl` loop
on the port to show it never drops.

## Removing it

```sh
systemctl --user disable --now holt-prod-backup.timer
dc down            # add -v to drop the database too (take a backup first)
docker buildx rm holt-prod
docker image prune -af --filter label=holt.stack=holt-prod
rm -rf ~/.local/share/holt-prod ~/.config/systemd/user/holt-prod-backup.*
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

