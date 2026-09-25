"""A pull request opened an hour ago has not been ignored.

Live runs judge silence only on attempts at least `MIN_AGE_HOURS` old. The
committed fixtures are a frozen benchmark and keep the old arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from holt.agent import pipeline
from holt.agent.signals import MIN_AGE_HOURS, build_threads, compute
from holt.agent.verdict import classify, rule_codes
from holt.agent.findings import Findings
from holt.evidence.fixtures import FixtureProvider
from holt.evidence.provider import EvidenceProvider
from holt.report import Verdict
from holt.types import EvidenceRecord, Window

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def rec(eid: str, hours_ago: float, author: str) -> EvidenceRecord:
    return EvidenceRecord(
        eid, "github", "https://github.com/a/b/pull/1",
        NOW - timedelta(hours=hours_ago), {"author": author, "author_is_bot": False},
    )


class LiveLikeProvider(EvidenceProvider):
    """Serves fixed records the way a live provider would: recency applies."""

    def __init__(self, records: list[EvidenceRecord]) -> None:
        super().__init__(Window.PRE_T, NOW)
        self._records = records

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        return self._records

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return next((r for r in self._records if r.evidence_id == evidence_id), None)


def silent_attempts(n: int, hours_ago: float, start: int = 1) -> list[EvidenceRecord]:
    return [rec(f"pr:a/b#{i}:opened", hours_ago, f"user{i}") for i in range(start, start + n)]


def test_a_fresh_unanswered_pull_request_is_awaiting_not_ignored():
    threads = build_threads(silent_attempts(1, hours_ago=3) + silent_attempts(1, 200, start=2))
    s = compute(threads, as_of=NOW)
    assert s.outsider_threads == 2
    assert s.outsider_ignored == 1
    assert s.outsider_awaiting_reply == 1
    assert s.outsider_judgeable == 1


def test_the_boundary_is_min_age_hours():
    just_under = silent_attempts(1, MIN_AGE_HOURS - 0.1)
    just_over = silent_attempts(1, MIN_AGE_HOURS + 0.1, start=2)
    s = compute(build_threads(just_under + just_over), as_of=NOW)
    assert (s.outsider_awaiting_reply, s.outsider_ignored) == (1, 1)


def test_no_reference_time_keeps_the_old_arithmetic():
    s = compute(build_threads(silent_attempts(3, hours_ago=1)))
    assert s.outsider_ignored == 3 and s.outsider_awaiting_reply == 0


def test_a_fresh_pull_request_that_got_a_reply_is_not_awaiting():
    records = silent_attempts(1, hours_ago=5) + [rec("pr:a/b#1:comment:0", 4, "maintainer")]
    s = compute(build_threads(records), as_of=NOW)
    assert s.outsider_awaiting_reply == 0 and s.outsider_ignored == 0
    assert s.outsider_answered == 1


def test_a_burst_of_new_pull_requests_does_not_make_a_repo_look_hostile():
    """The bug: a busy repo read at any moment looked hostile, because its
    newest pull requests had no reply *yet*."""
    records = silent_attempts(10, hours_ago=2)
    fresh = compute(build_threads(records), as_of=NOW)
    verdict, trace = classify(Findings(), fresh)
    assert verdict is not Verdict.NOT_VIABLE
    assert "awaiting_reply" in rule_codes(trace)
    # The same records with no age guard are exactly the old false accusation.
    legacy = compute(build_threads(records))
    assert classify(Findings(), legacy)[0] is Verdict.NOT_VIABLE


def test_a_live_run_does_not_count_a_fresh_pull_request_as_ignored():
    records = silent_attempts(9, hours_ago=400) + silent_attempts(1, hours_ago=2, start=50)
    provider = LiveLikeProvider(records)
    _, trace = pipeline.analyze_without_model("a/b", provider, as_of=NOW)
    assert trace.signals.outsider_ignored == 9
    assert trace.signals.outsider_awaiting_reply == 1


def test_a_live_run_with_no_as_of_measures_from_now():
    records = [
        EvidenceRecord("pr:a/b#1:opened", "github", "https://x",
                       datetime.now(UTC) - timedelta(hours=1),
                       {"author": "new", "author_is_bot": False}),
    ]
    provider = LiveLikeProvider(records)
    provider.cutoff = datetime.now(UTC) + timedelta(minutes=1)
    _, trace = pipeline.analyze_without_model("a/b", provider)
    assert trace.signals.outsider_awaiting_reply == 1
    assert trace.signals.outsider_ignored == 0


def test_the_guard_can_be_switched_off_explicitly():
    provider = LiveLikeProvider(silent_attempts(2, hours_ago=1))
    _, trace = pipeline.analyze_without_model("a/b", provider, as_of=NOW, min_age_hours=0)
    assert trace.signals.outsider_ignored == 2


def test_the_frozen_benchmark_is_unchanged():
    """Fixtures were scored without the guard; applying it would move 44 of 74."""
    provider = FixtureProvider(Window.PRE_T)
    assert provider.judges_recency is False
    records = provider.fetch("NixOS/nixpkgs")
    expected = compute(build_threads(records))
    _, trace = pipeline.analyze_without_model(
        "NixOS/nixpkgs", FixtureProvider(Window.PRE_T), as_of=provider.cutoff
    )
    assert trace.signals.outsider_ignored == expected.outsider_ignored
    assert trace.signals.outsider_awaiting_reply == 0


def test_unanswered_attempts_are_reported_next_to_the_median():
    records = (
        silent_attempts(3, hours_ago=300)
        + [rec("pr:a/b#10:opened", 300, "u10"), rec("pr:a/b#10:comment:0", 299, "m")]
    )
    s = compute(build_threads(records), as_of=NOW)
    assert s.median_first_response_hours == 1.0
    assert s.outsider_answered == 1
    assert s.outsider_ignored == 3
    d = s.as_dict()
    assert d["outsider_answered"] == 1 and d["outsider_awaiting_reply"] == 0
