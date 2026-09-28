"""Staging has one host setting, its sign-in keys are its own, and it is quick.

`deploy/staging/preview.sh` is the loop that rebuilds the staging site. Two
things about it are easy to break without noticing, because nothing fails
until a person opens the site:

- the address. It used to be written in five places; now `STAGING_HOST` is
  the only one, and the web app's site host, `HOLT_WEB_URL`, `AUTH_URL`, the
  `site` on `/__build` and the smoke tests' `BASE_URL` must all follow it.
- the OAuth keys. Staging reads `STAGING_*_OAUTH_*` from the secrets file
  production also reads, and must never end up with production's keys.

And it has to stay fast: an image is rebuilt only when its inputs changed,
the smoke run comes after the site is live and can be skipped, and
`/__build` says what is happening now.

The script runs here for real, against a throwaway origin, with `docker`,
`gh`, `curl`, `npm` and `npx` replaced by stubs that write down what they
were given. Nothing is built, fetched or started.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

STAGING = Path("deploy/staging")
OLD_HOST = "holt-new.aahil-khan.xyz"
DEFAULT_HOST = "staging.githolt.com"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not all(shutil.which(t) for t in ("bash", "git", "flock")),
    reason="the staging scripts are bash and run on the Linux server",
)

STUBS = {
    # What compose was given when the stack was started. deploy/swap.sh
    # starts each new container with `up --scale` and waits for it to be
    # healthy: every scale-up adds one container id to what `ps` lists.
    # `compose config` answers with each service's build section (the web
    # image's build args follow the contact city); `compose build` gives the
    # image a new id and writes the service down in $STUB_DIR/built.
    "docker": """#!/bin/sh
echo "docker $*" >> "$STUB_DIR/calls"
for last; do :; done
n=$(cat "$STUB_DIR/containers" 2>/dev/null || echo 0)
case " $* " in
    *" up "*)
        case " $* " in *" --scale "*) echo $((n + 1)) > "$STUB_DIR/containers" ;; esac
        cp "$HOLT_STAGE_HOME/now.json" "$STUB_DIR/now-while-starting"; env | grep -E '^(STAGING_HOST|HOLT_WEB_URL|AUTH_|NEXT_PUBLIC_|GITHUB_TOKENS=)' | sort > "$STUB_DIR/compose.env" ;;
    *" ps "*) i=1; while [ "$i" -le "$n" ]; do echo "c$i"; i=$((i + 1)); done ;;
    *" config --hash "*) echo "$last stub-hash" ;;
    *" config "*)
        printf '{"services": {"server": {"image": "stage-holt-new-server:latest", "build": {"context": "/s"}},'
        printf ' "web": {"image": "stage-holt-new-web:latest", "build": {"context": "/w", "args": {"NEXT_PUBLIC_CONTACT_CITY": "%s"}}}}}\\n' "$NEXT_PUBLIC_CONTACT_CITY" ;;
    *" compose "*" build "*)
        cp "$HOLT_STAGE_HOME/now.json" "$STUB_DIR/now-while-building-$last"
        [ -n "$STUB_BUILD_FAILS" ] && exit 1
        echo "$last" >> "$STUB_DIR/built"
        date +%s%N > "$STUB_DIR/image-stage-holt-new-$last:latest" ;;
    *" image inspect "*)
        [ -f "$STUB_DIR/image-$last" ] || exit 1
        echo "sha256:$(cat "$STUB_DIR/image-$last")" ;;
    # A container (deploy/swap.sh): never the current one, always healthy.
    *" inspect "*) echo "0 healthy" ;;
esac
exit 0
""",
    # The smoke unit: what it was asked to do, and whether it is running.
    "systemctl": """#!/bin/sh
echo "systemctl $*" >> "$STUB_DIR/systemctl"
case " $* " in
    *" show "*) cat "$STUB_DIR/smoke_unit_state" 2>/dev/null || echo inactive ;;
esac
exit 0
""",
    # No labelled PRs; a token for make-env.sh.
    "gh": """#!/bin/sh
