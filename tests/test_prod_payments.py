"""Production sells passes only on the owner's switch, and only with live keys.

`deploy/prod/env.sh` (`check_prod_payments`) and `deploy.sh` run here for
real, with `docker` and `git` stubbed so nothing is built, fetched or
started. What must hold: production reads its own names (`HOLT_PROD_PAYMENTS`,
`PROD_RAZORPAY_*`, `PROD_DODO_*`) and never the unprefixed ones staging uses
with test keys; with the switch on, a deploy stops before it changes anything
unless the Razorpay keys are live and complete and Dodo is all there or not
at all; and no message ever holds a key.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

PROD = Path("deploy/prod").resolve()

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"),
    reason="the production scripts are bash and run on the Linux server",
)

LIVE = {
    "HOLT_PROD_PAYMENTS": "1",
    "PROD_RAZORPAY_KEY_ID": "rzp_live_Abc123",
    "PROD_RAZORPAY_KEY_SECRET": "rz-secret-value",
    "PROD_RAZORPAY_WEBHOOK_SECRET": "rz-hook-value",
}
DODO = {
    "PROD_DODO_API_KEY": "dodo-key-value",
    "PROD_DODO_WEBHOOK_SECRET": "dodo-hook-value",
    "PROD_DODO_PRODUCT_PRO_1M": "pdt_one",
    "PROD_DODO_PRODUCT_PRO_3M": "pdt_three",
    "PROD_DODO_PRODUCT_PRO_12M": "pdt_twelve",
}
# What staging's secrets look like: none of it is production's to read.
STAGING = {
    "HOLT_PAYMENTS_ENABLED": "1",
    "HOLT_PASSES_ON_SALE": "1",
    "RAZORPAY_KEY_ID": "rzp_test_staging",
    "RAZORPAY_KEY_SECRET": "staging-secret-value",
    "RAZORPAY_WEBHOOK_SECRET": "staging-hook-value",
    "DODO_API_KEY": "staging-dodo-value",
}

# `docker exec` runs passes.sh's Python here, against the test's own server.
DOCKER_STUB = f"""#!/bin/sh
echo "$*" >> "$STUB_DIR/docker"
case " $* " in
    *" ps "*) [ -f "$STUB_DIR/no_server" ] || echo abc123 ;;
    *" exec "*) exec "{sys.executable}" - "$STUB_URL" ;;
