"""Production's warm scripts hand the pass the right job.

`deploy/prod/warm.sh` and `warm-refresh.sh` run here for real with `docker`
stubbed, so nothing is started. What must hold: a dry run never becomes a
detached pass or waits for the one that is running, and neither script gives
a refresh tier an age of its own: the tier's age comes from one place, the
server's HOLT_REFRESH_*_HOURS, which compose.yml passes through. (On 6 Oct
2026 `warm.sh --tier monthly` passed none and the pass fell back to 20 hours.)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROD = Path("deploy/prod").resolve()

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"),
    reason="the production scripts are bash and run on the Linux server",
)

DOCKER_STUB = """#!/bin/sh
echo "$*" >> "$STUB_DIR/docker"
case " $* " in
    *" ps "*) [ -f "$STUB_DIR/warm_running" ] && echo abc123 ;;
esac
exit 0
"""


class Rig:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.state = tmp / "state"
        self.stubs = tmp / "stubs"
        bin_ = self.home / ".local" / "bin"
        for d in (bin_, self.state, self.stubs):
            d.mkdir(parents=True)
        (bin_ / "docker").write_text(DOCKER_STUB, encoding="utf-8")
        (bin_ / "docker").chmod(0o755)
        (self.state / "current").write_text("abc1234\n", encoding="utf-8")
        (self.state / ".env").write_text("", encoding="utf-8")
        # warm-refresh.sh uses the deployed commit's compose file and env.sh.
        shutil.copytree(PROD, self.state / "src" / "deploy" / "prod")

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.home / '.local' / 'bin'}:{os.environ['PATH']}",
            "STUB_DIR": str(self.stubs),
            "HOLT_PROD_HOME": str(self.state),
            "HOLT_PROD_PROJECT": "warm-test",
            "GITHUB_TOKENS": "not-a-token",
        }
        return subprocess.run(["bash", str(PROD / script), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def runs(self) -> list[str]:
        """The `docker compose ... run` calls, as the stub saw them."""
        p = self.stubs / "docker"
        calls = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        return [c for c in calls if " run " in c]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


@pytest.mark.parametrize("args", [("--dry-run", "--tier", "monthly"),
                                  ("--tier", "monthly", "--dry-run")])
def test_a_dry_run_is_in_the_foreground_even_while_a_pass_runs(rig: Rig, args) -> None:
    (rig.stubs / "warm_running").touch()
    r = rig.run("warm.sh", *args)
    assert r.returncode == 0, r.stderr
    [call] = rig.runs()
    assert " run --rm --no-deps server python -m holt_server.warm " in call
    assert call.endswith(" ".join(args)) and " -d " not in call


def test_a_pass_is_detached_and_a_second_one_is_not_started(rig: Rig) -> None:
    r = rig.run("warm.sh", "--tier", "monthly", "--wait-for-budget")
    assert r.returncode == 0, r.stderr
    [call] = rig.runs()
    assert " run -d --no-deps --name warm-test-warm " in call
    assert call.endswith("python -m holt_server.warm --tier monthly --wait-for-budget")

    (rig.stubs / "warm_running").touch()
    again = rig.run("warm.sh", "--tier", "monthly")
    assert "already running" in again.stdout and len(rig.runs()) == 1


def test_neither_script_gives_a_tier_an_age_of_its_own(rig: Rig) -> None:
    assert rig.run("warm.sh", "--tier", "weekly").returncode == 0
    r = rig.run("warm-refresh.sh")
    assert r.returncode == 0, r.stderr
    by_hand, weekly, monthly = rig.runs()
    assert weekly.endswith("--tier weekly") and monthly.endswith("--tier monthly")
    for call in (by_hand, weekly, monthly):
        assert "HOLT_WARM_MAX_AGE_HOURS" not in call and "_HOURS" not in call


def test_the_server_gets_the_tiers_ages_from_compose() -> None:
    compose = yaml.safe_load((PROD / "compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["server"]["environment"]
    assert env["HOLT_REFRESH_WEEKLY_HOURS"] == "${HOLT_REFRESH_WEEKLY_HOURS:-168}"
    assert env["HOLT_REFRESH_MONTHLY_HOURS"] == "${HOLT_REFRESH_MONTHLY_HOURS:-720}"