[ "$1 $2" = "auth token" ] && echo stub-token
exit 0
""",
    # The health check reads the status code from stdout. GitHub's answer to
    # a token check is $STUB_GITHUB_STATUS; its arguments and stdin are kept.
    "curl": """#!/bin/sh
case "$*" in
    *api.github.com*)
        echo "curl $*" >> "$STUB_DIR/github_calls"
        cat >> "$STUB_DIR/github_stdin"
        printf '%s' "${STUB_GITHUB_STATUS:-200}" ;;
    *) printf 200 ;;
esac
""",
    "npm": """#!/bin/sh
exit 0
""",
    # The smoke run: keep the URL it was pointed at, and the Access token it was given.
    "npx": """#!/bin/sh
echo "npx $*" >> "$STUB_DIR/npx"
printf '%s' "$BASE_URL" > "$STUB_DIR/base_url"
printf '%s\n%s\n' "${STAGING_CF_ACCESS_CLIENT_ID-(unset)}" "${STAGING_CF_ACCESS_CLIENT_SECRET-(unset)}" > "$STUB_DIR/cf_access"
exit 0
""",
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
        cwd=cwd, check=True, capture_output=True,
    )


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.home = root / "home"
        self.stub_dir = root / "stubs"
        self.secrets = root / "secrets.env"
        self.env_file = self.state / "src" / "deploy" / "staging" / ".env"

        # An origin whose main is the staging directory as it is in this checkout.
        origin = root / "origin"
        self.origin = origin
        shutil.copytree(STAGING, origin / "deploy" / "staging", ignore=shutil.ignore_patterns(".env", "build"))
        shutil.copytree(Path("deploy/server"), origin / "deploy" / "server")
        shutil.copytree(Path("deploy/web"), origin / "deploy" / "web")
        for app in ("web", "e2e"):
            (origin / app).mkdir()
            (origin / app / "package.json").write_text("{}\n", encoding="utf-8")
        git(origin, "init", "-q", "-b", "main")
        git(origin, "add", "-A")
        git(origin, "commit", "-q", "-m", "staging")
        self.state.mkdir()
        git(self.state, "clone", "-q", str(origin), "src")

        bin_dir = self.home / ".local" / "bin"   # first on the script's PATH
        bin_dir.mkdir(parents=True)
        self.stub_dir.mkdir()
        for name, body in STUBS.items():
            (bin_dir / name).write_text(body, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        self.write_secrets()

    def write_secrets(self, **keys: str) -> None:
        lines = {"CONTACT_EMAIL": "hello@example.org", "CONTACT_CITY": "Patiala", **keys}
        self.secrets.write_text("".join(f"{k}={v}\n" for k, v in lines.items()), encoding="utf-8")

    def commit(self, path: str, text: str, message: str = "change") -> None:
        """A new commit on origin's main that writes `text` to `path`."""
        target = self.origin / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", message)

    def stub_lines(self, name: str) -> list[str]:
        path = self.stub_dir / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    @property
    def build(self) -> dict:
        return json.loads((self.state / "src/deploy/staging/build/build.json").read_text(encoding="utf-8"))

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        for name in ("compose.env", "base_url", "calls", "cf_access", "github_calls", "github_stdin",
                     "built", "npx", "systemctl"):
            (self.stub_dir / name).unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(STAGING / "preview.sh"), *args],
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.home),
                "HOLT_STAGE_HOME": str(self.state),
                "HOLT_SECRETS_FILE": str(self.secrets),
                "HOLT_LOCAL_REPO": str(self.root / "no-local-repo"),
                "STUB_DIR": str(self.stub_dir),
                "FORCE": "1",   # don't wait for the machine running the tests to be quiet
                "SWAP_SETTLE": "0",
                **env,
            },
            capture_output=True, text=True, timeout=120,
        )

    def live(self, **env: str) -> dict[str, str]:
        """Run once and return what compose was started with."""
        done = self.run(**env)
        assert done.returncode == 0, done.stdout + done.stderr
        text = (self.stub_dir / "compose.env").read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.splitlines())

    @property
    def site(self) -> str:
        build = self.state / "src" / "deploy" / "staging" / "build" / "build.json"
        return json.loads(build.read_text(encoding="utf-8"))["site"]

    @property
    def base_url(self) -> str:
        return (self.stub_dir / "base_url").read_text(encoding="utf-8")

    @property
    def cf_access(self) -> tuple[str, str]:
        """The Cloudflare Access id and secret the smoke run was given."""
        id_, secret = (self.stub_dir / "cf_access").read_text(encoding="utf-8").splitlines()
        return id_, secret


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_the_default_host_is_staging_githolt_com(sandbox: Sandbox) -> None:
    started = sandbox.live()
    assert started["STAGING_HOST"] == DEFAULT_HOST
    assert sandbox.site == f"https://{DEFAULT_HOST}"
    assert sandbox.base_url == f"https://{DEFAULT_HOST}"


