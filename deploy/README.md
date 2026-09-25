# Deploying Holt

Container images and the staging preview for the web app and API server.

| Path | What |
|---|---|
| `server/Dockerfile` | API server (`server/`) plus the engine (`src/holt`). uv, slim Python, non-root. Build context: repo root. |
| `web/Dockerfile` | Web app (`web/`). Next.js standalone output when `web/next.config` sets `output: "standalone"`, otherwise `next start` with production `node_modules`. Build context: `web/`. |
| `staging/compose.yml` | The staging stack, compose project `stage-holt-new`: Postgres, a one-shot web migration, server, web, and a small nginx `edge` that serves `/__build` and proxies everything else to web. Only `edge` publishes a port, on `127.0.0.1:9110`. |
| `staging/preview.sh` | One update: build `origin/main` + every open PR labelled `staging` + `staging/extra-branches`, restart the stack. |
| `staging/install.sh` | One-time setup: systemd `--user` timer (every 3 minutes) and the `stagectl` route. |
| `staging/make-env.sh` | Writes `staging/.env` (gitignored): random keys, `gh auth token`, site URLs. |

## Staging: https://holt-new.aahil-khan.xyz

It shows **origin/main merged with every open PR that has the `staging`
label**, rebuilt automatically within a few minutes of a push. To put a PR
on staging, add the label; to take it off, remove it. A branch with no PR
yet can go in `staging/extra-branches` (on main or in a labelled PR).
A PR that conflicts is left out and the reason is shown on `/__build`.

**What's live:** https://holt-new.aahil-khan.xyz/__build lists the main
commit, each included PR and its commit, skipped ones with the reason, the
build time, the smoke-test result for that build (`"smoke"`: passed or
failed, with each failing test), and the last attempt (building / waiting /
failed + why).

### How it runs

- Everything lives in `~/.local/share/holt-staging/`: `src/` is a dedicated
  clone checked out at the preview commit, `src/deploy/staging/.env` holds
  the secrets, `logs/` keeps the last 10 build logs, `fingerprint` is what
  was last built.
- The timer runs `~/.local/share/holt-staging/bin/preview.sh` (a copy, so a
  PR can't change the loop; re-run `install.sh` after editing it).
- A run does nothing unless main, a labelled PR or an extra branch moved.
- Builds never overlap (`flock`), and wait until the 1-minute load is under
  6 and MemAvailable is over 3 GB (for up to 30 minutes; then the next tick
  tries again).
- Images build on a buildx builder of its own (`holt-stage`, 3 GB memory
  cap), so after each build it prunes only its own cache and only images
  labelled `holt.stage=holt-new`. It never prunes anything else.
- After each build goes live it runs the `e2e/` smoke suite once against the
  public URL (one browser, `--workers=1`). A failure does not roll back; it
  shows on `/__build`. Set `HOLT_STAGE_SMOKE=0` in the environment of the
  service to skip it.
- Memory limits: web 512m, server 512m, db 256m, edge 32m.
- Sign-in has no OAuth app yet, so staging is anonymous: rules reports work,
  AI reports answer "needs a key". Add `AUTH_GITHUB_ID/SECRET` or
  `OPENROUTER_API_KEY` to `.env` and run `FORCE=1 preview.sh` to change that.

### Commands

```sh
# first time (clones, builds, routes the subdomain, starts the timer)
deploy/staging/install.sh
~/.local/share/holt-staging/bin/preview.sh          # first build now instead of waiting

# helper for the rest
S=~/.local/share/holt-staging/src/deploy/staging
dc() { docker compose -p stage-holt-new -f $S/compose.yml --env-file $S/.env "$@"; }

# status
systemctl --user list-timers holt-stage.timer
curl -s https://holt-new.aahil-khan.xyz/__build | jq '.live.included, .last_attempt.status'
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

# stop the site (keeps data and the URL; nginx shows "offline")
dc stop
dc start

# remove it completely
systemctl --user disable --now holt-stage.timer
dc down -v --rmi local
docker buildx rm holt-stage
~/staging/bin/stagectl release holt-new
rm -rf ~/.local/share/holt-staging ~/.config/systemd/user/holt-stage.*
```

`.env` is kept across runs; `make-env.sh --force` regenerates it (this
drops saved BYOK keys, and the database password only applies to a fresh
volume, so also `dc down -v`).
