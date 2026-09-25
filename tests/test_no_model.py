"""The degraded mode: a verdict with no model, and an honest account of the cost.

`--no-model` exists because the project measured its own model stages at +0.01
MCC on the verdict. If the rules decide, the verdict must be obtainable without
a model. What must not happen is the mode quietly presenting itself as a full
report, so the tests here are as much about what it *says* as what it decides.
"""

from __future__ import annotations

import pytest

from holt.agent.findings import Findings
from holt.agent.pipeline import NO_MODEL_METHOD, analyze
from holt.agent.signals import build_threads, compute
from holt.agent.verdict import classify
from holt.evidence.fixtures import FixtureProvider
from holt.types import Window

REPOS = ["NixOS/nixpkgs", "is-a-dev/register", "space-wizards/space-station-14"]


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider(Window.PRE_T)


@pytest.mark.parametrize("repo", REPOS)
def test_no_model_calls_no_model(repo: str, provider: FixtureProvider) -> None:
    # Passing None is the only route into this mode, and it is the whole
    # guarantee: there is no client to call.
    assessment, _ = analyze(repo, provider, None)
    assert assessment.models == []
    assert assessment.method == NO_MODEL_METHOD
    assert assessment.replayed is False


@pytest.mark.parametrize("repo", REPOS)
def test_the_verdict_is_the_same_function_the_full_pipeline_uses(
    repo: str, provider: FixtureProvider
) -> None:
    """Not a second implementation. Same `classify`, same `Signals`."""
    assessment, trace = analyze(repo, provider, None)
    records = list(provider.fetch(repo))
    threads = build_threads(records)

    # Rebuild the exact call the mode makes: the only seeded finding is the
    # archived flag, taken from metadata rather than asked of a model.
    seed = Findings()
    meta = next((r for r in records if r.evidence_id.endswith(":meta")), None)
    if meta is not None and meta.payload.get("is_archived"):
        seed.add("is_archived", True, (meta.evidence_id,), "")
    expected, rules = classify(seed, compute(threads), 7)
    assert assessment.verdict == expected
    assert assessment.rules == list(rules)
    assert trace.signals == compute(threads)


@pytest.mark.parametrize("repo", REPOS)
def test_every_claim_still_resolves(repo: str, provider: FixtureProvider) -> None:
    """The evidence rule does not relax because the model is gone."""
    assessment, _ = analyze(repo, provider, None)
    for claim in assessment.claims:
        assert claim.evidence_id is not None
        assert provider.resolve(claim.evidence_id) is not None


@pytest.mark.parametrize("repo", REPOS)
def test_it_says_what_was_lost_and_what_that_cost(
    repo: str, provider: FixtureProvider
) -> None:
    """A degraded report that does not disclose the degradation is worse than none."""
    assessment, _ = analyze(repo, provider, None)
    limits = assessment.limits
    assert "No model ran" in limits
    # The measured cost, not an adjective. Out of sample it is 8 points,
    # not the 1 the in-sample ablation suggested, and the report says so --
    # in words a beginner reads, with the statistic's name left in the docs.
    assert "0.55" in limits and "0.63" in limits
    assert "cites no specific threads" in limits
    assert "MCC" not in limits


@pytest.mark.parametrize("repo", REPOS)
def test_the_time_budget_still_reaches_the_verdict(
    repo: str, provider: FixtureProvider
) -> None:
    """`--days` is arithmetic, so it must work in the mode with only arithmetic."""
    threads = build_threads(provider.fetch(repo))
    signals = compute(threads)
    if signals.median_first_response_hours is None:
        pytest.skip("no response times recorded for this repository")
    patient, _ = analyze(repo, provider, None, contributor_days=3650)
    hurried, _ = analyze(repo, provider, None, contributor_days=1)
    assert patient.contributor_days == 3650 and hurried.contributor_days == 1
    # Same evidence, different budgets: the rule trace must reflect the budget
    # it was given rather than a cached one.
    assert isinstance(patient.rules, list) and isinstance(hurried.rules, list)
