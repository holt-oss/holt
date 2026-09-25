""""What decided it" is read by beginners, so it is written for them.

Every rule sentence the verdict can produce is generated here from a sweep of
signals and kinds, and checked for internal vocabulary.
"""

from __future__ import annotations

import itertools
import re

import pytest

from holt.agent import pipeline
from holt.agent.findings import Findings
from holt.agent.signals import Signals
from holt.agent.verdict import (
    Rule,
    classify,
    contested_kind,
    headline,
    hours_phrase,
    legacy_trace,
    rule_codes,
)
from holt.evidence.fixtures import FixtureProvider
from holt.report import Verdict
from holt.types import Window

JARGON = re.compile(
    r"repo_kind|=|rubber.?stamp|period read|waved through|unread|outsider|"
    r"not_viable|insufficient_evidence|registry|awesome_list|course_material|"
    r"\bmedian\b|\bMCC\b|p-value|\d+h\b|/\d",
    re.IGNORECASE,
)


def signals(**over) -> Signals:
    base = dict(
        total_threads=20, outsider_threads=10, outsider_merged=4, outsider_ignored=1,
        median_first_response_hours=12.0, bot_share=0.1, distinct_outsider_authors=4,
        distinct_merged_authors=4, reviewed_share=0.5, merge_rate=0.4,
        merged_with_files=10, merged_dirs_median=1.0, outsider_answered=6,
    )
    base.update(over)
    return Signals(**base)


def findings(**fields) -> Findings:
    f = Findings()
    for k, v in fields.items():
        f.add(k, v, evidence_ids=("repo:a/b:readme",))
    return f


def every_trace():
    kinds = [None, "real_software", "registry", "awesome_list", "portfolio",
             "course_material", "mirror"]
    shapes = [
        {},
        {"outsider_threads": 0, "outsider_merged": 0, "outsider_ignored": 0},
        {"outsider_merged": 0, "outsider_ignored": 9},
        {"outsider_merged": 0, "outsider_ignored": 4, "outsider_threads": 5},
        {"outsider_merged": 1},
        {"median_first_response_hours": 400.0},
        {"median_first_response_hours": 0.4},
        {"reviewed_share": 0.1, "merge_rate": 0.9},
        {"outsider_awaiting_reply": 3},
        {"outsider_awaiting_reply": 1, "outsider_ignored": 0},
    ]
    for kind, shape, days in itertools.product(kinds, shapes, (1, 7)):
        f = findings(repo_kind=kind) if kind else Findings()
        yield classify(f, signals(**shape), contributor_days=days)[1]
    yield classify(findings(is_archived=True), signals())[1]
    yield [contested_kind(findings(repo_kind="registry"),
                          signals(merged_dirs_median=4.0))]
    yield [contested_kind(findings(repo_kind="mirror"), signals(), {"is_mirror": False})]
    uncited = Findings()
    uncited.add("repo_kind", "portfolio")
    yield classify(uncited, signals())[1]


def test_every_rule_sentence_reads_as_plain_english():
    seen = set()
    for trace in every_trace():
        for line in trace:
            assert isinstance(line, Rule), line
            assert line.code
            assert not JARGON.search(line), f"jargon in: {line}"
            assert line[0].isupper() or line[0].isdigit(), line
            assert line.rstrip().endswith("."), line
            seen.add(line.code)
    # The sweep reached every rule the verdict has.
    assert seen >= {
        "archived", "closed_kind", "non_software_kind", "kind_uncited", "no_attempts",
        "ignored", "merges", "rubber_stamp", "slow", "too_few_attempts", "few_merges",
        "awaiting_reply", "kind_contested",
    }


def test_rules_are_still_plain_strings():
    _, trace = classify(findings(repo_kind="real_software"), signals())
    assert all(isinstance(line, str) for line in trace)
    assert " ".join(trace)


def test_the_narrator_gets_the_recorded_wording():
    """The narration prompt quotes the trace; its recordings used the old words."""
    _, trace = classify(findings(repo_kind="registry"), signals())
    assert legacy_trace(trace) == ["repo_kind=registry: merged work here is not a software contribution"]
    assert rule_codes(trace) == ["non_software_kind"]


@pytest.mark.parametrize("verdict, text", [
    (Verdict.VIABLE, "Worth your time"),
    (Verdict.NOT_VIABLE, "Not worth your time"),
    (Verdict.INSUFFICIENT_EVIDENCE, "Not enough evidence"),
    ("viable", "Worth your time"),
])
def test_headline(verdict, text):
    assert headline(verdict) == text


@pytest.mark.parametrize("hours, text", [
    (0.4, "24 minutes"), (0.01, "1 minute"), (1, "1 hour"), (12.5, "12.5 hours"),
    (72, "3.0 days"),
])
def test_hours_read_naturally(hours, text):
    assert hours_phrase(hours) == text


@pytest.mark.parametrize("kind", ["portfolio", "course_material"])
def test_an_uncited_personal_or_course_kind_does_not_decide(kind):
    """Text in a README asking to be called a portfolio must not reject a repo."""
    f = Findings()
    f.add("repo_kind", kind)  # no evidence ids
    verdict, trace = classify(f, signals())
    assert verdict is Verdict.VIABLE
    assert "kind_uncited" in rule_codes(trace)


@pytest.mark.parametrize("kind", ["portfolio", "course_material"])
def test_a_cited_personal_or_course_kind_still_decides(kind):
    verdict, trace = classify(findings(repo_kind=kind), signals())
    assert verdict is Verdict.NOT_VIABLE
    assert rule_codes(trace) == ["non_software_kind"]


def test_the_no_model_report_is_plain_english():
    assessment, _ = pipeline.analyze_without_model("NixOS/nixpkgs", FixtureProvider(Window.PRE_T))
    for text in (assessment.summary, assessment.limits, assessment.bottom_line):
        assert "MCC" not in text and "period read" not in text and "outsider" not in text
    assert assessment.bottom_line.startswith(headline(assessment.verdict))
