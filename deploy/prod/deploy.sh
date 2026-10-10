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
# commit SHA), run the one-shot web and server migrations, swap server then
# web with no gap (the new containers start beside the old ones and take
# over once every one of them is healthy; ../swap.sh), health-check on
# 127.0.0.1 and in each web container, and swap back to the previous tag if
# that fails. web runs HOLT_WEB_REPLICAS containers (.env; default 2, at
# most 3). Then, when the commit's edge.conf differs
# from the edge's, check it with nginx -t in the running edge and reload it
# (never a restart); a rejected config is put back and the run fails. Then
# prune only this stack's images.
#
# follow.sh (the holt-prod-follow timer, install-follow.sh) runs it for each
# new main commit once CI and staging are green on it; by hand it works as
# before (README.md, "Deploying").
#
# Exit status: 0 live (or already live), 75 didn't start (another deploy
# holds the lock, or the box stayed busy; try again later), 1 failed.
#
# State: ~/.local/share/holt-prod/  .env (make-env.sh), src/ (clone at the
# deployed commit), current + previous (image tags), build/build.json
# (served at /__build), edge/default.conf (the edge's live nginx config, a
# copy of src/deploy/prod/edge.conf), logs/. Secrets that must not sit in
# .env come from ~/.config/holt/secrets.env when it exists (see README.md).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

here="$(cd "$(dirname "$0")" && pwd)"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }
busy() { log "ERROR: $*"; exit 75; }   # not a failure of the commit: nothing was changed
# shellcheck source=env.sh
. "$here/env.sh"   # STATE, PROJECT, SECRETS, load_prod_env, env_value
# shellcheck source=../edge.sh
. "$here/../edge.sh"   # edge_seed, edge_apply, edge_revert
# shellcheck source=../swap.sh
. "$here/../swap.sh"   # swap_service
SRC="$STATE/src"
REPO="${HOLT_REPO:-holt-oss/holt}"
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

exec 9>"$STATE/lock"
flock -n 9 || busy "another deploy is in progress"

# --- env and secrets ---------------------------------------------------------
[[ -f "$STATE/.env" ]] || "$here/make-env.sh"
port="$(sed -n 's/^HOLT_PROD_PORT=//p' "$STATE/.env")"; port="${port:-8310}"
# How many web containers (compose.yml, `deploy.replicas`). Three at most:
# the db's max_connections is sized for that many.
replicas="$(env_value HOLT_WEB_REPLICAS 2)"
[[ "$replicas" =~ ^[1-3]$ ]] \
    || die "HOLT_WEB_REPLICAS must be 1, 2 or 3, not '$replicas' (the db's max_connections in compose.yml is sized for three)"
export HOLT_WEB_REPLICAS="$replicas"
# CPU shares for db, server, web and edge (prioritise, below). A container's
# default is 1024; 8192 is about five times its weight when the box is busy.
# A rehearsal under another project name gets no priority.
default_shares=8192; [[ "$PROJECT" == holt-prod ]] || default_shares=1024
CPU_SHARES="$(env_value HOLT_PROD_CPU_SHARES "$default_shares")"
[[ "$CPU_SHARES" =~ ^[0-9]+$ ]] && (( CPU_SHARES >= 2 && CPU_SHARES <= 262144 )) \
    || die "HOLT_PROD_CPU_SHARES must be a number from 2 to 262144, not '$CPU_SHARES'"

# Secrets and the GitHub token (env.sh). The contact details are checked
# here because only the web build needs them: the policy pages must never
# show placeholders, so a deploy without them stops before building.
load_prod_env
[[ -n "$AUTH_GITHUB_ID" ]] && log "GitHub sign-in: on" || log "GitHub sign-in: off (no GITHUB_OAUTH_ID)"
[[ -n "$AUTH_GOOGLE_ID" ]] && log "Google sign-in: on" || log "Google sign-in: off (no GOOGLE_OAUTH_ID)"
[[ -n "$OPENROUTER_API_KEY" ]] && log "server AI key: on" || log "server AI key: off (AI reports need BYOK)"
# AI spend needs a budget, and in production the owner's explicit say-so too.
if [[ "${HOLT_PROD_AI_BUDGET_USD:-0}" =~ ^0*(\.0*)?$ ]]; then
    log "AI budget: 0 (AI off)"
elif [[ "${HOLT_PROD_AI_BUDGET_OWNER_OK:-}" != 1 ]]; then
    die "HOLT_PROD_AI_BUDGET_USD is set without HOLT_PROD_AI_BUDGET_OWNER_OK=1; production AI needs the owner's explicit setting"
else
    log "AI budget: \$$HOLT_PROD_AI_BUDGET_USD (owner-approved)"
fi
# Pass sales (README.md, "Selling passes"): off unless HOLT_PROD_PAYMENTS=1,
# and then only with live Razorpay keys.
(( PAYMENTS_OK )) || die "$PAYMENTS_MSG; nothing was changed (README.md, \"Selling passes\")"
log "$PAYMENTS_MSG"
for k in CONTACT_EMAIL CONTACT_CITY; do
    v="NEXT_PUBLIC_$k"
    [[ -n "${!v}" && "${!v}" != "$k" ]] || die "$k is not set in $SECRETS; the policy pages (/terms, /privacy, /refunds, /contact) would show the placeholder"