def test_the_env_file_holds_the_host_and_no_urls(sandbox: Sandbox) -> None:
    sandbox.live()
    written = sandbox.env_file.read_text(encoding="utf-8")
    assert f"STAGING_HOST={DEFAULT_HOST}\n" in written
    assert "HOLT_WEB_URL" not in written
    assert "NEXT_PUBLIC_SITE_HOST" not in written


def test_another_host_moves_every_url_and_is_remembered(sandbox: Sandbox) -> None:
    started = sandbox.live(STAGING_HOST="preview.example.org")
    assert started["STAGING_HOST"] == "preview.example.org"
    assert sandbox.site == "https://preview.example.org"
    assert sandbox.base_url == "https://preview.example.org"

    # The first run wrote it to .env; the timer's runs, which export nothing, keep it.
    assert sandbox.live()["STAGING_HOST"] == "preview.example.org"
    assert sandbox.site == "https://preview.example.org"


def test_an_env_file_from_the_old_address_moves_to_the_new_one(sandbox: Sandbox) -> None:
    sandbox.env_file.write_text(
        f"HOLT_STAGE_PORT=9110\nHOLT_WEB_URL=https://{OLD_HOST}\nNEXT_PUBLIC_SITE_HOST={OLD_HOST}\n",
        encoding="utf-8",
    )
    started = sandbox.live()
    assert started["STAGING_HOST"] == DEFAULT_HOST
    assert "HOLT_WEB_URL" not in started   # compose.yml writes it from STAGING_HOST
    assert sandbox.site == f"https://{DEFAULT_HOST}"
    assert sandbox.base_url == f"https://{DEFAULT_HOST}"


@pytest.mark.parametrize("host", ["https://staging.githolt.com", "staging.githolt.com/", "githolt.com", "www.githolt.com"])
def test_a_url_or_productions_host_is_refused(sandbox: Sandbox, host: str) -> None:
    done = sandbox.run(STAGING_HOST=host)
    assert done.returncode != 0
    assert "STAGING_HOST" in done.stdout
    assert not (sandbox.stub_dir / "calls").exists(), "nothing may be built for a host that was refused"


def test_sign_in_is_off_without_staging_keys(sandbox: Sandbox) -> None:
    started = sandbox.live()
    for key in ("AUTH_GITHUB_ID", "AUTH_GITHUB_SECRET", "AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET"):
        assert started[key] == ""


def test_staging_keys_turn_on_their_own_provider(sandbox: Sandbox) -> None:
    sandbox.write_secrets(
        GITHUB_OAUTH_ID="prod-id", GITHUB_OAUTH_SECRET="prod-secret",
        STAGING_GITHUB_OAUTH_ID="stage-id", STAGING_GITHUB_OAUTH_SECRET="stage-secret",
    )
    started = sandbox.live()
    assert (started["AUTH_GITHUB_ID"], started["AUTH_GITHUB_SECRET"]) == ("stage-id", "stage-secret")
    assert (started["AUTH_GOOGLE_ID"], started["AUTH_GOOGLE_SECRET"]) == ("", "")

    sandbox.write_secrets(STAGING_GOOGLE_OAUTH_ID="g-id", STAGING_GOOGLE_OAUTH_SECRET="g-secret")
    started = sandbox.live()
    assert (started["AUTH_GOOGLE_ID"], started["AUTH_GOOGLE_SECRET"]) == ("g-id", "g-secret")
    assert (started["AUTH_GITHUB_ID"], started["AUTH_GITHUB_SECRET"]) == ("", "")


