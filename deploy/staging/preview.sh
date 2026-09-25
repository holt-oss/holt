#!/usr/bin/env bash
# preview.sh -- keep https://holt-new.aahil-khan.xyz on the latest preview.
#
# One run: fetch origin; if main, any open PR labelled `staging`, or any
# branch in deploy/staging/extra-branches moved, build a preview commit
# (origin/main merged with each of them, skipping ones that conflict),
# rebuild the images and restart only the stage-holt-new stack. Then prune
# this stack's dangling images and its own build cache.
#
# The systemd --user timer from install.sh runs it every 3 minutes.
# By hand:   preview.sh            (no-op when nothing changed)
#            FORCE=1 preview.sh    (rebuild anyway, and skip the load check)
#
# Serialised with flock: a run that finds another in progress exits.
# Waits for the 1-minute load < 6 and MemAvailable > 3 GB before building.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

STATE="${HOLT_STAGE_HOME:-$HOME/.local/share/holt-staging}"
SRC="$STATE/src"                                   # dedicated clone, detached at the preview
REPO="${HOLT_REPO:-holt-oss/holt}"
LOCAL_REPO="${HOLT_LOCAL_REPO:-$HOME/projects/holt}"  # for extra branches not pushed yet
PROJECT=stage-holt-new
LABEL="holt.stage=holt-new"
BUILDER=holt-stage
MAX_LOAD="${HOLT_STAGE_MAX_LOAD:-6}"
MIN_AVAIL_MB="${HOLT_STAGE_MIN_AVAIL_MB:-3072}"
MAX_WAIT="${HOLT_STAGE_MAX_WAIT:-1800}"            # seconds to wait for room, then retry next tick
DEPLOY="$SRC/deploy/staging"
FORCE="${FORCE:-0}"

mkdir -p "$STATE/logs"
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

exec 9>"$STATE/lock"
if ! flock -n 9; then log "another run is in progress; skipping"; exit 0; fi

RUN="$(mktemp -d "$STATE/run.XXXXXX")"
trap 'rm -rf "$RUN"' EXIT
: > "$RUN/included.tsv"   # kind  name  branch  sha  title  url
: > "$RUN/skipped.tsv"    # kind  name  branch  sha  title  url  reason

# --- clone ------------------------------------------------------------------
if [[ ! -d "$SRC/.git" ]]; then
    log "cloning $REPO into $SRC"
    git clone -q "https://github.com/$REPO.git" "$SRC"
    git -C "$SRC" config user.name "holt-staging"
    git -C "$SRC" config user.email "holt-staging@localhost"
fi
cd "$SRC"

# --- what should be in the preview ------------------------------------------
git fetch -q --prune origin '+refs/heads/*:refs/remotes/origin/*'
main_sha="$(git rev-parse refs/remotes/origin/main)"

declare -a CANDIDATES=()   # "kind<TAB>name<TAB>branch<TAB>sha<TAB>title<TAB>url"
pr_branches=" "
while IFS=$'\t' read -r num branch title url; do
    [[ -z "$num" ]] && continue
    git fetch -q origin "+refs/pull/$num/head:refs/remotes/pr/$num"
    sha="$(git rev-parse "refs/remotes/pr/$num")"
    CANDIDATES+=("pr"$'\t'"#$num"$'\t'"$branch"$'\t'"$sha"$'\t'"$title"$'\t'"$url")
    pr_branches+="$branch "
done < <(gh pr list -R "$REPO" --label staging --state open --limit 50 \
            --json number,headRefName,title,url \
            --jq 'sort_by(.number) | .[] | [.number, .headRefName, .title, .url] | @tsv')

# extra-branches: union of the file on main and in each labelled PR.
{
    git show "$main_sha:deploy/staging/extra-branches" 2>/dev/null || true
    for c in "${CANDIDATES[@]}"; do
        git show "$(cut -f4 <<<"$c"):deploy/staging/extra-branches" 2>/dev/null || true
    done
} | sed 's/#.*//; s/[[:space:]]//g; /^$/d' | awk '!seen[$0]++' > "$RUN/extra"

