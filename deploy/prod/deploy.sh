#!/usr/bin/env bash
# deploy.sh -- put origin/main on https://githolt.com (compose project holt-prod).
#
#   deploy/prod/deploy.sh             deploy origin/main (no-op when it is live)
#   deploy/prod/deploy.sh <sha>       deploy an older main commit (a rollback);
#                                     anything not on origin/main is refused
#   FORCE=1 deploy.sh                 re-up the live tag (new secrets/env), skip the load check
#   REBUILD=1 deploy.sh               rebuild the images even if the tag exists
#
# One run: fetch origin, check the commit is on main, wait until the box is
# quiet, build the server and web images one at a time (tagged with the
# commit SHA), run the one-shot web migration, swap the containers behind the
# edge (its port never moves), health-check on 127.0.0.1, and roll back to
# the previous tag if that fails. Then prune only this stack's images.
#
# Only the orchestrator runs it, when the user approves a deploy. Nothing
# runs it on a timer: production never auto-updates.
#
# State: ~/.local/share/holt-prod/  .env (make-env.sh), src/ (clone at the
# deployed commit), current + previous (image tags), build/build.json
# (served at /__build), logs/. Secrets that must not sit in .env come from
# ~/.config/holt/secrets.env when it exists (see README.md).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

here="$(cd "$(dirname "$0")" && pwd)"
STATE="${HOLT_PROD_HOME:-$HOME/.local/share/holt-prod}"
SRC="$STATE/src"
REPO="${HOLT_REPO:-holt-oss/holt}"
SECRETS="${HOLT_SECRETS_FILE:-$HOME/.config/holt/secrets.env}"
# HOLT_PROD_PROJECT: only for a rehearsal on a dev port (README.md); the
# builder, the label and the image names follow it, so the rehearsal and the
# real stack never share anything.
PROJECT="${HOLT_PROD_PROJECT:-holt-prod}"
LABEL="holt.stack=$PROJECT"
BUILDER="$PROJECT"
MAX_LOAD="${HOLT_PROD_MAX_LOAD:-6}"
MIN_AVAIL_MB="${HOLT_PROD_MIN_AVAIL_MB:-3072}"
MAX_WAIT="${HOLT_PROD_MAX_WAIT:-1800}"
HEALTH_WAIT="${HOLT_PROD_HEALTH_WAIT:-300}"
FORCE="${FORCE:-0}"
REBUILD="${REBUILD:-0}"
WANT="${1:-origin/main}"

mkdir -p "$STATE/logs" "$STATE/build"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

exec 9>"$STATE/lock"
flock -n 9 || die "another deploy is in progress"

# --- env and secrets ---------------------------------------------------------
[[ -f "$STATE/.env" ]] || "$here/make-env.sh"
port="$(sed -n 's/^HOLT_PROD_PORT=//p' "$STATE/.env")"; port="${port:-8310}"

