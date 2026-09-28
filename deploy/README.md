# Deploying Holt

Container images, the staging preview and the production stack for the web
app and API server.

| Path | What |
|---|---|
| `server/Dockerfile` | API server (`server/`) plus the engine (`src/holt`). uv, slim Python, non-root. Build context: repo root. |
| `web/Dockerfile` | Web app (`web/`). Next.js standalone output when `web/next.config` sets `output: "standalone"`, otherwise `next start` with production `node_modules`. Build context: `web/`. |
| `staging/compose.yml` | The staging stack, compose project `stage-holt-new`: Postgres, one-shot web and server migrations, server, web, and a small nginx `edge` that serves `/__build` and proxies everything else to web. Only `edge` publishes a port, on `127.0.0.1:9110`. Every URL in it comes from `STAGING_HOST`. |
| `staging/preview.sh` | One update: build `origin/main` + every open PR labelled `staging` + `staging/extra-branches`, run the migrations, swap server and web with no gap (`swap.sh`). |
| `staging/install.sh` | One-time setup: the timer's copy of `preview.sh` (and `edge.sh`, `swap.sh`) and the systemd `--user` timer (every 3 minutes). It does not touch the public route. |
| `edge.sh` | Sourced by `prod/deploy.sh` and `staging/preview.sh`: when `edge.conf` changed, checks it with `nginx -t` in the running edge and reloads it (the port stays open); a rejected config is put back and the run fails. |
| `swap.sh` | Sourced by `prod/deploy.sh` and `staging/preview.sh`: `swap_service` replaces a service's container with no gap (the new one starts beside the old one; the old one goes once the new one is healthy). The edges also show a "Holt is updating" page (503, never cached) if web can't be reached; see [`prod/README.md`](prod/README.md#the-updating-page). |
| `staging/compose.pro.yml` | The optional paid-features service beside staging, compose project `stage-holt-pro`, joined to the staging network as `pro`, no published port. `preview.sh` runs it; see "Paid features". |
| `staging/make-env.sh` | Writes `staging/.env` (gitignored): random keys, `gh auth token` (overridden on each run, see "The GitHub token"), `STAGING_HOST`. |
| `prod/` | Production, https://githolt.com: compose project `holt-prod` on `127.0.0.1:8310` behind a Cloudflare tunnel, built only from `origin/main` by `prod/deploy.sh` (never on a timer), nightly backups. See [`prod/README.md`](prod/README.md) and [`prod/TUNNEL.md`](prod/TUNNEL.md). |

## Staging: https://staging.githolt.com

It shows **origin/main merged with every open PR that has the `staging`
label**, rebuilt automatically within a few minutes of a push. To put a PR
on staging, add the label; to take it off, remove it. A branch with no PR
yet can go in `staging/extra-branches` (on main or in a labelled PR).
A PR that conflicts is left out and the reason is shown on `/__build`.

**What's live:** https://staging.githolt.com/__build lists the main
commit, each included PR and its commit, skipped ones with the reason, the
build time, the smoke-test result for that build (`"smoke"`: passed or
failed, with each failing test), and the last attempt (building / waiting /
failed + why).

Staging is never indexed (`ROBOTS_NOINDEX=1` at build and run time), and it
shares nothing with production: its own database, keys, images and builder.

### The host: one setting

`STAGING_HOST` (default `staging.githolt.com`) is the only place the
address is written. It is a bare host name, no `https://` and no path.

| Made from it | Where | Value |
|---|---|---|
| `NEXT_PUBLIC_SITE_HOST` (build arg and runtime) | `compose.yml` | `$STAGING_HOST` |
| `HOLT_WEB_URL` (server) | `compose.yml` | `https://$STAGING_HOST` |
| `AUTH_URL` (web, the OAuth callback base) | `compose.yml` | `https://$STAGING_HOST` |
| `"site"` on `/__build` | `preview.sh` | `https://$STAGING_HOST` |
| `BASE_URL` of the smoke run | `preview.sh` | `https://$STAGING_HOST` |

It is read from `STAGING_HOST=` in `staging/.env`; without that line the
default applies. An exported `STAGING_HOST` wins for that one run (and is
what `make-env.sh` writes into a new `.env`). To change it, edit the line;
the next tick notices and rebuilds. `HOLT_WEB_URL` and
`NEXT_PUBLIC_SITE_HOST` lines in an older `.env` are ignored.

`preview.sh` refuses a value that isn't a host name, and refuses
`githolt.com` and `www.githolt.com`: staging never answers as production.
Outside the stack, `e2e/` uses the same default and also reads
`STAGING_HOST` (`BASE_URL` still wins).

### The public route

The stack listens only on `127.0.0.1:9110`. A Cloudflare tunnel is the way
in, and `~/.cloudflared/` is hand-managed: nothing under `deploy/` reads or
writes it. What the route needs, in the tunnel that serves the githolt.com
zone:

```yaml
# above the catch-all `- service: http_status:404`
  - hostname: staging.githolt.com
    service: http://127.0.0.1:9110
```

and a proxied CNAME `staging` in the githolt.com zone pointing at that
tunnel (`cloudflared tunnel route dns <tunnel> staging.githolt.com` writes
it), then a restart of that tunnel. Check it:

```sh
curl -s https://staging.githolt.com/__build | jq -r .site    # https://staging.githolt.com
curl -s https://staging.githolt.com/robots.txt               # Disallow: /
```

The web app trusts `CF-Connecting-IP` (`TRUST_PROXY_HEADERS=1`) for rate
limits. That is safe only while the edge stays on 127.0.0.1 and the tunnel
is the sole way in; never publish 9110 on another address.

### Sign-in on staging

Off by default: staging is anonymous, rules reports work, and `/signin`
says each sign-in "isn't set up here". To turn one on, make an OAuth app
**for staging only** and put its keys in `~/.config/holt/secrets.env`:

| In `secrets.env` | Becomes | Callback URL to register |
|---|---|---|
| `STAGING_GITHUB_OAUTH_ID`, `STAGING_GITHUB_OAUTH_SECRET` | `AUTH_GITHUB_ID/SECRET` | `https://staging.githolt.com/api/auth/callback/github` |
| `STAGING_GOOGLE_OAUTH_ID`, `STAGING_GOOGLE_OAUTH_SECRET` | `AUTH_GOOGLE_ID/SECRET` | `https://staging.githolt.com/api/auth/callback/google` |

Then `FORCE=1 ~/.local/share/holt-staging/bin/preview.sh`; its log says
`GitHub sign-in: on` or why it is off.

- Never reuse production's OAuth keys. `preview.sh` does not read
  `GITHUB_OAUTH_*` / `GOOGLE_OAUTH_*` for staging, and if a `STAGING_*`
  value is the same as production's it leaves that sign-in off and says so.
- Both halves of a pair are needed; one without the other is off.
- `secrets.env` is the only source. `AUTH_*` lines in `staging/.env` or in
  the environment of whoever runs the script are overridden.
- Accounts made on staging live in staging's database only.

### The GitHub token

Every run reads the server's GitHub token fresh, as production does:
`GITHUB_TOKENS` from `~/.config/holt/secrets.env`, else the current
`gh auth token`. It overrides the `GITHUB_TOKENS` line `make-env.sh` wrote
into `staging/.env` once, so rotating a token needs no new `.env` (and
re-running `make-env.sh --force` would regenerate the database password and
auth secrets). The log says which source it used, never the value.

Before building, each token is checked against GitHub's API. One GitHub
refuses (401: revoked or expired) stops the run with `GitHub refused token
<n> in GITHUB_TOKENS`, also shown on `/__build` under `last_attempt`, and
the next tick tries again, so fixing `secrets.env` or `gh auth login` is
enough. Any other answer, or no answer, doesn't block the build.

### Behind Cloudflare Access

When staging sits behind Cloudflare Access (email one-time PIN for people),
the smoke run after each build still needs to get in. Give it a **service
token**:

1. Zero Trust → Access → Service credentials → Service Tokens → create one
   (for example `holt-staging-smoke`).
2. In the staging application, add a policy with the action **Service
   Auth** that includes that token.
3. Put the token in `~/.config/holt/secrets.env`:

   ```sh
   STAGING_CF_ACCESS_CLIENT_ID=<client id>.access
   STAGING_CF_ACCESS_CLIENT_SECRET=<client secret>
   ```

`preview.sh` reads the two keys on every run and hands them to the smoke
run's command only (never to the stack, never to a log). Its log says
`smoke: through Cloudflare Access with the service token`, or, with just
one of the two keys, that both are needed. Without them the smoke run is
the same as before (and, once Access is on, fails on the login page).

`e2e/` doesn't send the token on page loads: it trades it once for Access's
session cookie and gives the browser only that cookie, set for the staging
host alone, so neither the token nor the cookie reaches github.com or any
other site. See [`e2e/README.md`](../e2e/README.md).

The `curl` checks above then need the token too:

```sh
export $(grep '^STAGING_CF_ACCESS_' ~/.config/holt/secrets.env | xargs)   # just these two keys
curl -s -H "CF-Access-Client-Id: $STAGING_CF_ACCESS_CLIENT_ID" \
        -H "CF-Access-Client-Secret: $STAGING_CF_ACCESS_CLIENT_SECRET" \
        https://staging.githolt.com/__build | jq -r .site
```

`preview.sh` runs from the copy `install.sh` made, so after changing it
re-run `deploy/staging/install.sh`.

### Paid features

Paid features run in an optional internal service, a separate private
program the server calls over the Docker network (`HOLT_PRO_URL`,
`HOLT_PRO_KEY`; see [`server/README.md`](../server/README.md)). On staging
it runs only when its private checkout exists at `~/projects/holt-pro`
(`HOLT_PRO_REPO` overrides the path). Without it, staging works as before
and paid features say "not available yet".

`preview.sh` keeps a clone of that checkout's `origin/main` in
`~/.local/share/holt-staging/pro-src`, and a new commit there triggers a
rebuild like a change to main. It builds the image after server and web,
then runs it as its own compose project, `stage-holt-pro`
([`staging/compose.pro.yml`](staging/compose.pro.yml)), on the staging
stack's network as `pro`, with no published port and a 256m memory limit.
It is not part of `stage-holt-new`, whose `up --remove-orphans` would
remove it. Any problem with it (no key, no database, a failed build) leaves
paid features off and the rest of staging untouched; the log says why
(`paid features: on` / `off (...)`).

**One-time setup (you do this):**

1. Make the service's database in the staging Postgres. A database volume
   created from now on gets it from `staging/initdb/20-pro-db.sh`; the
   running one needs it once:

   ```sh
   docker exec stage-holt-new-db-1 psql -U holt -d holt -c 'CREATE DATABASE holt_pro'
   ```

2. Add a staging key to `~/.config/holt/secrets.env`. It must differ from
   production's `HOLT_PRO_KEY` (the same value is refused):

   ```sh
   echo "STAGING_HOLT_PRO_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(24))')" >> ~/.config/holt/secrets.env
   ```

3. Re-run `deploy/staging/install.sh` (the timer's copy of `preview.sh`),
   then `FORCE=1 ~/.local/share/holt-staging/bin/preview.sh`.

Check it (the server logs one line at startup, and can ping on demand):

```sh
docker logs stage-holt-new-server-1 2>&1 | grep holt-pro    # holt-pro: ok at http://pro:8000 (...)
docker exec stage-holt-new-server-1 python -m holt_server.pro
```

To take it away: remove `STAGING_HOLT_PRO_KEY`, run `preview.sh` with
`FORCE=1`, then `docker compose -p stage-holt-pro down`.

### How it runs

- Everything lives in `~/.local/share/holt-staging/`: `src/` is a dedicated
  clone checked out at the preview commit, `src/deploy/staging/.env` holds
  the secrets and `STAGING_HOST`, `logs/` keeps the last 10 build logs,
  `fingerprint` is what was last built.
- The timer runs `~/.local/share/holt-staging/bin/preview.sh` (a copy, so a
  PR can't change the loop; re-run `install.sh` after editing it or
  `deploy/edge.sh`).
- The edge reads its nginx config from `~/.local/share/holt-staging/edge/`
  (`HOLT_STAGE_EDGE_DIR`), a copy of the preview's `staging/edge.conf`.
  When that changes, `preview.sh` runs `nginx -t` in the running edge and
  reloads it; a rejected config is put back and the run fails
  (`EDGE CONFIG NOT APPLIED` on `/__build`). A timer copy from before this
  stops at `compose up` with "set by preview.sh; re-run
  deploy/staging/install.sh", leaving the running stack as it was.
- A run does nothing unless main, a labelled PR, an extra branch or
  `STAGING_HOST` moved.
- Builds never overlap (`flock`), and wait until the 1-minute load is under
  6 and MemAvailable is over 3 GB (for up to 30 minutes; then the next tick
  tries again).
- Images build on a buildx builder of its own (`holt-stage`, 3 GB memory
  cap), so after each build it prunes only its own cache and only images
  labelled `holt.stage=holt-new` (the label comes from `compose.yml`, so
  production images, labelled `holt.stack=holt-prod`, are never touched).
  It never prunes anything else.
- The names `stage-holt-new` and `holt.stage=holt-new` come from the site's
  first address. They are only names, and they stay: renaming the compose
  project would start a second stack with an empty database.
- After each build goes live it runs the `e2e/` smoke suite once against the
  public URL (one browser, `--workers=1`). A failure does not roll back; it
  shows on `/__build`. Set `HOLT_STAGE_SMOKE=0` in the environment of the
  service to skip it.
- Memory limits: web 512m, server 512m, db 256m, edge 32m, and the
  paid-features service 256m when it runs.
- The policy pages' contact details (`CONTACT_EMAIL`, `CONTACT_CITY`) are
  read from `~/.config/holt/secrets.env` on every run, the same file
  production uses. Besides those two, only the `STAGING_*` keys above are
  taken from it. Without the contact details the build fails on purpose
  rather than showing the placeholders.
- AI reports answer "needs a key" until `OPENROUTER_API_KEY` is set in
  `.env` (then `FORCE=1 preview.sh`).

### Commands

```sh
# first time (clones, builds, starts the timer); the route is separate, see above
deploy/staging/install.sh
~/.local/share/holt-staging/bin/preview.sh          # first build now instead of waiting

# helper for the rest (by project name, so it needs no env)
dc() { docker compose -p stage-holt-new "$@"; }

# status
systemctl --user list-timers holt-stage.timer
curl -s https://staging.githolt.com/__build | jq '.site, .live.included, .last_attempt.status'
dc ps

# logs
journalctl --user -u holt-stage -f                 # the update loop
ls -t ~/.local/share/holt-staging/logs | head -2   # latest build and smoke logs
dc logs -f --tail 100 server web

# rebuild now (skips the load check)
FORCE=1 ~/.local/share/holt-staging/bin/preview.sh

# turn auto-update off / on
systemctl --user disable --now holt-stage.timer
systemctl --user enable --now holt-stage.timer

# stop the site (keeps data and the route; visitors get Cloudflare's 502)
dc stop
dc start
```

Start or recreate containers with `preview.sh`, not `dc up`: the script is
what supplies the contact details and the sign-in keys.

`.env` is kept across runs; `make-env.sh --force` regenerates it (this
drops saved BYOK keys, and the database password only applies to a fresh
volume, so also `dc down -v`).

### Tear-down

Removing staging completely, in this order. Each step names only things
that belong to staging; production (`holt-prod`) and every other container
on the box are not touched.

```sh
# 1. Stop the loop first, or the next tick builds it all again.
systemctl --user disable --now holt-stage.timer
systemctl --user stop holt-stage.service            # ends a run in progress

# 2. Optional: keep the data.
mkdir -p ~/backups/holt-staging
for d in holt holt_web; do
    docker compose -p stage-holt-new exec -T db pg_dump -U holt "$d" | gzip > ~/backups/holt-staging/$d.sql.gz
done

# 3. The stack: containers, network and the database volume.
docker compose -p stage-holt-new down -v

# 4. Its images, its builder and that builder's cache.
docker image rm stage-holt-new-server:latest stage-holt-new-web:latest
docker image prune -f --filter label=holt.stage=holt-new
docker buildx rm holt-stage

# 5. Its state (the clone, .env with staging's keys, logs) and the units.
rm -rf ~/.local/share/holt-staging
rm -f ~/.config/systemd/user/holt-stage.service ~/.config/systemd/user/holt-stage.timer
systemctl --user daemon-reload
```

Then, by hand:

6. **The route.** Remove the `staging.githolt.com` ingress rule from the
   tunnel config, restart that tunnel, and delete the `staging` CNAME in
   the githolt.com zone. Leave the `githolt.com` and `www` rules alone.
7. **The old address**, if it was never released:
   `~/staging/bin/stagectl release holt-new`.
8. **Sign-in.** Delete the `STAGING_*` lines from
   `~/.config/holt/secrets.env` (nothing else in that file: the rest is
   production's) and delete the staging OAuth apps at GitHub and Google.

Do not remove `postgres:16-alpine` or `nginx:1.27-alpine`, and do not run
`docker system prune` or `docker volume prune`: those images and volumes
are shared with production and other services.

Check that it is gone:

```sh
docker ps -a --filter label=holt.stage=holt-new --format '{{.Names}}'   # nothing
docker volume ls --filter name=stage-holt-new --format '{{.Name}}'      # nothing
ss -ltn | grep ':9110 '                                                 # nothing
systemctl --user list-timers --all | grep holt-stage                    # nothing
```

To bring it back: `deploy/staging/install.sh`, then the route.
