#!/usr/bin/env bash
# warm-meta.sh -- re-read the repository details Discover shows (language,
# stars, topics, archived) for every reported repo whose copy is a day old.
# install.sh schedules it daily at 05:00 UTC (holt-prod-warm-meta.timer);
# by hand: deploy/prod/warm-meta.sh. Log: $STATE/logs/warm-meta.log.
#
# The warm pass with everything but details off (`--no-reports --no-starter
# --no-find`), in the foreground, in a one-off container of the live server
# image. It works no jobs, so it never takes a person's analysis. It reads
# the oldest details first, for at most HOLT_META_MAX_MINUTES (15); the rest
# are still due and go first tomorrow, so the whole list rolls over across
# several days (raise it to go faster). Cost: about one GitHub GraphQL point per ten repos (GitHub can't
# finish more at once), and it stops below HOLT_WARM_MIN_POINTS (1500) left.
# The summary line says how many points it used and how many repos are still
# due, and lists repos not on GitHub or not read. Running out of time is not
# a failure. It exits non-zero, and the unit shows failed, when GitHub
# couldn't answer three queries in a row or nothing could be read.
# A repo's first report already reads its own details (meta_refresh.py), so a
# skipped day only means some stars are a day older.
#
# Never overlaps:
#   - a deploy: it holds deploy.sh's lock ($STATE/lock) while it runs, and
#     waits up to HOLT_META_LOCK_WAIT seconds (45 min) for a deploy to finish,
#     else skips the day. A deploy that starts meanwhile exits 75 (busy) and
#     follow.sh tries again two minutes later. The pass takes at most
#     HOLT_META_MAX_MINUTES.
#   - the nightly backup: 03:30 UTC, and both take $STATE/backup.lock.
#   - a full warm pass: the pass's own advisory lock; it exits 75 and is
#     logged as skipped.
#
# The timer runs the copy in $STATE/bin (install.sh), with the compose file
# and env.sh of the deployed commit ($STATE/src), like the live stack.
# Rehearsal: HOLT_PROD_PROJECT and HOLT_PROD_HOME as for deploy.sh (README.md).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

STATE="${HOLT_PROD_HOME:-$HOME/.local/share/holt-prod}"
PROD="$STATE/src/deploy/prod"
LOCK_WAIT="${HOLT_META_LOCK_WAIT:-2700}"
LOG="$STATE/logs/warm-meta.log"
mkdir -p "$STATE/logs"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

sha="$(cat "$STATE/current" 2>/dev/null || true)"
[[ -n "$sha" && -f "$PROD/compose.yml" ]] || { log "nothing deployed yet (no $STATE/current or $PROD); skipped"; exit 0; }
# shellcheck source=env.sh
. "$PROD/env.sh"   # PROJECT, load_prod_env

# The backup's lock first, so waiting on it never holds up a deploy.
exec 7>"$STATE/backup.lock"
if ! flock -w "$LOCK_WAIT" 7; then
    log "the backup held its lock for ${LOCK_WAIT}s; skipped today"; exit 0
fi
exec 9>"$STATE/lock"
if ! flock -w "$LOCK_WAIT" 9; then
    log "a deploy held the lock for ${LOCK_WAIT}s; skipped today"; exit 0
fi

export HOLT_SRC="$STATE/src" HOLT_TAG="$sha" HOLT_PROD_HOME="$STATE" HOLT_PROD_PROJECT="$PROJECT"
load_prod_env >/dev/null   # the GitHub App or GITHUB_TOKENS, for `compose run`
log "reading repository details (${sha:0:7})"
docker rm -f "$PROJECT-warm-meta" >/dev/null 2>&1 || true   # a crashed run's leftover
set +e
docker compose -p "$PROJECT" -f "$PROD/compose.yml" --env-file "$STATE/.env" \
    run --rm --no-deps --name "$PROJECT-warm-meta" --label "holt.stack=$PROJECT" \
    server python -m holt_server.warm --no-reports --no-starter --no-find 2>&1 \
    | while IFS= read -r line; do log "$line"; done
code="${PIPESTATUS[0]}"
set -e
case "$code" in
    0)  ;;
    75) log "a warm pass was already running; skipped today"; code=0 ;;
    *)  log "ERROR: the details pass exited $code" ;;
esac
exit "$code"