def test_productions_keys_never_reach_staging(sandbox: Sandbox) -> None:
    prod = {
        "GITHUB_OAUTH_ID": "prod-id", "GITHUB_OAUTH_SECRET": "prod-secret",
        "GOOGLE_OAUTH_ID": "prod-g-id", "GOOGLE_OAUTH_SECRET": "prod-g-secret",
    }
    off = {"AUTH_GITHUB_ID": "", "AUTH_GITHUB_SECRET": "", "AUTH_GOOGLE_ID": "", "AUTH_GOOGLE_SECRET": ""}

    def auth(started: dict[str, str]) -> dict[str, str]:
        return {k: started[k] for k in off}

    # Only production's keys in the file: no fallback to them.
    sandbox.write_secrets(**prod)
    assert auth(sandbox.live()) == off

    # Production's keys copied under the staging names: refused.
    sandbox.write_secrets(
        **prod,
        STAGING_GITHUB_OAUTH_ID="prod-id", STAGING_GITHUB_OAUTH_SECRET="prod-secret",
        STAGING_GOOGLE_OAUTH_ID="prod-g-id", STAGING_GOOGLE_OAUTH_SECRET="other",
    )
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "production's key" in done.stdout
    assert auth(sandbox.live()) == off

    # Keys exported by whoever runs the script (say, after a production deploy): ignored.
    sandbox.write_secrets(**prod)
    assert auth(sandbox.live(AUTH_GITHUB_ID="prod-id", AUTH_GITHUB_SECRET="prod-secret")) == off


def test_half_a_key_pair_leaves_the_provider_off(sandbox: Sandbox) -> None:
    sandbox.write_secrets(STAGING_GITHUB_OAUTH_ID="stage-id")
    started = sandbox.live()
    assert (started["AUTH_GITHUB_ID"], started["AUTH_GITHUB_SECRET"]) == ("", "")


def test_secrets_are_not_logged(sandbox: Sandbox) -> None:
    sandbox.write_secrets(STAGING_GITHUB_OAUTH_ID="stage-id", STAGING_GITHUB_OAUTH_SECRET="stage-secret")
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "GitHub sign-in: on" in done.stdout
    assert "stage-secret" not in done.stdout + done.stderr


def test_the_smoke_run_gets_the_access_token_and_nothing_logs_it(sandbox: Sandbox) -> None:
    sandbox.write_secrets(STAGING_CF_ACCESS_CLIENT_ID="cf-id.access", STAGING_CF_ACCESS_CLIENT_SECRET="cf-secret-value")
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert sandbox.cf_access == ("cf-id.access", "cf-secret-value")
    assert "through Cloudflare Access" in done.stdout
    logs = "".join(p.read_text(encoding="utf-8") for p in (sandbox.state / "logs").glob("*.log"))
    for value in ("cf-id.access", "cf-secret-value"):
        assert value not in done.stdout + done.stderr + logs
    # The compose stack never sees it; only the smoke run does.
    assert "cf-secret" not in (sandbox.stub_dir / "compose.env").read_text(encoding="utf-8")


def test_without_the_access_token_the_smoke_run_is_unchanged(sandbox: Sandbox) -> None:
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert sandbox.cf_access == ("", "")
    assert "Cloudflare Access" not in done.stdout

    # Half a token is no token, and says so.
    sandbox.write_secrets(STAGING_CF_ACCESS_CLIENT_ID="cf-id.access")
    done = sandbox.run()
    assert sandbox.cf_access == ("", "")
    assert "needed together" in done.stdout
    assert "cf-id.access" not in done.stdout + done.stderr


