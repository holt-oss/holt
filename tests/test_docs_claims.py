"""The prose is now asserted, like everything else.

Every guard in this project points at the agent: the holdout is asserted per
record, Stage D drops a citation that does not resolve, replay refuses a
recording whose prompt moved. None of them watched the sentences we write about
the results, so a number stayed on the page after the run behind it was redone
and nothing failed. That is how verdict stability came to be published three
different ways at once, and how the reproduction guide came to promise a test
count that had been wrong for weeks.

These tests close that gap in the only way that lasts: the documented numbers
are recomputed from the committed results and must appear, verbatim, in the
documents that claim them -- and every command the guide prints must run.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from holt.cli import main

EVALUATION = Path("docs/EVALUATION.md")
REPRODUCTION = Path("REPRODUCTION.md")
USAGE = Path("USAGE.md")

POOL1 = [Path(f"eval/results_eval_run{i}.json") for i in (1, 2, 3)]
POOL2 = [Path(f"eval/results_eval_p2r{i}.json") for i in (1, 2, 3)]


def runs(paths: list[Path]) -> list[dict]:
    return [json.loads(p.read_text()) for p in paths]


def mean_metric(paths: list[Path], method: str, metric: str) -> float:
    return statistics.mean(
        next(x[metric] for x in r["results"] if x["method"] == method) for r in runs(paths)
    )


def stability(paths: list[Path], method: str) -> tuple[int, int]:
    """How many repositories got the identical verdict in every run."""
    rs = runs(paths)
    slugs = sorted(rs[0]["verdicts"]["holt"])
    same = sum(1 for s in slugs if len({r["verdicts"][method].get(s) for r in rs}) == 1)
    return same, len(slugs)


# --- the numbers -----------------------------------------------------------


def test_evaluation_states_the_measured_verdict_stability():
    """The claim that broke: 21/22 and 13/22 outlived the runs behind them."""
    holt_same, total = stability(POOL1, "holt")
    base_same, _ = stability(POOL1, "baseline")
    text = EVALUATION.read_text()
    assert f"**{holt_same} of {total}**" in text, (
        f"EVALUATION should say Holt is stable on {holt_same} of {total} pool-1 repositories"
    )
    assert f"**{base_same} of {total}**" in text, (
        f"EVALUATION should say the baseline is stable on {base_same} of {total}"
    )


def test_evaluation_states_the_combined_stability_across_both_pools():
    h1, n1 = stability(POOL1, "holt")
    h2, n2 = stability(POOL2, "holt")
    b1, _ = stability(POOL1, "baseline")
    b2, _ = stability(POOL2, "baseline")
    moved = (n1 - b1) + (n2 - b2)
    text = EVALUATION.read_text()
    assert f"**{h1 + h2} of {n1 + n2}**" in text
    assert f"changed its answer on {moved} of {n1 + n2}" in text


@pytest.mark.parametrize("paths,method", [
    (POOL1, "holt"), (POOL1, "baseline"), (POOL1, "name_only"),
    (POOL2, "holt"), (POOL2, "baseline"), (POOL2, "name_only"),
    (POOL2, "baseline_matched"),
])
def test_evaluation_headline_mcc_matches_the_committed_runs(paths, method):
    """Every MCC in the two headline tables is recomputed and must be on the page."""
    value = mean_metric(paths, method, "mcc")
    assert f"{value:.2f}" in EVALUATION.read_text(), (
        f"{method} MCC {value:.2f} is not stated in docs/EVALUATION.md"
    )


def test_usage_states_the_measured_balanced_accuracy():
    """The usage guide tells a user how often to expect a wrong call.

    It is the one number on that page a reader will act on, and it was written
    by hand from the README's tables. Recompute it here so it cannot drift the
    way the stability claim did.
    """
    text = USAGE.read_text()
    for paths in (POOL1, POOL2):
        value = mean_metric(paths, "holt", "balanced_accuracy")
        assert f"{value:.2f}" in text, (
            f"USAGE.md should state balanced accuracy {value:.2f}"
        )


# --- the commands ----------------------------------------------------------


def documented_holt_commands() -> list[list[str]]:
    """Every `holt ...` invocation the docs print, minus the paid ones.

    Both guides are covered. `USAGE.md` is the page a user actually follows, so
    a command that only appears there is exactly the kind that breaks unnoticed
    -- which is how `--baseline --replay` came to be broken on every repository
    while the benchmark stayed green.
    """
    found = []
    for doc in (REPRODUCTION, USAGE):
        for line in doc.read_text().splitlines():
            line = line.strip()
            m = re.match(
                r"^(?:(?:PYTHONPATH=\. )?uv run )?holt "
                r"((?:analyze|compare|next|profile|discover|models|tui)(?: .*)?)$",
                line,
            )
            if not m:
                continue
            # The guides annotate some commands with the verdict they produce
            # (`... --replay   # not_viable`); that is prose, not an argument.
            argv = m.group(1).split("#")[0].split()
            if "--live" in argv:  # needs GITHUB_TOKEN and money; documented as optional
                continue
            if argv[:1] == ["tui"]:  # opens an interactive screen; covered by its own suite
                continue
            if argv not in found:
                found.append(argv)
    return found


def test_the_guides_actually_print_commands():
    """Guards the parser above: a silent zero would make the next test vacuous."""
    assert len(documented_holt_commands()) >= 5
    assert any(a[:1] == ["profile"] for a in documented_holt_commands()), (
        "USAGE.md should still show how to state a profile"
    )


@pytest.mark.parametrize("argv", documented_holt_commands(), ids=lambda a: " ".join(a))
def test_every_documented_command_runs(argv, monkeypatch, tmp_path):
    """`--baseline --replay` was documented twice and failed on every repository.

    It failed because the baseline call was only ever recorded under the
    run-tagged directories the harness reads, so nothing under
    fixtures/trajectories/ could answer one. The benchmark never noticed, which
    is precisely why this test runs the *documented* path rather than the
    measured one.
    """
    # A model chosen with `holt models` must not reach a replay, so point the
    # config at an empty directory and prove the command still works.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    assert code == 0
    assert out.getvalue().strip(), f"holt {' '.join(argv)} printed nothing"


def test_a_chosen_model_does_not_break_a_replay(monkeypatch, tmp_path):
    """The regression that silently broke six of the seven documented commands.

    Selecting a model writes it to disk, and the id is part of a call's
    identity, so every committed recording became a replay miss -- reported as
    "the prompt or the stage's model has changed", which named the prompt first
    and sent a reader looking in the wrong place.
    """
    config = tmp_path / "holt"
    config.mkdir()
    (config / "models.toml").write_text(
        'provider = "ollama"\nmodel = "llama3.2:latest"\n'
        'base_url = "http://localhost:11434/v1"\napi_key_env = "OLLAMA_API_KEY"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["analyze", "NixOS/nixpkgs", "--baseline", "--replay"])
    assert code == 0
    assert "NixOS/nixpkgs" in out.getvalue()


# --- the test count the guide promises -------------------------------------


def test_reproduction_promises_the_real_test_count():
    """`128 passed` sat on the page while the suite was elsewhere entirely.

    The default install includes the product's terminal interface, so the guide
    states one complete count. The number in front of the reader must match it.
    """
    promised = [int(n) for n in re.findall(r"`(\d+) passed", REPRODUCTION.read_text())]
    assert promised, "REPRODUCTION.md no longer states an expected test count"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    collected = re.search(r"(\d+) tests? collected", result.stdout)
    assert collected, f"could not read a collection count:\n{result.stdout[-2000:]}"
    assert int(collected.group(1)) in promised, (
        f"the suite collects {collected.group(1)} tests; "
        f"REPRODUCTION.md promises {promised}"
    )
