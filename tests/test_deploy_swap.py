"""Deploys never show Cloudflare's error page.

Two parts, both easy to break without noticing until a deploy:

- `deploy/swap.sh` starts a service's new container next to the old one and
  retires the old one only once the new one is healthy. That needs a
  healthcheck on server and web, and neither may publish a port or pin a
  container name (two of each run for a moment).
- the edge (`deploy/*/edge.conf`) answers nginx's own 502/503/504 with a
  small "Holt is updating" page: a 503 that is never cached, with
  Retry-After, identical on prod and staging.

`swap_service` runs here for real, in bash, with `docker` replaced by a stub
that keeps a list of containers. Nothing is started.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

DEPLOY = Path("deploy")
EDGES = [DEPLOY / "prod" / "edge.conf", DEPLOY / "staging" / "edge.conf"]
COMPOSES = [DEPLOY / "prod" / "compose.yml", DEPLOY / "staging" / "compose.yml"]


def updating_block(conf: Path) -> str:
    text = conf.read_text(encoding="utf-8")
    start = text.index("    location @updating {")
    end = text.index("\n    }\n", start)
    return text[start:end]


def page(conf: Path) -> str:
    return re.search(r"return 503 '(.*?)';", updating_block(conf), re.S).group(1)


def test_prod_and_staging_show_the_same_updating_page() -> None:
    assert updating_block(EDGES[0]) == updating_block(EDGES[1])


@pytest.mark.parametrize("conf", EDGES, ids=lambda p: p.parent.name)
def test_the_updating_page_is_an_uncached_503(conf: Path) -> None:
    block = updating_block(conf)
    assert "return 503 '" in block
    assert 'add_header Cache-Control "no-store" always;' in block
    assert "add_header Retry-After 10 always;" in block
    assert 'default_type "text/html; charset=utf-8";' in block


@pytest.mark.parametrize("conf", EDGES, ids=lambda p: p.parent.name)
def test_only_the_web_proxy_falls_back_to_it(conf: Path) -> None:
    text = conf.read_text(encoding="utf-8")
    # In `location /` only: the Umami paths keep their plain 502.
    assert text.count("error_page 502 503 504 = @updating;") == 1
    web = text[text.index("    location / {"):text.index("    location @updating")]
    assert "error_page 502 503 504 = @updating;" in web
    # Never the app's own error pages.
    assert "proxy_intercept_errors" not in text
    assert "proxy_connect_timeout 1s;" in web
    assert "proxy_next_upstream error timeout non_idempotent;" in web


@pytest.mark.parametrize("conf", EDGES, ids=lambda p: p.parent.name)
def test_the_page_is_a_safe_nginx_string_and_reads_plainly(conf: Path) -> None:
    html = page(conf)
    # nginx would end the string at a quote and expand $name as a variable.
    assert "'" not in html and "$" not in html
    assert "Holt is updating." in html
    assert "Back in a few seconds." in html
    assert "prefers-color-scheme:dark" in html
    assert 'http-equiv="refresh" content="5"' in html   # without JavaScript
    assert "5000" in html                                # with it


@pytest.mark.parametrize("compose", COMPOSES, ids=lambda p: p.parent.name)
def test_server_and_web_can_run_twice_during_a_swap(compose: Path) -> None:
    services = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]
    for name in ("server", "web"):
        svc = services[name]
        assert "ports" not in svc and "container_name" not in svc, name
        check = svc["healthcheck"]
        assert check["test"][0] == "CMD", name
        assert check["start_interval"] == "1s", name


# --- swap_service, with a stub docker ------------------------------------------

STUB = r"""#!/bin/bash
# Containers are lines "<id> <state>" in $STUB_DIR/containers. A new one's
# state is $STUB_NEW_STATE (default healthy).
echo "docker $*" >> "$STUB_DIR/calls"
db="$STUB_DIR/containers"; touch "$db"
case "$1" in
    compose)
        case " $* " in
            *" ps "*) cut -d' ' -f1 "$db" ;;
            *" config --hash "*) echo "web hash1" ;;
            *" up "*)
                all="$*"; want="${all##*--scale }"; want="${want%% *}"; want="${want#*=}"
                have=$(grep -c . "$db")
                while (( have < want )); do
                    have=$((have + 1)); echo "new$have ${STUB_NEW_STATE:-healthy}" >> "$db"
                done ;;
        esac ;;
    image) echo "sha256:img" ;;   # image inspect: the tag's current image
    inspect) id="${@: -1}"; state=$(grep "^$id " "$db" | cut -d' ' -f2)
        if [[ "$*" == *config-hash* ]]; then   # swap.sh's "already current?" check
            [[ -n "$STUB_CURRENT" ]] && echo "hash1 sha256:img $state web:tag" || echo "hash0 sha256:old $state web:tag"
            exit 0
        fi
        restarts=0; [[ "$state" == crashing ]] && { restarts=2; state=restarting; }
        echo "$restarts $state" ;;
    logs) echo "boom: port in use" ;;
    stop) ;;
    rm) for id in "$@"; do sed -i "/^$id /d" "$db"; done ;;