while read -r b; do
    [[ "$pr_branches" == *" $b "* ]] && continue    # its PR is labelled; already in
    url="https://github.com/$REPO/tree/$b"
    if sha="$(git rev-parse -q --verify "refs/remotes/origin/$b")"; then
        CANDIDATES+=("branch"$'\t'"$b"$'\t'"$b"$'\t'"$sha"$'\t'"(no PR yet)"$'\t'"$url")
    elif [[ -d "$LOCAL_REPO/.git" || -f "$LOCAL_REPO/.git" ]] \
         && git -C "$LOCAL_REPO" rev-parse -q --verify "refs/heads/$b" >/dev/null; then
        git fetch -q "$LOCAL_REPO" "+refs/heads/$b:refs/remotes/local/$b"
        sha="$(git rev-parse "refs/remotes/local/$b")"
        CANDIDATES+=("branch"$'\t'"$b"$'\t'"$b"$'\t'"$sha"$'\t'"(no PR yet; local, not pushed)"$'\t'"")
    else
        printf 'branch\t%s\t%s\t\t\t\t%s\n' "$b" "$b" "branch not found on origin or locally" >> "$RUN/skipped.tsv"
    fi
done < "$RUN/extra"

fingerprint="$( { echo "main $main_sha"; printf '%s\n' "${CANDIDATES[@]}" | cut -f1-4; cat "$RUN/skipped.tsv"; } | sha256sum | cut -c1-16)"
if [[ "$FORCE" != 1 && "$fingerprint" == "$(cat "$STATE/fingerprint" 2>/dev/null || true)" ]]; then
    exit 0   # nothing changed; stay quiet so the journal stays readable
fi
log "change detected (main ${main_sha:0:7}, ${#CANDIDATES[@]} branch(es))"

# --- build-info JSON (/__build) -----------------------------------------------
BUILD_DIR="$DEPLOY/build"
write_build_json() {   # status message [preview_sha]
    mkdir -p "$BUILD_DIR"
    STATUS="$1" MESSAGE="$2" PREVIEW="${3:-}" MAIN="$main_sha" RUN="$RUN" STATE="$STATE" \
    OUT="$BUILD_DIR/build.json" REPO="$REPO" python3 - <<'PY'
import json, os, datetime
env = os.environ
def rows(name, keys):
    out = []
    with open(os.path.join(env["RUN"], name), encoding="utf-8") as f:
        for line in f:
            vals = line.rstrip("\n").split("\t")
            d = {k: v for k, v in zip(keys, vals) if v}
            if d.get("sha"):
                d["short"] = d["sha"][:7]
            out.append(d)
    return out
keys = ["kind", "name", "branch", "sha", "title", "url"]
attempt = {
    "status": env["STATUS"],
    "message": env["MESSAGE"],
    "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "main": {"sha": env["MAIN"], "short": env["MAIN"][:7],
             "url": f"https://github.com/{env['REPO']}/commit/{env['MAIN']}"},
    "preview_sha": env["PREVIEW"] or None,
    "included": rows("included.tsv", keys),
    "skipped": rows("skipped.tsv", keys + ["reason"]),
}
live_path = os.path.join(env["STATE"], "live.json")
if env["STATUS"] == "live":
    live = dict(attempt, built_at=attempt["at"])
    for k in ("status", "message", "at"):
        live.pop(k)
    with open(live_path, "w", encoding="utf-8") as f:
        json.dump(live, f, indent=2)
try:
    with open(live_path, encoding="utf-8") as f:
        live = json.load(f)
except FileNotFoundError:
    live = None
doc = {"site": "https://holt-new.aahil-khan.xyz", "live": live, "last_attempt": attempt}
tmp = env["OUT"] + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
os.replace(tmp, env["OUT"])
PY
}

# --- wait for room ------------------------------------------------------------
wait_for_room() {
    local waited=0 load avail
    while :; do
        load="$(cut -d' ' -f1 /proc/loadavg)"
        avail="$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)"
        if awk -v l="$load" -v m="$MAX_LOAD" 'BEGIN{exit !(l < m)}' && (( avail > MIN_AVAIL_MB )); then
            return 0
        fi
        (( waited >= MAX_WAIT )) && { log "still busy after ${MAX_WAIT}s (load $load, ${avail} MB free); next tick retries"; return 1; }
        (( waited == 0 )) && log "waiting for room: load $load (< $MAX_LOAD), MemAvailable ${avail} MB (> $MIN_AVAIL_MB)"
        sleep 30; waited=$((waited + 30))
    done
}