esac
exit 0
"""
GIT_STUB = """#!/bin/sh
echo "$*" >> "$STUB_DIR/git"
exit 1
"""
CHECK = '. "$1"; load_prod_env >/dev/null; echo "$PAYMENTS_OK|$HOLT_PROD_PAYMENTS|$PAYMENTS_MSG"'


class Rig:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.state = tmp / "state"
        self.stubs = tmp / "stubs"
        self.secrets = tmp / "secrets.env"
        bin_ = self.home / ".local" / "bin"
        for d in (bin_, self.state, self.stubs):
            d.mkdir(parents=True)
        for name, body in (("docker", DOCKER_STUB), ("git", GIT_STUB)):
            (bin_ / name).write_text(body, encoding="utf-8")
            (bin_ / name).chmod(0o755)
        self.dotenv = self.state / ".env"
        self.dotenv.write_text("HOLT_PROD_PORT=1\n", encoding="utf-8")
        self.write(self.secrets, {})

    def write(self, path: Path, values: dict[str, str], keep: bool = False) -> None:
        base = {"CONTACT_EMAIL": "owner@example.com", "CONTACT_CITY": "Patiala"} if path == self.secrets else {}
        old = path.read_text(encoding="utf-8") if keep else ""
        path.write_text(old + "".join(f"{k}={v}\n" for k, v in {**base, **values}.items()), encoding="utf-8")

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "PATH": f"{self.home / '.local' / 'bin'}:{os.environ['PATH']}",
            "STUB_DIR": str(self.stubs),
            "HOLT_PROD_HOME": str(self.state),
            "HOLT_PROD_PROJECT": "payments-test",
            "HOLT_SECRETS_FILE": str(self.secrets),
            "GITHUB_TOKENS": "not-a-token",
            **extra,
        }

    def check(self, **extra: str) -> tuple[bool, str, str]:
        """(ok, the switch as compose will see it, the message)."""
        r = subprocess.run(["bash", "-c", CHECK, "check", str(PROD / "env.sh")], env=self.env(**extra),
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        ok, switch, msg = r.stdout.strip().split("|", 2)
        return ok == "1", switch, msg

    def deploy(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(PROD / "deploy.sh")], env=self.env(**extra),
                              capture_output=True, text=True, timeout=60)

    def calls(self, tool: str) -> list[str]:
        p = self.stubs / tool
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def no_values(text: str) -> None:
    for value in [*LIVE.values(), *DODO.values(), *STAGING.values()]:
        if len(value) > 1:
            assert value not in text, "a setting's value was printed"


# --- the guard -------------------------------------------------------------------------


def test_passes_are_off_until_the_owner_sets_the_switch(rig: Rig) -> None:
    assert rig.check() == (True, "0", "passes: off (HOLT_PROD_PAYMENTS is not 1)")
    # Live keys alone sell nothing: the switch is its own setting.
    rig.write(rig.secrets, {**LIVE, **DODO, "HOLT_PROD_PAYMENTS": "0"})
    assert rig.check() == (True, "0", "passes: off (HOLT_PROD_PAYMENTS is not 1)")


def test_stagings_names_never_switch_production_on(rig: Rig) -> None:
    rig.write(rig.secrets, STAGING)
    rig.write(rig.dotenv, STAGING, keep=True)
    assert rig.check(**STAGING) == (True, "0", "passes: off (HOLT_PROD_PAYMENTS is not 1)")


@pytest.mark.parametrize("where", ["secrets", "dotenv"])
def test_live_razorpay_keys_and_the_switch_put_passes_on_sale(rig: Rig, where: str) -> None:
    rig.write(rig.secrets if where == "secrets" else rig.dotenv, LIVE, keep=True)
    assert rig.check() == (True, "1", "passes: on (Razorpay live keys; no Dodo, so no USD)")


def test_dodo_all_set_offers_usd(rig: Rig) -> None:
    rig.write(rig.secrets, {**LIVE, **DODO})
    assert rig.check() == (True, "1", "passes: on (Razorpay live keys; Dodo set, USD offered)")


@pytest.mark.parametrize("key_id", ["rzp_test_Abc123", "rzp_live_", "Abc123", "rzp_test_rzp_live_x"])
def test_a_key_that_is_not_live_is_refused(rig: Rig, key_id: str) -> None:
    rig.write(rig.secrets, {**LIVE, "PROD_RAZORPAY_KEY_ID": key_id})
    assert rig.check() == (False, "0", "PROD_RAZORPAY_KEY_ID is not a live key (it must start with rzp_live_)")


def test_a_test_key_under_productions_name_is_refused_with_the_switch_off_too(rig: Rig) -> None:
    rig.write(rig.secrets, {**LIVE, "HOLT_PROD_PAYMENTS": "0", "PROD_RAZORPAY_KEY_ID": "rzp_test_Abc123"})
    ok, _, msg = rig.check()
    assert not ok and "not a live key" in msg


@pytest.mark.parametrize("missing", ["PROD_RAZORPAY_KEY_ID", "PROD_RAZORPAY_KEY_SECRET",
                                     "PROD_RAZORPAY_WEBHOOK_SECRET"])
def test_the_switch_without_every_razorpay_setting_is_refused(rig: Rig, missing: str) -> None:
    rig.write(rig.secrets, {k: v for k, v in LIVE.items() if k != missing})
    ok, _, msg = rig.check()
    assert not ok and msg == f"HOLT_PROD_PAYMENTS=1 but {missing} not set"


def test_stagings_keys_do_not_stand_in_for_productions(rig: Rig) -> None:
    rig.write(rig.secrets, {**STAGING, "HOLT_PROD_PAYMENTS": "1"})
    ok, _, msg = rig.check()
    assert not ok and "PROD_RAZORPAY_KEY_ID PROD_RAZORPAY_KEY_SECRET PROD_RAZORPAY_WEBHOOK_SECRET" in msg


@pytest.mark.parametrize("missing", sorted(DODO))
def test_half_of_dodo_is_refused(rig: Rig, missing: str) -> None:
    rig.write(rig.secrets, {**LIVE, **{k: v for k, v in DODO.items() if k != missing}})
    ok, _, msg = rig.check()
    assert not ok and msg.startswith(f"Dodo is only partly set up: {missing} not set")
    no_values(msg)


@pytest.mark.parametrize("value", ["true", "yes", "on", "2", "1 "])
def test_the_switch_is_0_or_1_and_nothing_else(rig: Rig, value: str) -> None:
    """The server would read `true` as on; the guard must not read it as off."""
    ok, switch, msg = rig.check(HOLT_PROD_PAYMENTS=value, **{k: v for k, v in LIVE.items()
                                                             if k != "HOLT_PROD_PAYMENTS"})
    assert (ok, switch, msg) == (False, "0", "HOLT_PROD_PAYMENTS must be 0 or 1")


# --- deploy.sh ---------------------------------------------------------------------------


@pytest.mark.parametrize("secrets", [
    {**LIVE, "PROD_RAZORPAY_KEY_ID": "rzp_test_Abc123"},
    {k: v for k, v in LIVE.items() if k != "PROD_RAZORPAY_WEBHOOK_SECRET"},
    {**LIVE, **{k: v for k, v in DODO.items() if k != "PROD_DODO_PRODUCT_PRO_3M"}},
])
def test_a_refused_deploy_changes_nothing_and_prints_no_value(rig: Rig, secrets: dict) -> None:
    rig.write(rig.secrets, secrets)
    r = rig.deploy()
    assert r.returncode == 1 and "ERROR: " in r.stdout and "nothing was changed" in r.stdout
    assert rig.calls("git") == [] and rig.calls("docker") == []
    no_values(r.stdout + r.stderr)


def test_a_deploy_says_whether_passes_are_on_and_prints_no_value(rig: Rig) -> None:
    r = rig.deploy()   # goes on to fetch the commit, which the git stub fails
    assert "passes: off (HOLT_PROD_PAYMENTS is not 1)" in r.stdout
    rig.write(rig.secrets, {**LIVE, **DODO})
    r = rig.deploy()
    assert "passes: on (Razorpay live keys; Dodo set, USD offered)" in r.stdout
    assert rig.calls("git") and rig.calls("docker") == []
    no_values(r.stdout + r.stderr)


# --- compose.yml ---------------------------------------------------------------------------


def test_compose_gives_the_server_only_productions_names() -> None:
    compose = yaml.safe_load((PROD / "compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["server"]["environment"]
    assert env["HOLT_ENV"] == "production"
    assert env["HOLT_PAYMENTS_ENABLED"] == "${HOLT_PROD_PAYMENTS:-0}"
    assert env["DODO_ENV"] == "live"
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "DODO_API_KEY",
                 "DODO_WEBHOOK_SECRET", "DODO_PRODUCT_PRO_1M", "DODO_PRODUCT_PRO_3M", "DODO_PRODUCT_PRO_12M"):
        assert env[name] == f"${{PROD_{name}:-}}", name
    assert "HOLT_PASSES_ON_SALE" not in env
    # The checkout's key id reaches the browser through the API: web gets nothing.
    web = compose["services"]["web"]
    for name in [*web["environment"], *web["build"]["args"]]:
        assert not any(word in name for word in ("RAZORPAY", "DODO", "PAYMENTS")), name


def test_nothing_in_production_reads_stagings_names() -> None:
    for path in sorted(PROD.iterdir()):
        if path.suffix in (".sh", ".yml"):
            text = path.read_text(encoding="utf-8")
            for name in ("RAZORPAY_", "DODO_API", "DODO_WEBHOOK", "DODO_PRODUCT", "HOLT_PAYMENTS_ENABLED",
                         "HOLT_PASSES_ON_SALE"):
                for prefix in ("${", "$"):
                    assert f"{prefix}{name}" not in text, f"{path.name} reads {name}"


# --- passes.sh ---------------------------------------------------------------------------


class Api(http.server.BaseHTTPRequestHandler):
    body: dict = {}

    def do_GET(self) -> None:
        ok = self.path == "/v1/passes" and self.headers.get("X-Holt-Internal-Key") == "internal-key-value"
        self.send_response(200 if ok else 401)
        self.end_headers()
        self.wfile.write(json.dumps(self.body if ok else {}).encode())

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def passes(rig: Rig):
    """Run passes.sh against a stand-in for the server answering GET /v1/passes."""
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def run(body: dict, **container_env: str) -> subprocess.CompletedProcess:
        Api.body = body
        env = rig.env(STUB_URL=f"http://127.0.0.1:{httpd.server_port}",
                      HOLT_INTERNAL_KEY="internal-key-value", **container_env)
        return subprocess.run(["bash", str(PROD / "passes.sh")], env=env,
                              capture_output=True, text=True, timeout=60)
    yield run
    httpd.shutdown()


ON_SALE = {"on_sale": True, "features": [], "passes": [
    {"id": "pro_1m", "name": "1 month", "days": 30, "amount": 9900, "currency": "INR"},
    {"id": "pro_12m", "name": "12 months", "days": 365, "amount": 79900, "currency": "INR"}]}
RUNNING = {"HOLT_PAYMENTS_ENABLED": "1", "RAZORPAY_KEY_ID": LIVE["PROD_RAZORPAY_KEY_ID"],
           "RAZORPAY_KEY_SECRET": LIVE["PROD_RAZORPAY_KEY_SECRET"],
           "RAZORPAY_WEBHOOK_SECRET": LIVE["PROD_RAZORPAY_WEBHOOK_SECRET"]}
RUNNING_DODO = {"DODO_ENV": "live", **{k.removeprefix("PROD_"): v for k, v in DODO.items()}}


def test_passes_sh_says_what_is_live_without_a_secret(rig: Rig, passes) -> None:
    r = passes(ON_SALE, **RUNNING, **RUNNING_DODO)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "payments switch: on",
        "Razorpay: live key, key secret set, webhook secret set",
        "Dodo: set (DODO_ENV=live)",
        "passes on sale:",
        "  pro_1m   1 month     30 days  INR 99.00  USD 7.00",
        "  pro_12m  12 months  365 days  INR 799.00  USD 39.00",
    ]
    no_values(r.stdout + r.stderr)
    assert "internal-key-value" not in r.stdout + r.stderr + "\n".join(rig.calls("docker"))
    assert all(" exec " in f" {c} " or " ps " in f" {c} " for c in rig.calls("docker"))   # read-only


def test_passes_sh_when_nothing_is_on_sale(rig: Rig, passes) -> None:
    r = passes({"on_sale": False, "passes": [], "features": []})
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "payments switch: off",
        "Razorpay: no key id, key secret MISSING, webhook secret MISSING",
        "Dodo: not set (no USD)",
        "passes on sale: none",
    ]


def test_passes_sh_names_a_test_key_and_half_of_dodo(rig: Rig, passes) -> None:
    r = passes(ON_SALE, **{**RUNNING, "RAZORPAY_KEY_ID": "rzp_test_Abc123"}, DODO_API_KEY="dodo-key-value")
    assert "Razorpay: TEST key" in r.stdout
    assert ("Dodo: partly set, missing DODO_WEBHOOK_SECRET DODO_PRODUCT_PRO_1M DODO_PRODUCT_PRO_3M "
            "DODO_PRODUCT_PRO_12M") in r.stdout
    assert "USD" not in r.stdout.split("passes on sale:")[1]
    no_values(r.stdout + r.stderr)


def test_passes_sh_without_a_running_server(rig: Rig, passes) -> None:
    (rig.stubs / "no_server").touch()
    r = passes(ON_SALE)
    assert r.returncode == 1 and "server container is not running" in r.stdout
