#!/usr/bin/env bash
# env.sh -- the production stack's environment, shared by deploy.sh and
# warm.sh (source it, then call load_prod_env). Not a script to run.
#
# Sets STATE, PROJECT, SECRETS and, from ~/.config/holt/secrets.env
# (optional, user-managed, KEY=value lines):
#   GITHUB_OAUTH_ID / GITHUB_OAUTH_SECRET  -> AUTH_GITHUB_ID / AUTH_GITHUB_SECRET
#   GOOGLE_OAUTH_ID / GOOGLE_OAUTH_SECRET  -> AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET
#   OPENROUTER_API_KEY, GITHUB_TOKENS      -> the same names
#   CONTACT_EMAIL / CONTACT_CITY           -> NEXT_PUBLIC_CONTACT_EMAIL / _CITY
# Exported, so they win over .env for compose. An unset key stays empty and
# the feature stays off (sign-in hidden, AI reports answer needs_key). The
# one thing every run needs is a GitHub token: GITHUB_TOKENS from the secrets
# file, else `gh auth token`, else stop, because the server would start with
# no API budget ("points left 0") and a warm pass would end at once.

STATE="${HOLT_PROD_HOME:-$HOME/.local/share/holt-prod}"
SECRETS="${HOLT_SECRETS_FILE:-$HOME/.config/holt/secrets.env}"
# HOLT_PROD_PROJECT: only for a rehearsal on a dev port (README.md); the
# builder, the label and the image names follow it, so the rehearsal and the
# real stack never share anything.
PROJECT="${HOLT_PROD_PROJECT:-holt-prod}"

if ! declare -F log >/dev/null; then log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }; fi
if ! declare -F die >/dev/null; then die() { log "ERROR: $*"; exit 1; }; fi

load_prod_env() {
    if [[ -f "$SECRETS" ]]; then
        local line key val
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
    export NEXT_PUBLIC_CONTACT_EMAIL="${NEXT_PUBLIC_CONTACT_EMAIL:-${CONTACT_EMAIL:-}}"
    export NEXT_PUBLIC_CONTACT_CITY="${NEXT_PUBLIC_CONTACT_CITY:-${CONTACT_CITY:-}}"
}
