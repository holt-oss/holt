#!/usr/bin/env bash
# passes.sh -- what the running production server is selling. Read-only.
#
#   deploy/prod/passes.sh
#
# Asks the server container itself (its environment and its GET /v1/passes),
# so it shows what is live, not what the secrets file says: run it after
# `FORCE=1 deploy.sh` (README.md, "Selling passes"). Prints whether each
# setting is there, never its value.
set -euo pipefail
PROJECT="${HOLT_PROD_PROJECT:-holt-prod}"

server="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=server" \
    --filter "label=com.docker.compose.oneoff=False" --filter status=running | head -1)"
[[ -n "$server" ]] || { echo "the $PROJECT server container is not running"; exit 1; }

docker exec -i "$server" python - http://127.0.0.1:8000 <<'PY'
import json
import os
import sys
import urllib.request

env = os.environ.get


def money(minor, currency):
    return f"{currency} {minor / 100:,.2f}"


switch = env("HOLT_PAYMENTS_ENABLED", "0")
print(f"payments switch: {'on' if switch == '1' else 'off'}")

key = env("RAZORPAY_KEY_ID", "")
kind = ("live key" if key.startswith("rzp_live_") else
        "TEST key" if key.startswith("rzp_test_") else "key id of an unknown kind" if key else "no key id")
secrets = {"key secret": "RAZORPAY_KEY_SECRET", "webhook secret": "RAZORPAY_WEBHOOK_SECRET"}
print("Razorpay: " + ", ".join(
    [kind] + [f"{what} {'set' if env(name) else 'MISSING'}" for what, name in secrets.items()]))

dodo = ["DODO_API_KEY", "DODO_WEBHOOK_SECRET", "DODO_PRODUCT_PRO_1M", "DODO_PRODUCT_PRO_3M",
        "DODO_PRODUCT_PRO_12M"]
missing = [name for name in dodo if not env(name)]
if not missing:
    print(f"Dodo: set (DODO_ENV={env('DODO_ENV', '')})")
elif len(missing) == len(dodo):
    print("Dodo: not set (no USD)")
else:
    print("Dodo: partly set, missing " + " ".join(missing))

req = urllib.request.Request(sys.argv[1] + "/v1/passes",
                             headers={"X-Holt-Internal-Key": env("HOLT_INTERNAL_KEY", "")})
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        body = json.load(res)
except Exception as exc:  # a status line, not a traceback
    print(f"passes: the server didn't answer GET /v1/passes ({exc})")
    sys.exit(1)

passes = body.get("passes") or []
if not body.get("on_sale") or not passes:
    print("passes on sale: none")
    sys.exit(0)

# USD prices are in the catalogue; GET /v1/passes lists what Razorpay charges.
usd = {}
if not missing:
    try:
        from holt_server import pricing

        usd = {pid: p.price.usd_cents
               for pid, p in pricing.load(env("HOLT_PRICING_FILE") or None).passes.items()}
    except Exception:
        pass
print("passes on sale:")
for p in passes:
    line = f"  {p['id']:<8} {p['name']:<10} {p['days']:>3} days  {money(p['amount'], p['currency'])}"
    if usd.get(p["id"]):
        line += f"  {money(usd[p['id']], 'USD')}"
    print(line)
PY
