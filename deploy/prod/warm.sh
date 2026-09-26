#!/usr/bin/env bash
# warm.sh -- fill production's caches (reports, starter issues, /find) from
# the seed list, detached, in the server image with the server's env.
#
#   deploy/prod/warm.sh                 start a full pass in the background
#   deploy/prod/warm.sh --dry-run       what it would do (foreground)
#   deploy/prod/warm.sh --limit 50 --no-find
#   deploy/prod/warm.sh --logs          follow the running pass
#   deploy/prod/warm.sh --status        is it running? last lines
#
# Jobs go through the normal queue at badge priority, one at a time
# (HOLT_BADGE_CONCURRENCY=1 in the server), so user requests always run first.
# Run it after the first deploy (an empty cache) and after a long outage.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
STATE="${HOLT_PROD_HOME:-$HOME/.local/share/holt-prod}"
PROJECT="${HOLT_PROD_PROJECT:-holt-prod}"
NAME="$PROJECT-warm"
sha="$(cat "$STATE/current" 2>/dev/null || true)"
[[ -n "$sha" ]] || { echo "nothing deployed yet (no $STATE/current)"; exit 1; }
export HOLT_SRC="$STATE/src" HOLT_TAG="$sha" HOLT_PROD_HOME="$STATE" HOLT_PROD_PROJECT="$PROJECT"
compose() { docker compose -p "$PROJECT" -f "$here/compose.yml" --env-file "$STATE/.env" "$@"; }

case "${1:-}" in
    --logs) exec docker logs -f "$NAME" ;;
    --status)
        if docker ps -q --filter "name=^$NAME$" | grep -q .; then echo "running:"; else echo "not running; last run:"; fi
        docker logs --tail 15 "$NAME" 2>&1 || echo "(no warm container yet)"; exit 0 ;;
    --dry-run)
        exec docker compose -p "$PROJECT" -f "$here/compose.yml" --env-file "$STATE/.env" \
            run --rm --no-deps server python -m holt_server.warm --dry-run ;;
esac

if docker ps -q --filter "name=^$NAME$" | grep -q .; then
    echo "a warm pass is already running (warm.sh --logs)"; exit 0
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
compose run -d --no-deps --name "$NAME" --label "holt.stack=$PROJECT" server python -m holt_server.warm "$@" >/dev/null
echo "warm pass started in container $NAME (warm.sh --logs to follow, --status for the summary)"
