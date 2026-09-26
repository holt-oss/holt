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
| `deploy.sh` | One deploy: build main's images, migrate, swap, health-check, roll back on failure, prune only this stack's images. |
| `make-env.sh` | Writes `~/.local/share/holt-prod/.env` once: fresh `AUTH_SECRET`, `HOLT_INTERNAL_KEY`, `HOLT_SECRET_KEY`, db password. Nothing shared with staging. |
| `install.sh` | One-time: the env file plus the nightly backup timer. No deploy timer, on purpose. |
| `backup.sh` | `pg_dump` of both databases to `~/backups/holt/<stamp>/`, keeps 14 days. |
| `warm.sh` | Runs `python -m holt_server.warm` detached in the server image (fills the caches). |
| `edge.conf` | nginx: keeps the port across deploys, `/__build`, `www` → apex redirect, SSE-friendly proxy. |
| `migrate-web.sh`, `initdb/` | Auth.js tables migration (one-shot `migrate-web` service) and the `holt_web` database. |
| `TUNNEL.md` | Steps for the user to route githolt.com here. |

State lives in `~/.local/share/holt-prod/` (outside every checkout, so
removing a worktree can't delete secrets): `.env`, `src/` (a clone at the
deployed commit), `current` and `previous` (image tags), `build/build.json`
(served at `/__build`), `logs/`.

## Environment

Fixed in `compose.yml`: `HOLT_ENV=production`, `NEXT_PUBLIC_SITE_HOST=githolt.com`
(build and run time), `HOLT_WEB_URL` and `AUTH_URL=https://githolt.com`,
`TRUST_PROXY_HEADERS=1`, no `ROBOTS_NOINDEX` (production is indexed), no
`MOCK_API`. From `.env`: the generated secrets, `HOLT_STARTER_CACHE_HOURS=24`,
`HOLT_JOB_CONCURRENCY=1`, `HOLT_PROD_PORT=8310`.

Keys the user owns come from **`~/.config/holt/secrets.env`** (`KEY=value`
lines, `chmod 600`), read by `deploy.sh` on every run and mapped:

| In `secrets.env` | Becomes | When missing |
|---|---|---|
| `GITHUB_OAUTH_ID`, `GITHUB_OAUTH_SECRET` | `AUTH_GITHUB_ID/SECRET` | GitHub sign-in shows "isn't set up here" |
| `GOOGLE_OAUTH_ID`, `GOOGLE_OAUTH_SECRET` | `AUTH_GOOGLE_ID/SECRET` | Google sign-in shows "isn't set up here" |
| `OPENROUTER_API_KEY` | the same | AI reports answer `needs_key`; BYOK still works |
| `GITHUB_TOKENS` | the same | falls back to `gh auth token` |

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
   each file once; the API server's own tables are created on startup).
6. `compose up -d`: server is recreated and waited for healthy, then web.
   The edge keeps 127.0.0.1:8310 open throughout and re-resolves `web`, so
   the gap is the few seconds web takes to start.
7. Health check: `/` answers 200 and `POST /api/analyses` for
   `pallets/flask` is accepted (200/202), within 5 minutes.
8. On failure: `compose up -d` with the previous tag, checks again, records
   the failure on `/__build`, exits 1. On success: records `current`/`previous`.
9. Prunes only this stack: untag image tags other than current and previous,
   `docker image prune --filter label=holt.stack=holt-prod`, and the builder's
   cache over 3 GB. Nothing else on the box is touched.

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

## Removing it

```sh
systemctl --user disable --now holt-prod-backup.timer
dc down            # add -v to drop the database too (take a backup first)
docker buildx rm holt-prod
docker image prune -af --filter label=holt.stack=holt-prod
rm -rf ~/.local/share/holt-prod ~/.config/systemd/user/holt-prod-backup.*
```
