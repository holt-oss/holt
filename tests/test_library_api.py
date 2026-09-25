"""The engine as the web server calls it: signatures, progress, and file hygiene."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from holt import model
from holt.agent import pipeline
from holt.evidence.fixtures import FixtureProvider
from holt.types import Window

CANARY = "home-assistant/core"


def test_signatures_the_server_relies_on():
    for fn in (pipeline.analyze, pipeline.analyze_without_model):
        params = inspect.signature(fn).parameters
        assert list(params)[:2] == ["repo", "provider"]
        assert params["progress"].default is None
        assert params["as_of"].default is None
    assert list(inspect.signature(pipeline.analyze).parameters)[:5] == [
        "repo", "provider", "model", "contributor_days", "as_of"]


def test_progress_is_reported_in_order_for_the_full_pipeline():
    seen: list[tuple[str, float]] = []
    pipeline.analyze(
        CANARY, FixtureProvider(Window.PRE_T), model.build(CANARY, replay=True),
        progress=lambda stage, fraction: seen.append((stage, fraction)),
    )
    stages = [s for s, _ in seen]
    assert stages[0] == "Fetching pull requests"
    assert "Reading threads" in stages and "Checking evidence" in stages
    assert "Writing the report" in stages
    assert seen[-1] == ("Done", 1.0)
    fractions = [f for _, f in seen]
    assert fractions == sorted(fractions)
    assert all(0.0 <= f <= 1.0 for f in fractions)
    # Plain English: no underscores or internal stage letters.
    assert not any("_" in s for s in stages)


def test_progress_is_reported_without_a_model():
    seen: list[tuple[str, float]] = []
    pipeline.analyze(CANARY, FixtureProvider(Window.PRE_T), None,
                     progress=lambda s, f: seen.append((s, f)))
    assert seen[0][0] == "Fetching pull requests" and seen[-1] == ("Done", 1.0)


def test_a_failing_progress_callback_does_not_fail_the_analysis():
    def broken(stage, fraction):
        raise RuntimeError("the browser went away")

    assessment, _ = pipeline.analyze_without_model(CANARY, FixtureProvider(Window.PRE_T),
                                                   progress=broken)
    assert assessment.verdict


def test_the_trace_says_which_fields_a_model_wrote():
    _, with_model = pipeline.analyze(CANARY, FixtureProvider(Window.PRE_T),
                                     model.build(CANARY, replay=True))
    assert with_model.model_written == ("summary", "bottom_line", "limits")
    _, without = pipeline.analyze_without_model(CANARY, FixtureProvider(Window.PRE_T))
    assert without.model_written == ()


def test_model_rationale_is_labelled_on_evidence_claims():
    assessment, _ = pipeline.analyze(CANARY, FixtureProvider(Window.PRE_T),
                                     model.build(CANARY, replay=True))
    noted = [c for c in assessment.claims if "(" in c.text and "thread outcome" not in c.text]
    assert noted, "the canary has at least one finding with a rationale"
    assert all(pipeline.MODEL_NOTE_LABEL in c.text for c in noted if " (" in c.text)


def test_fixture_root_can_be_pointed_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLT_FIXTURE_ROOT", str(tmp_path))
    assert FixtureProvider(Window.PRE_T).root == tmp_path


def test_every_file_call_in_the_engine_names_utf8():
    """Windows defaults to a legacy code page; every text read and write says utf-8."""
    root = Path(__file__).resolve().parent.parent / "src" / "holt"
    files = [*(root / "agent").glob("*.py"), *(root / "evidence").glob("*.py"),
             root / "reponame.py", root / "model.py"]
    offenders = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"open", "read_text", "write_text"}:
                continue
            if not any(k.arg == "encoding" for k in node.keywords):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
