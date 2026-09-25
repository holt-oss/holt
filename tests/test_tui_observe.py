"""The TUI's observation layer, and the coupling it is allowed to have.

Three things are held here:

* Watching a run does not change it. The assessment produced with the observers
  in place is identical to the one produced without them, because a second way
  of running a stage is exactly what this feature must not become.
* The keys `holt.tui.observe` reads off each stage's response still exist. That
  file mirrors `holt.agent.stages` so the live view can show a claim before
  Stage D judges it; the mirror is pinned here so a schema change breaks a test
  instead of silently emptying a panel.
* The Stage D drop reaches the event stream, from a repository where a drop
  really happens rather than a constructed one.

None of these import Textual. The observation layer is useful without a
terminal, and the tests run on a checkout that never installed the extra.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from holt import model
from holt.agent import pipeline
from holt.evidence.fixtures import FixtureProvider
from holt.tui import events
from holt.tui.observe import EXPECTED_KEYS, ObservingModel, ObservingProvider
from holt.tui.session import RunOptions, Session
from holt.types import Window

# A repository whose recorded run drops a finding: the model cited
# `no_contributing_file`, an id it invented, which does not resolve.
DROPS = "Sistema-de-certificacion-academica/Sistema-de-certificacion-academica"
CLEAN = "home-assistant/core"

from tests.replay_health import reason as _replay_reason

pytestmark = pytest.mark.skipif(
    _replay_reason() is not None, reason=_replay_reason() or ""
)


def _run(repo: str, emit=None):
    events_seen: list = []
    emit = emit or events_seen.append
    provider = ObservingProvider(FixtureProvider(Window.PRE_T), emit)
    client = ObservingModel(model.build(repo, replay=True), emit, repo)
    assessment, trace = pipeline.analyze(repo, provider, client)
    return assessment, trace, events_seen


def test_observing_does_not_change_the_result():
    """The wrappers are pure delegates, and this is what that has to mean."""
    watched, watched_trace, _ = _run(DROPS)

    plain_assessment, plain_trace = pipeline.analyze(
        DROPS, FixtureProvider(Window.PRE_T), model.build(DROPS, replay=True)
    )

    assert watched.verdict == plain_assessment.verdict
    assert watched.summary == plain_assessment.summary
    assert watched.render() == plain_assessment.render()
    assert [(c.text, c.evidence_id) for c in watched.claims] == [
        (c.text, c.evidence_id) for c in plain_assessment.claims
    ]
    assert watched_trace.before_verification == plain_trace.before_verification
    assert watched_trace.after_verification == plain_trace.after_verification
    assert [d.field for d in watched_trace.dropped] == [
        d.field for d in plain_trace.dropped
    ]


@pytest.mark.parametrize("repo", [CLEAN, DROPS])
def test_stage_responses_still_carry_the_keys_the_live_view_reads(repo):
    """`observe.py` mirrors `stages.py`. If the mirror cracks, fail loudly.

    A live view that renders nothing because a key was renamed looks like a
    working interface with a quiet repository behind it, which is the worst
    failure mode available to this feature.
    """
    _, _, seen = _run(repo)
    responses = {e.stage: e.payload for e in seen if isinstance(e, events.ToolResponse)}

    for stage, keys in EXPECTED_KEYS.items():
        assert stage in responses, f"no recorded response for stage {stage!r}"
        for key in keys:
            assert key in responses[stage], (
                f"stage {stage!r} no longer returns {key!r}; "
                "holt.tui.observe reads it to build the live view"
            )


def test_every_finding_the_engine_records_is_also_emitted():
    """The stream shows the same number of claims the engine actually built."""
    _, trace, seen = _run(DROPS)
    emitted = [e for e in seen if isinstance(e, events.FindingEmitted)]
    assert len(emitted) == trace.before_verification


def test_the_drop_reaches_the_event_stream():
    """Stage D removed a claim, and the stream says so.

    Under the current recordings the dropped finding cites nothing at all — the
    model asserted `onboarding = absent` without pointing at a record. That is
    the same rule with a different shape: a claim with no resolvable evidence
    does not reach the reader, whether the id was wrong or never given.
    """
    session = Session(RunOptions(repo=DROPS, replay=True))
    session.start()
    session.wait(120)

    assert session.error is None, session.error
    dropped = [e for e in session.log if isinstance(e, events.FindingDropped)]
    assert len(dropped) == 1
    assert dropped[0].field == "onboarding"

    # Whatever it cited, none of it survived into the report.
    surviving = {c.evidence_id for c in session.assessment.claims}
    assert not (set(dropped[0].cited) & surviving)

    # The engine's own arithmetic agrees with the stream.
    assert session.trace.before_verification - session.trace.after_verification == 1

    # Every claim that did reach the reader carries an id.
    assert all(c.evidence_id for c in session.assessment.claims)


def test_a_clean_run_drops_nothing_and_still_reports_resolution():
    session = Session(RunOptions(repo=CLEAN, replay=True))
    session.start()
    session.wait(120)

    assert session.error is None, session.error
    assert not [e for e in session.log if isinstance(e, events.FindingDropped)]
    assert [e for e in session.log if isinstance(e, events.EvidenceResolved)]
    assert session.assessment.verdict.value == "viable"


def test_a_stored_run_keeps_the_records_behind_its_claims():
    """What makes a reopened report checkable, and what keeps it small.

    Every id the report prints gets its record stored with it — read back out
    of the provider the run is still holding, so a live run costs no second
    crawl and the record stored is the one Stage D saw. Nothing else is kept:
    the run read over a thousand records, and the interface can only ever look
    up an id that is on the page.
    """
    session = Session(RunOptions(repo=CLEAN, replay=True))
    session.start()
    session.wait(120)
    assert session.error is None, session.error

    entry = session.to_entry()
    cited = {c.evidence_id for c in session.assessment.claims}
    assert cited, "a report with no ids would make this test vacuous"
    assert {r.evidence_id for r in entry.evidence} == cited

    read = [e for e in session.log if isinstance(e, events.EvidenceLoaded)][0].count
    assert len(entry.evidence) < read

    # Looking those ids up again is not part of the run, and must not appear in
    # its trace as a stage D that resolved everything twice.
    resolutions = len([e for e in session.log if isinstance(e, events.EvidenceResolved)])
    session.to_entry()
    session.drain()
    assert (
        len([e for e in session.log if isinstance(e, events.EvidenceResolved)])
        == resolutions
    )


def test_describe_survives_an_event_it_has_never_seen():
    """Unknown events degrade to a line. Nothing in the UI may raise on one."""

    class Invented:
        __slots__ = ("stage", "detail")

        def __init__(self):
            self.stage, self.detail = "new_stage", "something added later"

    line = events.describe(Invented())
    assert "Invented" in line
    assert "new_stage" in line


def test_verdict_colour_tolerates_a_member_the_tui_has_never_seen():
    from holt.tui import theme

    assert theme.verdict_colour("viable") == theme.VIABLE
    assert theme.verdict_colour("a_verdict_added_later") == theme.VERDICT_FALLBACK
    assert theme.verdict_label("not_viable") == "not viable"


def test_a_live_run_records_outside_the_committed_fixtures():
    """The interface must never append to the evidence the harness replays.

    `OpenAIModel` appends every call to the path it is handed. Pointing it at
    `fixtures/trajectories/` would have a TUI session rewrite the recordings the
    eval harness reproduces its numbers from. This asserts the path chosen for a
    live run lands under the user data directory and nowhere near the fixtures
    — or the current directory, which is somebody's project.
    """
    from holt import model, paths

    opts = RunOptions(repo=CLEAN, replay=False, live=True)
    for kind in ("verdict", "pathfinder"):
        path = opts.recording(CLEAN, kind)
        assert paths.runs_dir() in path.parents
        assert path.is_absolute()
        assert model.TRAJECTORY_DIR not in path.parents
        assert "fixtures" not in path.parts
    # Both halves of one run share a directory, so a session is one artefact.
    assert (
        opts.recording(CLEAN, "verdict").parent
        == opts.recording(CLEAN, "pathfinder").parent
    )


def test_replay_still_reads_the_committed_trajectories():
    """The other half of the same guarantee: replay is unchanged."""
    from holt.tui.session import _client

    opts = RunOptions(repo=CLEAN, replay=True)
    assert _client(CLEAN, opts, "verdict").replayed is True


def test_missing_credentials_asks_only_for_a_github_token(monkeypatch):
    """A model is never required: without one a run is rules-only."""
    from holt import credentials
    from holt.tui.session import missing_credentials

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert missing_credentials(RunOptions(repo=CLEAN, replay=True)) == []
    assert missing_credentials(RunOptions(repo=CLEAN, replay=False, live=False)) == []

    live = missing_credentials(RunOptions(repo=CLEAN, replay=False, live=True))
    assert len(live) == 1 and credentials.TOKEN_URL in live[0]
    assert "OPENAI" not in live[0]

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    assert missing_credentials(RunOptions(repo=CLEAN, replay=False, live=True)) == []


def test_with_no_model_set_up_a_run_is_rules_only(monkeypatch):
    from holt import model
    from holt.tui.session import Session, _client

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model.enable_user_models_config(model.ModelsConfig())
    opts = RunOptions(repo=CLEAN, replay=False, live=False)
    assert opts.rules_only
    assert _client(CLEAN, opts, "verdict") is None

    session = Session(opts)
    session.start()
    session.wait(timeout=60)
    assert session.error is None, session.error
    assert session.assessment is not None
    assert not session.assessment.models  # no model wrote anything


def test_the_interface_honours_the_chosen_provider(monkeypatch, tmp_path):
    from holt import model
    from holt.tui.session import _client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    model.enable_user_models_config(model.ModelsConfig(provider="anthropic"))
    try:
        opts = RunOptions(repo=CLEAN, replay=False, live=False, run_root=tmp_path)
        assert not opts.rules_only
        assert isinstance(_client(CLEAN, opts, "verdict"), model.AnthropicModel)
    finally:
        model.enable_user_models_config(model.ModelsConfig())


def test_env_file_fills_gaps_without_overriding(tmp_path, monkeypatch):
    """`.env` is a convenience, not an authority: an explicit export wins."""
    from holt.tui import env

    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n"
        "\n"
        'export QUOTED="from-file"\n'
        "ALREADY_SET=from-file\n"
        "NOT_SET=from-file\n"
    )
    monkeypatch.setenv("ALREADY_SET", "from-shell")
    monkeypatch.delenv("NOT_SET", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)

    filled = env.load(path)

    assert os.environ["ALREADY_SET"] == "from-shell"
    assert os.environ["NOT_SET"] == "from-file"
    assert os.environ["QUOTED"] == "from-file"
    assert "ALREADY_SET" not in filled
    assert set(filled) == {"NOT_SET", "QUOTED"}


def test_replay_usage_describes_the_recording_not_a_purchase():
    """A replay reports the tokens the *original* run used.

    Those price out to a real number, which is why the live screen refuses to
    render it as spend: nothing was bought. The event still carries the counts,
    because they are true and something else may want them.
    """
    _, _, seen = _run(CLEAN)
    usage = [e for e in seen if isinstance(e, events.UsageUpdated)]
    assert usage, "no usage events were emitted"
    assert usage[-1].input_tokens > 0
    # Monotonic: it is a running total, not a per-call figure.
    assert [u.input_tokens for u in usage] == sorted(u.input_tokens for u in usage)


# ─── the window the run actually applied ────────────────────────────────────


class _StubProvider:
    """A provider with nothing but a cutoff and a window. That is all `fetch`
    reports about, and building a real one would drag the network in."""

    def __init__(self, cutoff, window=Window.PRE_T):
        self.cutoff = cutoff
        self.window = window

    def fetch(self, request, /, **params):
        return []

    def resolve(self, evidence_id):
        return None


def test_the_evidence_event_carries_the_cutoff_the_run_actually_used():
    """Live means now, and the stream has to say which "now" it meant.

    `LiveGitHubProvider` defaults its cutoff to today rather than the
    benchmark's T, because T is an evaluation device. Anything watching the run
    has to be told the real boundary; a watcher that assumed T would report a
    holdout the run never applied.
    """
    from datetime import UTC, datetime

    from holt.types import T_CUTOFF

    today = datetime(2026, 8, 31, tzinfo=UTC)
    seen: list = []
    ObservingProvider(_StubProvider(today), seen.append).fetch("owner/name")
    loaded = [e for e in seen if isinstance(e, events.EvidenceLoaded)]
    assert len(loaded) == 1
    assert loaded[0].cutoff == today

    seen.clear()
    ObservingProvider(_StubProvider(T_CUTOFF), seen.append).fetch("owner/name")
    assert [e.cutoff for e in seen if isinstance(e, events.EvidenceLoaded)] == [T_CUTOFF]


def test_a_replayed_run_reports_the_holdout_boundary():
    """The other side of it: a fixture run really is cut at T."""
    from holt.types import T_CUTOFF

    _, _, seen = _run(CLEAN)
    loaded = [e for e in seen if isinstance(e, events.EvidenceLoaded)]
    assert loaded, "no evidence event was emitted"
    assert all(e.cutoff == T_CUTOFF for e in loaded)


# ─── stopping a run ─────────────────────────────────────────────────────────


def test_a_stopped_run_is_interrupted_at_its_next_chokepoint():
    """A stop reaches the engine without the engine knowing about stopping.

    Cancelling before the run starts means the very first evidence read raises,
    which makes the test deterministic. What it pins is the mechanism: the run
    ends, it ends as cancelled rather than failed, and nothing partial survives.
    """
    session = Session(RunOptions(repo=CLEAN, replay=True))
    session.cancel()
    session.start()
    session.wait(60)

    assert session.cancelled
    assert session.error is None, "a deliberate stop must not report as a failure"
    assert session.assessment is None
    assert session.to_entry() is None, "a stopped run must not be stored"
    assert [e for e in session.log if isinstance(e, events.RunCancelled)]
    assert not [e for e in session.log if isinstance(e, events.RunFailed)]


def test_stopping_part_way_keeps_no_report_and_names_what_finished():
    """Stop after the first stage: the run ends, and says what it got through."""
    session = Session(RunOptions(repo=CLEAN, replay=True))
    stop_after = "classify"

    original = session._emit

    def emit(event):
        original(event)
        if isinstance(event, events.StageFinished) and event.stage == stop_after:
            session.cancel()

    session._emit = emit  # type: ignore[method-assign]
    session.start()
    session.wait(60)

    assert session.cancelled, "the stop never landed"
    assert session.assessment is None
    cancelled = [e for e in session.log if isinstance(e, events.RunCancelled)]
    assert len(cancelled) == 1
    assert stop_after in cancelled[0].completed_stages


def test_the_wrappers_raise_on_a_stop_without_reporting_a_failure():
    """The stop is checked before the call, not around it.

    Raising inside `complete`'s own try would emit `RunFailed` on the way out,
    which would have the interface report a stop the reader asked for as a
    defect in the run.
    """
    from holt.tui.observe import RunCancelled

    seen: list = []

    class _Boom:
        def complete(self, **kwargs):
            raise AssertionError("a stopped run must not call the model")

        def fetch(self, request, /, **params):
            raise AssertionError("a stopped run must not read evidence")

        def resolve(self, evidence_id):
            raise AssertionError("a stopped run must not resolve evidence")

    model = ObservingModel(_Boom(), seen.append, CLEAN, lambda: True)
    with pytest.raises(RunCancelled):
        model.complete(label="classify", system="", prompt="", schema={})

    provider = ObservingProvider(_Boom(), seen.append, lambda: True)
    with pytest.raises(RunCancelled):
        provider.fetch(CLEAN)

    assert not [e for e in seen if isinstance(e, events.RunFailed)]
    assert not [e for e in seen if isinstance(e, events.StageStarted)]


def test_a_run_nobody_stopped_is_not_affected_by_the_check():
    """The default is no cancellation, and the wrappers stay pure delegates."""
    _, _, seen = _run(CLEAN)
    assert not [e for e in seen if isinstance(e, events.RunCancelled)]
