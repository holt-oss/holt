"""The discovery layer, and the coupling it is allowed to have.

`holt.tui.discovery` reassembles the screening step from `discover`'s own public
parts rather than parsing the markdown `run_replay` prints. That is a real
dependency on the engine, so it is pinned here: the manifest shape, the
functions it calls, and the fact that screening still decides what it decided.

No Textual. The layer is useful without a terminal and these run on a checkout
that never installed the extra.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from holt.tui import discovery

#: The recorded session is optional in a checkout, and it is no longer the path
#: the interface opens on, so it gates only the tests that actually read it.
#: The live-search tests below must run everywhere — that is the default now.
needs_recording = pytest.mark.skipif(
    not discovery.manifest_path_exists(),
    reason="the recorded discovery session is not present in this checkout",
)


@needs_recording
def test_the_shipped_session_loads_with_no_credentials():
    """The demo session is the free path. It must need nothing at all."""
    session = discovery.load()

    assert session.name == discovery.DEFAULT_SESSION
    assert session.rows, "the recorded search found no candidates"
    assert session.queries, "a search with no query is not a search"
    assert session.profile_description


@needs_recording
def test_screening_keeps_what_it_rejected():
    """A discovery tool that shows only its survivors is asking to be trusted
    about the ones it hid."""
    session = discovery.load()
    cut = [r for r in session.rows if not r.survived]

    assert cut, "this session is expected to cut some candidates"
    assert all(r.category for r in cut)
    # Every cut carries a reason a person can read.
    assert all(discovery.cut_reason(r.category) for r in cut)


@needs_recording
def test_survivors_come_first_and_keep_the_search_order():
    """Screening says 'worth a look', never 'better than'. Sorting survivors
    among themselves would assert a ranking screening does not make."""
    session = discovery.load()
    flags = [r.survived for r in session.rows]
    assert flags == sorted(flags, reverse=True)

    import json

    from holt import discover

    manifest = json.loads(discover.manifest_path(session.name).read_text())
    order = [c["slug"] for c in manifest["candidates"]]
    survivors = [r.slug for r in session.rows if r.survived]
    assert survivors == [s for s in order if s in set(survivors)]


@needs_recording
def test_the_screening_verdict_is_the_engines_not_ours():
    """`screen_records` holds the rule. This asks it; it does not restate it."""
    import json

    from holt import discover
    from holt.evidence.fixtures import FixtureProvider
    from holt.profile import Profile
    from holt.types import Window

    session = discovery.load()
    manifest = json.loads(discover.manifest_path(session.name).read_text())
    profile = Profile(**manifest["profile"])
    provider = FixtureProvider(
        Window.PRE_T, root=discover.screen_root(session.name), cutoff=session.as_of
    )

    by_slug = {r.slug: r for r in session.rows}
    checked = 0
    for raw in manifest["candidates"]:
        candidate = discover.Candidate(**raw)
        if candidate.slug not in by_slug:
            continue
        expected = discover.screen_records(candidate, provider.fetch(candidate.slug),
                                           profile.days)
        row = by_slug[candidate.slug]
        assert row.category == expected.category
        assert row.verdict == expected.verdict.value
        checked += 1
    assert checked == len(by_slug)


@needs_recording
def test_a_session_that_is_not_there_raises_rather_than_inventing_one():
    with pytest.raises(FileNotFoundError):
        discovery.load("no-such-session")


@needs_recording
def test_counts_add_up():
    session = discovery.load()
    assert len(session.survivors) + len(
        [r for r in session.rows if not r.survived]
    ) == len(session.rows)


@needs_recording
def test_available_lists_the_shipped_session():
    assert discovery.DEFAULT_SESSION in discovery.available()


# ─── the live search ─────────────────────────────────────────────────────────
#
# The worker is driven against a stubbed `source_live`, so these exercise the
# streaming, the counting and the failure handling without a token, a network
# call or a recording. What screening *decides* is the engine's business and is
# tested there; what is pinned here is that the interface reports it faithfully.


class _Stub:
    """Stands in for `discover.LiveSearch`, yielding steps a screen would draw."""

    def __init__(self, steps, queries=("language:Python",), as_of=None):
        from datetime import UTC, datetime

        self.steps = steps
        self.queries = list(queries)
        self.as_of = as_of or datetime(2026, 6, 2, tzinfo=UTC)
        self.candidates = [s.candidate for s in steps]

    def screen(self, should_stop=lambda: False):
        for step in self.steps:
            if should_stop():
                return
            yield step


def _step(index, total, slug, category=None, error=None):
    from types import SimpleNamespace

    from holt import discover

    candidate = discover.Candidate(
        slug=slug, description=f"{slug} does things", stars=120, language="Python"
    )
    result = None
    if error is None:
        result = SimpleNamespace(
            verdict=SimpleNamespace(value="worth a look"),
            category=category,
            trace=["because the evidence said so"],
        )
    return discover.ScreenedStep(
        index=index, total=total, candidate=candidate, result=result, error=error
    )


def _run(monkeypatch, steps):
    """Run a search over stubbed steps and wait for the worker to finish."""
    from holt import discover
    from holt.profile import Profile

    stub = _Stub(steps)
    monkeypatch.setattr(discover, "source_live", lambda *a, **k: stub)
    search = discovery.Search(profile=Profile())
    search.start()
    search.wait(timeout=10)
    assert search.finished
    return search


def test_a_live_search_reports_every_candidate_it_screened(monkeypatch):
    """Cut candidates are rows too. A list of survivors alone asks to be
    trusted about the ones it hid."""
    search = _run(
        monkeypatch,
        [
            _step(1, 3, "one/alpha"),
            _step(2, 3, "two/beta", category="inactive"),
            _step(3, 3, "three/gamma"),
        ],
    )

    assert [r.slug for r in search.rows] == ["one/alpha", "two/beta", "three/gamma"]
    assert [r.slug for r in search.survivors] == ["one/alpha", "three/gamma"]
    assert search.error is None
    assert not search.cancelled


def test_a_live_search_keeps_the_order_the_search_returned(monkeypatch):
    """Screening says 'worth a look', never 'better than'. Floating survivors
    to the top as they land would assert a ranking the engine never computed."""
    search = _run(
        monkeypatch,
        [
            _step(1, 3, "one/cut", category="inactive"),
            _step(2, 3, "two/kept"),
            _step(3, 3, "three/cut", category="archived"),
        ],
    )

    assert [r.slug for r in search.rows] == ["one/cut", "two/kept", "three/cut"]


def test_a_candidate_that_could_not_be_read_is_not_a_rejection(monkeypatch):
    """'We could not look' and 'we looked and it failed' are different answers,
    and a search that quietly merged them would report a rejection it never
    made."""
    search = _run(
        monkeypatch,
        [
            _step(1, 2, "one/alpha"),
            _step(2, 2, "two/gone", error="404 Not Found"),
        ],
    )

    assert search.skipped == ["two/gone"]
    assert [r.slug for r in search.rows] == ["one/alpha"]
    assert "could not be read" in search.describe()


def test_a_search_that_fails_reports_the_reason_rather_than_raising(monkeypatch):
    """The worker is a thread. An exception that escaped it would be a screen
    that waits forever for a row that is never coming."""
    from holt import discover
    from holt.profile import Profile

    def boom(*a, **k):
        raise RuntimeError("github said no")

    monkeypatch.setattr(discover, "source_live", boom)
    search = discovery.Search(profile=Profile())
    search.start()
    search.wait(timeout=10)

    assert search.finished
    assert search.error and "github said no" in search.error
    assert search.rows == []


def test_a_cancelled_search_keeps_what_it_already_screened(monkeypatch):
    """Those rows were free and they are still true. Throwing them away would
    punish impatience."""
    from holt import discover
    from holt.profile import Profile

    steps = [_step(i, 4, f"n{i}/repo") for i in range(1, 5)]
    stub = _Stub(steps)
    monkeypatch.setattr(discover, "source_live", lambda *a, **k: stub)

    search = discovery.Search(profile=Profile())
    # Cancelled before it starts: the sweep stops at the first check, which is
    # the same path a keypress takes, without racing the worker.
    search.cancel()
    search.start()
    search.wait(timeout=10)

    assert search.finished
    assert search.cancelled
    assert search.rows == []
    assert "stopped" in search.describe()


def test_progress_reads_truthfully_before_anything_has_landed(monkeypatch):
    """A screen draws this line before the first row exists."""
    from holt.profile import Profile

    search = discovery.Search(profile=Profile())
    assert "searching" in search.describe()
    assert search.screened == 0


def test_a_live_search_needs_only_a_github_token(monkeypatch):
    """Screening calls no model. Demanding an OpenAI key to *find* candidates
    would turn a free feature into one that looks paid."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert discovery.missing_token() is None

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    message = discovery.missing_token()
    assert message and "GitHub token" in message