def test_the_github_token_is_read_fresh_and_overrides_env_file(sandbox: Sandbox) -> None:
    # make-env.sh baked `gh auth token` into .env once; a rotated token leaves that stale.
    sandbox.live()
    text = sandbox.env_file.read_text(encoding="utf-8").replace("GITHUB_TOKENS=stub-token", "GITHUB_TOKENS=stale")
    sandbox.env_file.write_text(text, encoding="utf-8")

    # No secrets entry: the current `gh auth token`.
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert sandbox.live()["GITHUB_TOKENS"] == "stub-token"
    assert "using gh auth token" in done.stdout

    # A secrets entry wins.
    sandbox.write_secrets(GITHUB_TOKENS="ghp_fromsecrets1,ghp_fromsecrets2")
    done = sandbox.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert sandbox.live()["GITHUB_TOKENS"] == "ghp_fromsecrets1,ghp_fromsecrets2"
    # Each token was checked, on stdin, never in curl's arguments or a log.
    stdin = (sandbox.stub_dir / "github_stdin").read_text(encoding="utf-8")
    assert "Bearer ghp_fromsecrets1" in stdin and "Bearer ghp_fromsecrets2" in stdin
    calls = (sandbox.stub_dir / "github_calls").read_text(encoding="utf-8")
    logs = "".join(p.read_text(encoding="utf-8") for p in (sandbox.state / "logs").glob("*.log"))
    for text in (calls, done.stdout, done.stderr, logs):
        assert "ghp_fromsecrets" not in text


def test_a_refused_github_token_stops_the_build_loudly(sandbox: Sandbox) -> None:
    sandbox.write_secrets(GITHUB_TOKENS="ghp_revoked")
    done = sandbox.run(STUB_GITHUB_STATUS="401")
    assert done.returncode != 0
    assert "GitHub refused token 1" in done.stdout
    assert "ghp_revoked" not in done.stdout + done.stderr
    assert not (sandbox.stub_dir / "compose.env").exists(), "nothing may start with a refused token"
    build = json.loads((sandbox.state / "src/deploy/staging/build/build.json").read_text(encoding="utf-8"))
    assert "refused" in build["last_attempt"]["message"]
    # The next tick tries again (no FORCE needed) once the token is fixed.
    assert not (sandbox.state / "fingerprint").exists()


def test_the_old_address_is_gone_from_what_runs_staging() -> None:
    checked = [p for p in STAGING.iterdir() if p.is_file()]
    checked += [Path("deploy/README.md"), Path("e2e/playwright.config.ts"), Path("e2e/lighthouse.mjs")]
    left = [str(p) for p in checked if OLD_HOST in p.read_text(encoding="utf-8")]
    assert left == []


def test_compose_takes_every_url_from_the_host_setting() -> None:
    compose = (STAGING / "compose.yml").read_text(encoding="utf-8")
    host = "${STAGING_HOST:-" + DEFAULT_HOST + "}"
    assert f"HOLT_WEB_URL: https://{host}\n" in compose
    assert f"AUTH_URL: https://{host}\n" in compose
    assert compose.count(f"NEXT_PUBLIC_SITE_HOST: {host}\n") == 2   # build arg and runtime
    assert "${HOLT_WEB_URL" not in compose and "${NEXT_PUBLIC_SITE_HOST" not in compose
    # What must not move with the address.
    assert compose.count('ROBOTS_NOINDEX: "1"\n') == 2
    assert 'TRUST_PROXY_HEADERS: "1"\n' in compose
    assert '"127.0.0.1:${HOLT_STAGE_PORT:-9110}:8080"' in compose