done
log "contact: $NEXT_PUBLIC_CONTACT_EMAIL, $NEXT_PUBLIC_CONTACT_CITY"
log "web containers: $replicas; CPU shares: $CPU_SHARES"

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
# The compose file: this checkout's for the deploy; the rollback uses the
# file the previous release was started with (releases/<sha>/compose.yml,
# kept below), so a commit that breaks compose.yml can still be rolled back.
# The project directory (where ./initdb and ./migrate-web.sh resolve) is the
# state clone, whichever checkout runs this: a bind mount whose source path
# changes makes compose recreate the container, and the db must not be
# recreated because follow.sh and a person deploy from different checkouts.
COMPOSE_YML="$here/compose.yml"
RELEASES="$STATE/releases"
compose() { docker compose -p "$PROJECT" -f "$COMPOSE_YML" --project-directory "$SRC/deploy/prod" --env-file "$STATE/.env" "$@"; }
# release_compose <sha>: the compose file <sha> went live with, else the
# one in its commit (releases before this existed), else nothing.
release_compose() {
    if [[ -f "$RELEASES/$1/compose.yml" ]]; then echo "$RELEASES/$1/compose.yml"; return; fi
    mkdir -p "$RELEASES/$1"
    git -C "$SRC" show "$1:deploy/prod/compose.yml" > "$RELEASES/$1/compose.yml.tmp" 2>/dev/null \
        && mv "$RELEASES/$1/compose.yml.tmp" "$RELEASES/$1/compose.yml" \
        && echo "$RELEASES/$1/compose.yml" && return
    rm -rf "$RELEASES/$1"
}
EDGE_CONF="$SRC/deploy/prod/edge.conf"   # the deployed commit's; the edge reads a copy in $STATE/edge
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
try:   # follow.sh's status (the auto-deploy) stays on /__build
    with open(env["OUT"], encoding="utf-8") as f:
        auto = json.load(f).get("autodeploy")
    if auto:
        doc["autodeploy"] = auto
except (FileNotFoundError, ValueError):
    pass
tmp = env["OUT"] + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2); f.write("\n")
os.replace(tmp, env["OUT"])
PY
}

# The two checks of healthy(), from inside one web container on its own
# port: a request through the edge reaches only one of them.
REPLICA_CHECK='
const get = (path) => fetch("http://127.0.0.1:3000" + path, { signal: AbortSignal.timeout(20000) }).then((r) => r.status);
Promise.all([get("/"), get("/api/public/report/pallets/flask")]).then(
  ([home, api]) => process.exit(home === 200 && (api === 200 || api === 404) ? 0 : 1),
  () => process.exit(1));'
replicas_healthy() {   # every web container answers; sets $sick to the one that doesn't
    local id n=0
    for id in $(_swap_ids web); do
        docker exec "$id" node -e "$REPLICA_CHECK" >/dev/null 2>&1 || { sick="web container ${id:0:12}"; return 1; }
        n=$((n + 1))
    done
    (( n > 0 )) || { sick="no web container"; return 1; }
    sick=
}

healthy() {   # the site and every web container answer within $HEALTH_WAIT seconds
    local deadline=$((SECONDS + HEALTH_WAIT)) code= sick=
    while (( SECONDS < deadline )); do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/" || true)"
        if [[ "$code" == 200 ]]; then
            # The API behind it too, through the extension's read-only proxy, which
            # stays open to signed-out callers and never starts an analysis: a cached
            # report (200) or the server's "no report yet" (404) proves web -> server
            # works; 502 is the server unreachable, 401 a bad internal key.
            code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
                    "http://127.0.0.1:$port/api/public/report/pallets/flask" || true)"
            if [[ "$code" == 200 || "$code" == 404 ]]; then replicas_healthy && return 0; fi
        fi
        sleep 5
    done
    log "health check failed (last status $code${sick:+; no answer from $sick})"; return 1
}

# --- wait for room ---------------------------------------------------------------
if [[ "$FORCE" != 1 ]]; then
    waited=0
    while :; do
        load="$(cut -d' ' -f1 /proc/loadavg)"
        avail="$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
        awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l < m)}' && (( avail > MIN_AVAIL_MB )) && break
        (( waited >= MAX_WAIT )) && busy "still busy after ${MAX_WAIT}s (load $load, ${avail} MB free); try again later"
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
    # The builder's container (buildx_buildkit_${BUILDER}0) idles at about
    # 660 MB once started; stop it when this run ends, however it ends. The
    # next build starts it again.
    trap 'docker buildx stop "$BUILDER" >/dev/null 2>&1 || true' EXIT
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
log "starting db and applying web and server migrations"
compose up -d db >>"$dlog" 2>&1
compose --profile migrate run --rm migrate-web >>"$dlog" 2>&1 || die "web migration failed; see $dlog"
compose --profile migrate run --rm migrate-server >>"$dlog" 2>&1 || die "server migration failed; see $dlog"