esac
exit 0
"""


@pytest.fixture
def stub(tmp_path: Path) -> Path:
    if sys.platform == "win32" or not shutil.which("bash"):
        pytest.skip("the deploy scripts are bash and run on the Linux server")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STUB, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    return tmp_path


def swap(stub: Path, containers: str, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    (stub / "containers").write_text(containers, encoding="utf-8")
    script = f"""
compose() {{ docker compose "$@"; }}
. {DEPLOY.resolve() / "swap.sh"}
swap_service web 5; rc=$?
echo "$SWAP_MSG"; exit $rc
"""
    done = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{stub / 'bin'}:{os.environ['PATH']}", "STUB_DIR": str(stub), "SWAP_SETTLE": "0", **env},
        capture_output=True, text=True, timeout=60,
    )
    return done, (stub / "containers").read_text(encoding="utf-8")


def test_the_old_container_goes_only_after_the_new_one_is_healthy(stub: Path) -> None:
    done, left = swap(stub, "old1 healthy\n")
    assert done.returncode == 0, done.stdout + done.stderr
    assert left == "new2 healthy\n"
    calls = (stub / "calls").read_text(encoding="utf-8")
    assert "--no-recreate --scale web=2 web" in calls
    assert calls.index("inspect") < calls.index("stop -t 30 old1")
    assert "old one retired" in done.stdout


def test_an_unhealthy_new_container_is_removed_and_the_old_one_stays(stub: Path) -> None:
    done, left = swap(stub, "old1 healthy\n", STUB_NEW_STATE="unhealthy")
    assert done.returncode == 1
    assert left == "old1 healthy\n"
    assert "the old one keeps serving" in done.stdout
    assert "boom: port in use" in done.stdout
    assert "stop" not in (stub / "calls").read_text(encoding="utf-8")


def test_a_new_container_that_never_gets_healthy_times_out(stub: Path) -> None:
    done, left = swap(stub, "old1 healthy\n", STUB_NEW_STATE="starting")
    assert done.returncode == 1
    assert left == "old1 healthy\n"
    assert "not healthy after 5s" in done.stdout


def test_a_crashing_new_container_fails_at_once(stub: Path) -> None:
    # restart: unless-stopped keeps bringing it back; that is not "starting".
    done, left = swap(stub, "old1 healthy\n", STUB_NEW_STATE="crashing")
    assert done.returncode == 1
    assert left == "old1 healthy\n"
    assert "crashing (restarted 2x)" in done.stdout
    assert (stub / "calls").read_text(encoding="utf-8").count("RestartCount") == 1


def test_a_first_run_just_starts_the_service(stub: Path) -> None:
    done, left = swap(stub, "")
    assert done.returncode == 0, done.stdout + done.stderr
    assert left == "new1 healthy\n"
    assert "retired" not in done.stdout


def test_an_unchanged_service_is_left_running(stub: Path) -> None:
    # Same config and image as the running container: no new one, no restart
    # (a server restart would interrupt its jobs).
    done, left = swap(stub, "old1 running\n", STUB_CURRENT="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert left == "old1 running\n"
    assert "unchanged, left running" in done.stdout
    calls = (stub / "calls").read_text(encoding="utf-8")
    assert "--scale" not in calls and "stop" not in calls