# --- merge --------------------------------------------------------------------
git checkout -q -f --detach "$main_sha"
for c in "${CANDIDATES[@]}"; do
    IFS=$'\t' read -r kind name branch sha title url <<<"$c"
    if git merge -q --no-ff --no-edit -m "staging: merge $name ($branch)" "$sha" >"$RUN/merge.out" 2>&1; then
        printf '%s\n' "$c" >> "$RUN/included.tsv"
        log "included $name ${sha:0:7}"
    else
        files="$(git diff --name-only --diff-filter=U | head -20 | paste -sd' ' -)"
        git merge --abort 2>/dev/null || git reset -q --hard
        reason="conflicts with main or a branch merged before it${files:+ in: $files}"
        [[ -z "$files" ]] && reason="merge failed: $(tail -1 "$RUN/merge.out")"
        printf '%s\t%s\n' "$c" "$reason" >> "$RUN/skipped.tsv"
        log "skipped $name: $reason"
    fi
done
preview_sha="$(git rev-parse HEAD)"

fail() {   # record a failed attempt; don't retry the same inputs until something moves
    log "FAILED: $1"
    write_build_json failed "$1" "$preview_sha" || true
    echo "$fingerprint" > "$STATE/fingerprint"
    exit 1
}

[[ -f "$DEPLOY/compose.yml" ]] || fail "the preview has no deploy/staging/compose.yml (is the deploy PR labelled staging, or merged?)"
[[ -f "$SRC/web/package.json" ]] || fail "the preview has no web/ app (is the web branch labelled or in extra-branches?)"
[[ -f "$DEPLOY/.env" ]] || "$DEPLOY/make-env.sh"

if [[ "$FORCE" != 1 ]] && ! wait_for_room; then
    write_build_json waiting "waiting for the server to be less busy" "$preview_sha" || true
    exit 0
fi

# --- build and restart this stack only ------------------------------------------
write_build_json building "building ${preview_sha:0:7}" "$preview_sha"
if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
    # A builder of our own: its cache can be pruned without touching anyone else's.
    docker buildx create --name "$BUILDER" --driver docker-container \
        --driver-opt memory=3g --driver-opt "env.BUILDKIT_STEP_LOG_MAX_SIZE=10485760" >/dev/null
fi
export BUILDX_BUILDER="$BUILDER" COMPOSE_PROJECT_NAME="$PROJECT"
compose() { docker compose -p "$PROJECT" -f "$DEPLOY/compose.yml" --env-file "$DEPLOY/.env" "$@"; }
port="$(sed -n 's/^HOLT_STAGE_PORT=//p' "$DEPLOY/.env")"; port="${port:-9110}"

blog="$STATE/logs/build-$(date -u +%Y%m%dT%H%M%SZ).log"
log "building (log: $blog)"
if ! compose build >"$blog" 2>&1; then
    fail "image build failed; last lines: $(tail -5 "$blog" | tr '\n' ' ' | cut -c1-600)"
fi
compose up -d --remove-orphans >>"$blog" 2>&1 || fail "compose up failed; see $blog"

ok=0
for _ in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/" || true)"
    [[ "$code" == 200 ]] && { ok=1; break; }
    sleep 5
done
(( ok )) || fail "the site did not answer 200 within 5 minutes (last status $code); see $blog"

write_build_json live "live" "$preview_sha"
echo "$fingerprint" > "$STATE/fingerprint"
log "live: ${preview_sha:0:7} on 127.0.0.1:$port"

# --- clean up after ourselves only ----------------------------------------------------
docker image prune -f --filter "label=$LABEL" >/dev/null || true
docker buildx prune --builder "$BUILDER" -f --max-used-space 3gb >/dev/null 2>&1 || true
ls -1t "$STATE"/logs/build-*.log 2>/dev/null | tail -n +11 | xargs -r rm -f