# Not FORCE, so the per-image checks run, and never waiting on the machine running the tests.
QUIET = {"FORCE": "0", "HOLT_STAGE_MAX_LOAD": "1000", "HOLT_STAGE_MAX_LOAD_LIGHT": "1000", "HOLT_STAGE_MIN_AVAIL_MB": "0"}
UNIT = {**QUIET, "HOLT_STAGE_SMOKE_UNIT": "holt-stage-smoke.service"}


def test_only_the_images_whose_inputs_changed_are_rebuilt(sandbox: Sandbox) -> None:
    def rebuilt() -> list[str]:
        done = sandbox.run(**QUIET)
        assert done.returncode == 0, done.stdout + done.stderr
        assert (sandbox.stub_dir / "compose.env").exists(), "the stack is restarted either way"
        return sandbox.stub_lines("built")

    assert rebuilt() == ["server", "web"]            # first run: nothing recorded yet

    sandbox.commit("web/src/page.tsx", "export default 1\n")
    assert rebuilt() == ["web"]                        # a web-only change never rebuilds the server
    sandbox.commit("src/holt/engine.py", "x = 1\n")
    assert rebuilt() == ["server"]
    sandbox.commit("uv.lock", "lock\n")
    assert rebuilt() == ["server"]
    sandbox.commit("deploy/web/Dockerfile", "FROM scratch\n")
    assert rebuilt() == ["web"]
    sandbox.commit("docs/notes.md", "neither image reads this\n")
    assert rebuilt() == []

    # A build arg (the contact city is baked into the web bundle).
    sandbox.write_secrets(CONTACT_CITY="Delhi")
    sandbox.commit("docs/notes.md", "move the fingerprint\n")
    assert rebuilt() == ["web"]

    # An image that is gone (or was rebuilt by something else) is rebuilt.
    (sandbox.stub_dir / "image-stage-holt-new-server:latest").unlink()
    sandbox.commit("docs/notes.md", "again\n")
    assert rebuilt() == ["server"]

    # FORCE=1 rebuilds everything.
    assert sandbox.run(**{**QUIET, "FORCE": "1"}).returncode == 0
    assert sandbox.stub_lines("built") == ["server", "web"]


