#!/usr/bin/env bash
# swap.sh -- replace a compose service's container with no gap in service.
# Sourced by prod/deploy.sh and staging/preview.sh; not a script to run.
# Calls the caller's `compose` function.
#
#   swap_service <svc> [timeout]
#
# Starts one new container of <svc> from the current compose config (the
# new image tag and env) next to the running one, waits for its health
# check, then stops and removes the old one. While both run, both answer to
# the service's name on the network: the edge re-resolves `web` every
# couple of seconds and tries the other address when one refuses, and web
# reaches `server` the same way, so nobody sees the swap. (This is what
# `docker compose up -d` can't do: it stops the old container first, and
# for those seconds Cloudflare showed its 502 page.)
#
# If the new container isn't healthy within <timeout> seconds (default 180)
# or exits, it is removed and the old one keeps serving: returns 1 and
# SWAP_MSG says why, with the new container's last log lines. On success
# SWAP_MSG says how long it took. A service with no container yet is just
# started (and waited for).
#
# Needs a healthcheck on <svc> (compose.yml); a service without one counts
# as ready once it is running. The service must not publish a host port or
# set container_name, since two of it run at once for a moment.

SWAP_STOP_WAIT="${SWAP_STOP_WAIT:-30}"   # seconds an old container gets to finish its requests
SWAP_SETTLE="${SWAP_SETTLE:-3}"         # seconds both run once the new one is healthy: longer than
                                        # the edge's DNS cache (resolver valid=2s), so it knows both

_swap_ids() { compose ps -a -q "$1" 2>/dev/null | sort; }

_swap_state() {   # healthy | starting | unhealthy | running (no healthcheck) | exited | crashing | ...
    local out
    out="$(docker inspect -f '{{.RestartCount}} {{if .State.Health}}{{if eq .State.Status "running"}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null)" \
        || { echo gone; return; }
    # restart: unless-stopped brings a crashing container back up, again and
    # again; once is enough to know it won't do.
    if [[ "${out%% *}" != 0 ]]; then echo "crashing (restarted ${out%% *}x)"; else echo "${out#* }"; fi
}

swap_service() {
    local svc="$1" timeout="${2:-180}" old new n state started=$SECONDS
    SWAP_MSG=
    old="$(_swap_ids "$svc")"
    n="$(printf '%s' "$old" | grep -c . || true)"
    # --no-recreate keeps the old container as it is; the extra one is
    # created from the config as it is now.
    if ! compose up -d --no-deps --no-recreate --scale "$svc=$((n + 1))" "$svc" >/dev/null 2>&1; then
        new="$(comm -13 <(printf '%s\n' "$old") <(_swap_ids "$svc") | grep . || true)"
        [[ -n "$new" ]] && docker rm -f $new >/dev/null 2>&1
        SWAP_MSG="$svc: compose couldn't start a new container; the old one keeps serving"
        return 1
    fi
    new="$(comm -13 <(printf '%s\n' "$old") <(_swap_ids "$svc") | grep . || true)"
    if [[ "$(printf '%s' "$new" | grep -c . || true)" != 1 ]]; then
        [[ -n "$new" ]] && docker rm -f $new >/dev/null 2>&1
        SWAP_MSG="$svc: expected one new container, found '$(echo $new)'; the old one keeps serving"
        return 1
    fi
    while :; do
        state="$(_swap_state "$new")"
        case "$state" in
            healthy|running) break ;;
            starting|created) ;;
            *) break ;;
        esac
        (( SECONDS - started >= timeout )) && { state="not healthy after ${timeout}s"; break; }
        sleep 1
    done
    if [[ "$state" != healthy && "$state" != running ]]; then
        SWAP_MSG="$svc: the new container is $state, so it was removed and the old one keeps serving. Its last lines: $(docker logs --tail 5 "$new" 2>&1 | tr '\n' ' ' | cut -c1-600)"
        docker rm -f "$new" >/dev/null 2>&1
        return 1
    fi
    if [[ -n "$old" ]]; then
        sleep "$SWAP_SETTLE"
        # docker stop: SIGTERM, then up to SWAP_STOP_WAIT for open requests.
        docker stop -t "$SWAP_STOP_WAIT" $old >/dev/null 2>&1 || true
        docker rm -f $old >/dev/null 2>&1 || true
    fi
    SWAP_MSG="$svc: new container healthy after $((SECONDS - started))s${old:+, old one retired}"
}
