#!/usr/bin/env bash
# warm.sh -- fill production's caches (reports, starter issues, /find) from
# the seed list, detached, in the server image with the server's env.
#
#   deploy/prod/warm.sh                 start a full pass in the background
#   deploy/prod/warm.sh --dry-run       what it would do (foreground)
#   deploy/prod/warm.sh --limit 50 --no-find
#   deploy/prod/warm.sh --stale-only    after a deploy that bumps ENGINE_VERSION:
#                                       re-run only reports an older engine made
#                                       (from kept evidence where it is fresh)
#   deploy/prod/warm.sh --tier weekly   one refresh tier (warm-refresh.sh runs both)
#   deploy/prod/warm.sh --no-find --wait-for-budget
#                                       a long sweep: when GitHub points run low,
#                                       wait for them instead of stopping
#   deploy/prod/warm.sh --logs          follow the running pass
#   deploy/prod/warm.sh --status        is it running? last lines, and how far it is
#                                       (seeds skipped as recently failed, seeds to go)
#
# Jobs go through the normal queue at badge priority, HOLT_WARM_PARALLEL (3)
# in flight at once (--parallel N to change it), so user requests always run
# first. Only one pass runs at a time (the pass's advisory lock), so a pass
# started by an older deploy keeps going until it ends or is stopped.
# Run it after the first deploy (an empty cache) and after a long outage.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
. "$here/env.sh"   # STATE, PROJECT, load_prod_env
NAME="$PROJECT-warm"
sha="$(cat "$STATE/current" 2>/dev/null || true)"
[[ -n "$sha" ]] || { echo "nothing deployed yet (no $STATE/current)"; exit 1; }
export HOLT_SRC="$STATE/src" HOLT_TAG="$sha" HOLT_PROD_HOME="$STATE" HOLT_PROD_PROJECT="$PROJECT"
compose() { docker compose -p "$PROJECT" -f "$here/compose.yml" --env-file "$STATE/.env" "$@"; }

case "${1:-}" in
    --logs) exec docker logs -f "$NAME" ;;
    --status)
        if docker ps -q --filter "name=^$NAME$" | grep -q .; then echo "running:"; else echo "not running; last run:"; fi
        docker logs --tail 15 "$NAME" 2>&1 || echo "(no warm container yet)"
        # How far it is: the seeds skipped as recently failed, the last
        # "progress:" line and, once the pass has ended, its summary.
        echo "so far:"
        docker logs "$NAME" 2>&1 \
            | grep -E '^([0-9]+ seeds skipped as recently failed|progress: |reports [0-9]+ run, )' \
            | tail -n 3 || true
        exit 0 ;;
esac

# The same secrets and GitHub access as deploy.sh: `compose run` takes the
# GitHub App's settings (or GITHUB_TOKENS) from this shell, and without them
# the server has no API budget and the pass ends at once ("points left 0").
load_prod_env

if [[ "${1:-}" == --dry-run ]]; then
    compose run --rm --no-deps server python -m holt_server.warm "$@"; exit $?
fi

if docker ps -q --filter "name=^$NAME$" | grep -q .; then
    echo "a warm pass is already running (warm.sh --logs)"; exit 0
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
compose run -d --no-deps --name "$NAME" --label "holt.stack=$PROJECT" server python -m holt_server.warm "$@" >/dev/null
echo "warm pass started in container $NAME (warm.sh --logs to follow, --status for the summary)"