# ~/.config/holt/secrets.env (optional, user-managed, KEY=value lines):
#   GITHUB_OAUTH_ID / GITHUB_OAUTH_SECRET  -> AUTH_GITHUB_ID / AUTH_GITHUB_SECRET
#   GOOGLE_OAUTH_ID / GOOGLE_OAUTH_SECRET  -> AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET
#   OPENROUTER_API_KEY, GITHUB_TOKENS      -> the same names
# Exported here, so they win over .env for compose. An unset key stays empty
# and the feature stays off (sign-in hidden, AI reports answer needs_key).
if [[ -f "$SECRETS" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"; line="${line#"${line%%[![:space:]]*}"}"
        [[ "$line" == *=* ]] || continue
        key="${line%%=*}"; val="${line#*=}"
        key="${key#export }"; key="${key%"${key##*[![:space:]]}"}"
        val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
        [[ "$val" == \"*\" || "$val" == \'*\' ]] && val="${val:1:${#val}-2}"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        export "$key=$val"
    done < "$SECRETS"
    log "using secrets from $SECRETS"
fi
export AUTH_GITHUB_ID="${AUTH_GITHUB_ID:-${GITHUB_OAUTH_ID:-}}"
export AUTH_GITHUB_SECRET="${AUTH_GITHUB_SECRET:-${GITHUB_OAUTH_SECRET:-}}"
export AUTH_GOOGLE_ID="${AUTH_GOOGLE_ID:-${GOOGLE_OAUTH_ID:-}}"
export AUTH_GOOGLE_SECRET="${AUTH_GOOGLE_SECRET:-${GOOGLE_OAUTH_SECRET:-}}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [[ -z "${GITHUB_TOKENS:-}" ]]; then
    GITHUB_TOKENS="$(gh auth token 2>/dev/null || true)"
    [[ -n "$GITHUB_TOKENS" ]] && log "GITHUB_TOKENS: using gh auth token (no secrets file entry)"
fi
export GITHUB_TOKENS
[[ -n "$GITHUB_TOKENS" ]] || die "no GitHub token: put GITHUB_TOKENS in $SECRETS or run gh auth login"
[[ -n "$AUTH_GITHUB_ID" ]] && log "GitHub sign-in: on" || log "GitHub sign-in: off (no GITHUB_OAUTH_ID)"
[[ -n "$AUTH_GOOGLE_ID" ]] && log "Google sign-in: on" || log "Google sign-in: off (no GOOGLE_OAUTH_ID)"
[[ -n "$OPENROUTER_API_KEY" ]] && log "server AI key: on" || log "server AI key: off (AI reports need BYOK)"

# --- the commit ----------------------------------------------------------------
if [[ ! -d "$SRC/.git" ]]; then
    log "cloning $REPO into $SRC"
    git clone -q "https://github.com/$REPO.git" "$SRC"
fi
git -C "$SRC" fetch -q --prune origin '+refs/heads/main:refs/remotes/origin/main'
main_sha="$(git -C "$SRC" rev-parse refs/remotes/origin/main)"
sha="$(git -C "$SRC" rev-parse --verify -q "${WANT}^{commit}")" || die "unknown commit: $WANT"
git -C "$SRC" merge-base --is-ancestor "$sha" "$main_sha" \
    || die "$WANT (${sha:0:7}) is not on origin/main; production builds only from main"
git -C "$SRC" checkout -q -f --detach "$sha"
short="${sha:0:7}"

current="$(cat "$STATE/current" 2>/dev/null || true)"
if [[ "$sha" == "$current" && "$FORCE" != 1 && "$REBUILD" != 1 ]]; then
    log "$short is already live on 127.0.0.1:$port (FORCE=1 to re-up)"; exit 0
fi
[[ "$sha" == "$main_sha" ]] || log "note: deploying ${short}, which is behind origin/main (${main_sha:0:7})"

# --- compose --------------------------------------------------------------------
export HOLT_SRC="$SRC" HOLT_TAG="$sha" HOLT_PROD_HOME="$STATE"
export COMPOSE_PROJECT_NAME="$PROJECT" HOLT_PROD_PROJECT="$PROJECT" BUILDX_BUILDER="$BUILDER"
compose() { docker compose -p "$PROJECT" -f "$here/compose.yml" --env-file "$STATE/.env" "$@"; }
dlog="$STATE/logs/deploy-$(date -u +%Y%m%dT%H%M%SZ)-$short.log"
log "log: $dlog"

write_build_json() {   # status message
    STATUS="$1" MESSAGE="$2" SHA="$sha" MAIN="$main_sha" STATE="$STATE" REPO="$REPO" \
    OUT="$STATE/build/build.json" python3 - <<'PY'
import json, os, datetime
env = os.environ
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
commit = {"sha": env["SHA"], "short": env["SHA"][:7],
          "url": f"https://github.com/{env['REPO']}/commit/{env['SHA']}"}
attempt = {"status": env["STATUS"], "message": env["MESSAGE"], "at": now, "main": commit,
           "origin_main": env["MAIN"][:7], "included": []}
live_path = os.path.join(env["STATE"], "live.json")
if env["STATUS"] == "live":
    live = {"main": commit, "tag": env["SHA"], "included": [], "built_at": now}
    with open(live_path, "w", encoding="utf-8") as f:
        json.dump(live, f, indent=2)
try:
    with open(live_path, encoding="utf-8") as f:
        live = json.load(f)
except FileNotFoundError:
    live = None
doc = {"site": "https://githolt.com", "live": live, "last_attempt": attempt}
tmp = env["OUT"] + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2); f.write("\n")
os.replace(tmp, env["OUT"])
PY
}

healthy() {   # the site answers on 127.0.0.1 within $HEALTH_WAIT seconds
    local deadline=$((SECONDS + HEALTH_WAIT)) code=
    while (( SECONDS < deadline )); do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/" || true)"
        if [[ "$code" == 200 ]]; then
            # The API behind it too: an anonymous rules request must be accepted or served.
            code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
                    -H 'content-type: application/json' -d '{"repo":"pallets/flask"}' \
                    "http://127.0.0.1:$port/api/analyses" || true)"
            [[ "$code" == 200 || "$code" == 202 ]] && return 0
        fi
        sleep 5
    done
    log "health check failed (last status $code)"; return 1
}

# --- wait for room ---------------------------------------------------------------
if [[ "$FORCE" != 1 ]]; then
    waited=0
    while :; do
        load="$(cut -d' ' -f1 /proc/loadavg)"
        avail="$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
        awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l < m)}' && (( avail > MIN_AVAIL_MB )) && break
        (( waited >= MAX_WAIT )) && die "still busy after ${MAX_WAIT}s (load $load, ${avail} MB free); try again later"
        (( waited == 0 )) && log "waiting for room: load $load (< $MAX_LOAD), MemAvailable ${avail} MB (> $MIN_AVAIL_MB)"
        sleep 30; waited=$((waited + 30))
    done
fi

# --- build -----------------------------------------------------------------------
have_images() { docker image inspect "$PROJECT-server:$sha" "$PROJECT-web:$sha" >/dev/null 2>&1; }
if [[ "$REBUILD" == 1 ]] || ! have_images; then
    if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
        # A builder of our own: its cache can be pruned without touching anyone else's.
        docker buildx create --name "$BUILDER" --driver docker-container \
            --driver-opt memory=3g --driver-opt "env.BUILDKIT_STEP_LOG_MAX_SIZE=10485760" >/dev/null
    fi
    write_build_json building "building $short"
    for svc in server web; do   # one at a time: two builds at once is too much for this box
        log "building $svc image $PROJECT-$svc:$short"
        compose build "$svc" >>"$dlog" 2>&1 \
            || die "$svc image build failed; last lines: $(tail -5 "$dlog" | tr '\n' ' ' | cut -c1-600)"
    done
else
    log "images for $short exist; not rebuilding (REBUILD=1 to force)"
fi

# --- migrate, swap, check, roll back ------------------------------------------------
log "starting db and applying web migrations"
compose up -d db >>"$dlog" 2>&1
compose --profile migrate run --rm migrate-web >>"$dlog" 2>&1 || die "web migration failed; see $dlog"

write_build_json deploying "starting $short"
log "swapping containers to $short (previous: ${current:0:7})"
compose up -d --remove-orphans >>"$dlog" 2>&1 || die "compose up failed; see $dlog"

if healthy; then
    [[ -n "$current" && "$current" != "$sha" ]] && echo "$current" > "$STATE/previous"
    echo "$sha" > "$STATE/current"
    write_build_json live "live"
    log "live: $short on 127.0.0.1:$port"
else
    compose logs --tail 50 server web >>"$dlog" 2>&1 || true
    if [[ -n "$current" && "$current" != "$sha" ]]; then
        log "rolling back to ${current:0:7}"
        HOLT_TAG="$current" compose up -d --remove-orphans >>"$dlog" 2>&1 || true
        if healthy; then
            write_build_json failed "$short failed its health check; rolled back to ${current:0:7}"
            die "$short failed its health check; rolled back to ${current:0:7} (see $dlog)"
        fi
        write_build_json failed "$short failed its health check and the rollback to ${current:0:7} is not healthy either"
        die "rollback to ${current:0:7} is not healthy either; see $dlog and 'compose ps'"
    fi
    write_build_json failed "$short failed its health check (nothing to roll back to)"
    die "$short failed its health check and there is no previous release; see $dlog"
fi

# --- clean up after ourselves only --------------------------------------------------
# Keep the live and the previous tag (the rollback target); untag older ones
# of this stack, then prune only images labelled holt.stack=prod and only this
# builder's cache. Nothing else on the box is touched.
keep=" $sha $(cat "$STATE/previous" 2>/dev/null || true) "
for img in $(docker images --filter "label=$LABEL" --format '{{.Repository}}:{{.Tag}}' | grep -E "^$PROJECT-(server|web):[0-9a-f]{40}\$"); do
    [[ "$keep" == *" ${img#*:} "* ]] || docker image rm "$img" >/dev/null 2>&1 || true
done
docker image prune -f --filter "label=$LABEL" >/dev/null || true
docker buildx prune --builder "$BUILDER" -f --max-used-space 3gb >/dev/null 2>&1 || true
ls -1t "$STATE"/logs/deploy-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