def test_a_dry_run_says_what_it_would_build_and_changes_nothing(sandbox: Sandbox) -> None:
    assert sandbox.run(**QUIET).returncode == 0
    build_before = sandbox.build
    fingerprint = (sandbox.state / "fingerprint").read_text(encoding="utf-8")

    sandbox.commit("web/src/page.tsx", "export default 2\n")
    done = sandbox.run("--dry-run", **UNIT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "would build web for" in done.stdout
    assert sandbox.stub_lines("built") == []
    assert not (sandbox.stub_dir / "compose.env").exists()
    assert sandbox.stub_lines("systemctl") == []
    assert sandbox.build == build_before
    assert (sandbox.state / "fingerprint").read_text(encoding="utf-8") == fingerprint

    # The real run still sees the change.
    assert sandbox.run(**QUIET).returncode == 0
    assert sandbox.stub_lines("built") == ["web"]


def test_build_says_what_it_is_doing_now(sandbox: Sandbox) -> None:
    done = sandbox.run(**QUIET)
    assert done.returncode == 0, done.stdout + done.stderr
    sha = sandbox.build["live"]["preview_sha"][:7]

    def seen(name: str) -> dict:
        return json.loads((sandbox.stub_dir / name).read_text(encoding="utf-8"))

    assert seen("now-while-building-web") | {"since": ""} == {
        "state": "building", "message": f"building web ({sha})", "since": ""}
    assert seen("now-while-starting")["state"] == "starting"
    now = sandbox.build["now"]
    assert now["state"] == "live" and sha in now["message"] and now["since"]

    sandbox.commit("web/src/page.tsx", "broken\n")
    done = sandbox.run(**QUIET, STUB_BUILD_FAILS="1")
    assert done.returncode != 0
    assert sandbox.build["now"]["state"] == "failed"
    assert sandbox.build["last_attempt"]["status"] == "failed"
    assert sandbox.build["live"]["preview_sha"][:7] == sha, "what is live didn't change"


def test_the_smoke_run_uses_three_browsers_after_the_site_is_live(sandbox: Sandbox) -> None:
    done = sandbox.run(**QUIET)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.index("live: ") < done.stdout.index("smoke: ")
    assert any("--workers=3" in line for line in sandbox.stub_lines("npx"))
    assert sandbox.build["smoke"]["status"] == "passed"
    assert sandbox.build["now"]["state"] == "live"

    sandbox.commit("web/src/page.tsx", "x\n")
    assert sandbox.run(**QUIET, HOLT_STAGE_SMOKE_WORKERS="2").returncode == 0
    assert any("--workers=2" in line for line in sandbox.stub_lines("npx"))


def test_the_smoke_run_can_be_skipped_for_one_build(sandbox: Sandbox) -> None:
    def smoke(*args: str, **env: str) -> dict:
        done = sandbox.run(*args, **{**QUIET, **env})
        assert done.returncode == 0, done.stdout + done.stderr
        assert sandbox.build["now"]["state"] == "live"
        return sandbox.build["smoke"]

    ran = lambda: bool(sandbox.stub_lines("npx"))  # noqa: E731

    assert smoke("--no-smoke")["status"] == "skipped" and not ran()
    assert "--no-smoke" in sandbox.build["smoke"]["message"]

    sandbox.commit("web/src/page.tsx", "1\n", message="Tweak the header [skip smoke]")
    assert smoke()["status"] == "skipped" and not ran()
    assert "[skip smoke]" in sandbox.build["smoke"]["message"]

    # That commit isn't new in the next build, so the next one runs.
    sandbox.commit("web/src/page.tsx", "2\n", message="Tweak the footer")
    assert smoke()["status"] == "passed" and ran()

    sandbox.commit("web/src/page.tsx", "3\n")
    assert smoke(HOLT_STAGE_SMOKE="0")["status"] == "skipped" and not ran()

    # The file skips every build until it is removed.
    (sandbox.state / "no-smoke").touch()
    sandbox.commit("web/src/page.tsx", "4\n")
    assert smoke()["status"] == "skipped" and not ran()


def test_under_the_timer_the_smoke_run_is_its_own_unit(sandbox: Sandbox) -> None:
    done = sandbox.run(**UNIT)
    assert done.returncode == 0, done.stdout + done.stderr
    # The build hands it off and ends, so the next change isn't held up by it.
    assert "systemctl --user start --no-block holt-stage-smoke.service" in sandbox.stub_lines("systemctl")
    assert not sandbox.stub_lines("npx")
    assert sandbox.build["now"]["state"] == "smoke"

    # What the unit runs: the suite from the live commit, against the site.
    done = sandbox.run("--smoke", **UNIT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert any("--workers=3" in line for line in sandbox.stub_lines("npx"))
    assert sandbox.base_url == f"https://{DEFAULT_HOST}"
    assert sandbox.build["smoke"]["status"] == "passed"
    assert sandbox.build["now"]["state"] == "live"

    # Nothing changed: a running smoke run is left alone.
    (sandbox.stub_dir / "smoke_unit_state").write_text("activating\n", encoding="utf-8")
    assert sandbox.run(**UNIT).returncode == 0
    assert not any(" stop " in line for line in sandbox.stub_lines("systemctl"))

    # A newer change stops it before building: it would be testing a site about to change.
    sandbox.commit("web/src/page.tsx", "x\n")
    done = sandbox.run(**UNIT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "systemctl --user stop holt-stage-smoke.service" in sandbox.stub_lines("systemctl")
    assert "stopped the previous build's run" in done.stdout


def test_the_timer_ticks_every_minute_and_knows_its_smoke_unit() -> None:
    text = (STAGING / "install.sh").read_text(encoding="utf-8")
    assert "OnUnitInactiveSec=1min" in text
    assert "Environment=HOLT_STAGE_SMOKE_UNIT=holt-stage-smoke.service" in text
    assert "ExecStart=$STATE/bin/preview.sh --smoke" in text