# The edge's config directory must exist before a (re)created edge starts.
edge_seed "$EDGE_CONF" "$STATE/edge" || die "$EDGE_MSG"
[[ -n "$EDGE_MSG" ]] && log "$EDGE_MSG"

# CPU priority, not a cap: when the box is busy the kernel shares CPU time
# between containers by these shares (a container's default is 1024), and
# when it isn't nothing changes. Set on the running containers, because
# cpu_shares in compose.yml would make compose recreate the db and the edge,
# which is a gap. Docker keeps it across restarts, and every deploy sets it
# on the containers it started. Not the warm pass (a one-off container).
prioritise() {
    local svc id
    for svc in db server web edge; do
        for id in $(_swap_ids "$svc"); do
            docker update --cpu-shares "$CPU_SHARES" "$id" >/dev/null 2>&1 \
                || log "note: couldn't set CPU shares on $svc (${id:0:12})"
        done
    done
    return 0
}

# Server, then web: the new containers start next to the old ones and take
# over once every one passes its health check, so the site never stops
# answering (../swap.sh). If one never gets healthy, all the new ones are
# removed and the old ones keep serving. Then `compose up` for the rest (db,
# edge, umami): server and web already match the config, so it leaves them
# alone.
swap_all() {   # log lines go to the deploy log and stdout
    local svc
    for svc in server web; do
        if ! swap_service "$svc" "$HEALTH_WAIT"; then log "$SWAP_MSG"; return 1; fi
        log "$SWAP_MSG"
    done
    compose up -d --remove-orphans >>"$dlog" 2>&1 || { log "compose up failed; see $dlog"; return 1; }
    prioritise
}

write_build_json deploying "starting $short"
log "swapping containers to $short (previous: ${current:0:7})"
swapped=0
swap_all && swapped=1

if (( swapped )) && healthy; then
    [[ -n "$current" && "$current" != "$sha" ]] && echo "$current" > "$STATE/previous"
    echo "$sha" > "$STATE/current"
    mkdir -p "$RELEASES/$sha" && cp "$COMPOSE_YML" "$RELEASES/$sha/compose.yml"
    write_build_json live "live"
    log "live: $short on 127.0.0.1:$port"
else
    compose logs --tail 50 server web >>"$dlog" 2>&1 || true
    if [[ -n "$current" && "$current" != "$sha" ]]; then
        how="the compose file it went live with"
        [[ -f "$RELEASES/$current/compose.yml" ]] || how="its commit's compose.yml (from git)"
        prev_yml="$(release_compose "$current")"
        if [[ -n "$prev_yml" ]]; then log "rolling back to ${current:0:7} with $how"
        else log "rolling back to ${current:0:7} with this commit's compose file (none kept for ${current:0:7})"; fi
        # swap_all (and swap.sh inside it) go through compose(), which reads
        # COMPOSE_YML: every step of the rollback uses the previous release's file.
        COMPOSE_YML="${prev_yml:-$COMPOSE_YML}" HOLT_TAG="$current" swap_all || true
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

# --- edge config -------------------------------------------------------------------
# After the swap, so a failure here leaves the new release live behind the old
# config. `nginx -s reload` is graceful: the port never closes. The edge only
# serves /__build and proxies, so a config that passes nginx -t but breaks the
# site is caught by the same health check, and the previous config goes back.
if ! edge_apply "$EDGE_CONF" "$STATE/edge"; then
    write_build_json failed "$short is live, but its edge.conf was rejected; the edge keeps the previous config"
    die "EDGE CONFIG NOT APPLIED: $EDGE_MSG ($short itself is live)"
fi
log "$EDGE_MSG"
if (( EDGE_CHANGED )) && ! healthy; then
    edge_revert "$STATE/edge" || true
    healthy || log "still unhealthy with the previous edge config; see 'compose logs edge'"
    write_build_json failed "$short is live, but its edge.conf broke the health check; the previous edge config is back"
    die "EDGE CONFIG REVERTED: the site failed its health check with $short's edge.conf"
fi

# --- clean up after ourselves only --------------------------------------------------
# Keep the live and the previous tag (the rollback target); untag older ones
# of this stack, then prune only images labelled holt.stack=prod and only this
# builder's cache. Nothing else on the box is touched.
keep=" $sha $(cat "$STATE/previous" 2>/dev/null || true) "
for d in "$RELEASES"/*/; do
    [[ -d "$d" && "$keep" != *" $(basename "$d") "* ]] && rm -rf "$d"
done
for img in $(docker images --filter "label=$LABEL" --format '{{.Repository}}:{{.Tag}}' | grep -E "^$PROJECT-(server|web):[0-9a-f]{40}\$"); do
    [[ "$keep" == *" ${img#*:} "* ]] || docker image rm "$img" >/dev/null 2>&1 || true
done
docker image prune -f --filter "label=$LABEL" >/dev/null || true
docker buildx prune --builder "$BUILDER" -f --max-used-space 3gb >/dev/null 2>&1 || true
ls -1t "$STATE"/logs/deploy-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
