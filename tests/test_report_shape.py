"""The report is a deliverable, so its shape is tested like one.

Everything here is about what a reader sees. The failures being guarded against
are the ones that make generated output look generated: a quotation mark with
nothing inside it, a sentence that stops mid-word, a heading over an empty
section, and a verdict word printed without saying what it means for the reader.
"""

from __future__ import annotations

import pytest

from holt.agent.pipeline import MAX_CLAIM_CHARS, clip
from holt.report import Assessment, Claim, Verdict


def build(**kw) -> str:
    base = dict(repo="a/b", verdict=Verdict.VIABLE, summary="Prose.")
    return Assessment(**{**base, **kw}).render()


@pytest.mark.parametrize(
    "verdict,expected",
    [(Verdict.VIABLE, "Worth your time"),
     (Verdict.NOT_VIABLE, "Not worth your time"),
     (Verdict.INSUFFICIENT_EVIDENCE, "Not enough evidence to say")],
)
def test_the_headline_says_what_the_verdict_means_for_the_reader(verdict, expected):
    assert expected in build(verdict=verdict)


def test_the_time_budget_is_stated_because_the_answer_depends_on_it():
    assert "with 3 days" in build(contributor_days=3)
    assert "with 1 day." in build(contributor_days=1)


def test_empty_sections_do_not_get_headings():
    out = build(bottom_line="", limits="", rules=[], claims=[])
    for heading in ("What decided it", "What could not be determined", "Evidence"):
        assert heading not in out


def test_the_deciding_rule_is_shown_not_described():
    """A chat answer cannot be asked which rule fired. This one can."""
    out = build(rules=["rubber_stamp: reviewed_share 0.04 < 0.20"])
    assert "## What decided it" in out
    assert "reviewed_share 0.04 < 0.20" in out


def test_clip_never_cuts_mid_word():
    text = "The maintainer asked for a smaller diff before they would look at it again"
    out = clip(text, 40)
    assert out.endswith("…")
    assert text.startswith(out[:-1])
    assert out[-2] != " "
    # what survives is whole words
    assert all(w in text.split() for w in out[:-1].split())


def test_clip_leaves_short_text_untouched():
    assert clip("  already   short ", 100) == "already short"


def test_a_long_note_is_clipped_before_it_reaches_the_reader():
    note = "word " * 200
    assert len(clip(note, MAX_CLAIM_CHARS)) <= MAX_CLAIM_CHARS + 1


def test_a_claim_keeps_its_evidence_id_next_to_it():
    out = build(claims=[Claim("merged after review", "pr:a/b#1:opened")])
    assert "- merged after review — [pull request #1](https://github.com/a/b/pull/1)" in out


@pytest.mark.parametrize(
    "evidence_id,url",
    [("pr:NixOS/nixpkgs#526518:opened", "https://github.com/NixOS/nixpkgs/pull/526518"),
     ("issue:a/b#45:closed", "https://github.com/a/b/issues/45"),
     ("pr:a/b#7:comment:3", "https://github.com/a/b/pull/7"),
     ("repo:a/b:meta", "https://github.com/a/b"),
     ("nonsense", "")],
)
def test_evidence_ids_become_github_links(evidence_id, url):
    from holt.report import evidence_url

    assert evidence_url(evidence_id) == url


def test_json_carries_the_headline_and_clickable_evidence():
    from holt.report import Assessment

    data = Assessment(
        repo="a/b", verdict=Verdict.NOT_VIABLE, summary="",
        claims=[Claim("ignored", "pr:a/b#2:opened")],
    ).to_dict()
    assert data["headline"] == "Not worth your time"
    assert data["mode"] == "rules"
    assert data["evidence"][0]["url"] == "https://github.com/a/b/pull/2"


def test_a_report_whose_every_claim_was_dropped_says_so_before_the_prose():
    """The `psf/requests` failure: 0 claims, and prose quoting statistics.

    Stage D had done its job -- every citation was unresolvable and every claim
    was removed -- and the page said nothing about it. A reader cannot tell that
    from a repository there was simply little to say about.
    """
    out = build(dropped_claims=14, bottom_line="You would be fine here.")
    assert "No claim in this report survived verification" in out
    assert "All 14 were dropped" in out
    # Above the prose, not below it.
    assert out.index("survived verification") < out.index("You would be fine here.")
    # The deterministic half is not disowned along with the prose.
    assert "computed without a model and still stand" in out


def test_the_warning_is_only_for_a_report_that_lost_everything():
    assert "survived verification" not in build()
    assert "survived verification" not in build(
        claims=[Claim("merged after review", "pr:a/b#1:opened")], dropped_claims=3
    )


def test_the_report_names_the_model_that_wrote_it():
    """A screenshot has to be able to answer "which model said this?".

    The prose, the classification and the limits degrade with the model behind
    them; the counts and the verdict do not. A report that does not name its
    model leaves a reader unable to tell one half from the other.
    """
    out = build(models=["llama3.2:latest"])
    assert "Model output from llama3.2:latest." in out
    # And nothing is claimed when nothing answered.
    assert "Model output from" not in build()


def test_the_day_budget_never_reaches_the_narration_prompt():
    """`--days` must cost zero model calls, so it cannot change a prompt.

    When the budget was in the prompt, every value other than the default was a
    replay miss, and the claim that re-answering the question is free was false
    without anything failing loudly enough to notice.
    """
    import inspect

    from holt.agent import stages

    source = inspect.getsource(stages.narrate)
    assert "contributor_days" not in source
    assert "contributor_days" not in stages.NARRATE_SYSTEM


def test_a_live_run_defaults_to_today_not_the_benchmark_cutoff():
    """T is an evaluation device and must not bound a user's question.

    Cutting a live run at 2026-06-01 discarded every month since, badly enough
    that an active repository reported "no outsider activity" and read as dead.
    """
    import argparse
    from datetime import UTC, datetime

    from holt.cli import as_of_from
    from holt.types import T_CUTOFF

    live = as_of_from(argparse.Namespace(live=True, as_of=None))
    assert live > T_CUTOFF
    assert (datetime.now(UTC) - live).total_seconds() < 60

    # Fixtures answer as of T, because that is what they contain.
    assert as_of_from(argparse.Namespace(live=False, as_of=None)) == T_CUTOFF
    # And the benchmark's view stays reproducible on demand.
    assert as_of_from(argparse.Namespace(live=True, as_of="2026-06-01")) == T_CUTOFF
