"""The verdict is deterministic, so it can be tested exhaustively rather than sampled."""

from __future__ import annotations

from holt.agent.findings import Findings
from holt.agent.signals import Signals
from holt.agent.verdict import classify, contested_kind, rule_codes
from holt.report import Verdict


def signals(**over) -> Signals:
    base = dict(
        total_threads=20,
        outsider_threads=10,
        outsider_merged=4,
        outsider_ignored=1,
        median_first_response_hours=12.0,
        bot_share=0.1,
        distinct_outsider_authors=4,
        distinct_merged_authors=4,
        reviewed_share=0.5,
        merge_rate=0.4,
    )
    base.update(over)
    return Signals(**base)


def findings(**fields) -> Findings:
    f = Findings()
    for k, v in fields.items():
        f.add(k, v, evidence_ids=("repo:a/b:readme",))
    return f


def test_a_healthy_repo_is_viable():
    v, trace = classify(findings(repo_kind="real_software"), signals())
    assert v is Verdict.VIABLE and trace


def test_registries_are_not_viable_however_active():
    """The whole point: high merge volume must not rescue a registry."""
    v, trace = classify(
        findings(repo_kind="registry"),
        signals(outsider_merged=400, distinct_outsider_authors=150),
    )
    assert v is Verdict.NOT_VIABLE
    assert trace[0].code == "non_software_kind"
    assert "software" in trace[0]


def test_archived_beats_every_other_signal():
    v, _ = classify(findings(repo_kind="real_software", is_archived=True), signals())
    assert v is Verdict.NOT_VIABLE


def test_mirrors_are_not_viable():
    assert classify(findings(repo_kind="mirror"), signals())[0] is Verdict.NOT_VIABLE


def test_no_attempts_is_insufficient_not_hostile():
    v, trace = classify(findings(repo_kind="real_software"), signals(outsider_threads=0))
    assert v is Verdict.INSUFFICIENT_EVIDENCE
    assert "nothing to judge" in trace[0] and trace[0].code == "no_attempts"


def test_ignored_attempts_with_no_merges_is_not_viable():
    v, _ = classify(
        findings(repo_kind="real_software"),
        signals(outsider_threads=10, outsider_merged=0, outsider_ignored=9),
    )
    assert v is Verdict.NOT_VIABLE


def test_one_person_merging_repeatedly_is_not_a_pattern():
    v, _ = classify(
        findings(repo_kind="real_software"),
        signals(outsider_merged=5, distinct_outsider_authors=1),
    )
    assert v is Verdict.INSUFFICIENT_EVIDENCE


def test_a_response_slower_than_a_week_blocks_viable():
    v, trace = classify(
        findings(repo_kind="real_software"), signals(median_first_response_hours=400.0)
    )
    assert v is Verdict.INSUFFICIENT_EVIDENCE
    assert "slow" in rule_codes(trace)


def test_classify_is_pure():
    """Same inputs, same answer -- the property the reproduction claim rests on."""
    f, s = findings(repo_kind="real_software"), signals()
    assert classify(f, s) == classify(f, s)


def test_a_handful_of_ignored_attempts_is_not_proof_of_hostility():
    """Four ignored pull requests out of four is four data points, not a policy."""
    v, trace = classify(
        findings(repo_kind="real_software"),
        signals(outsider_threads=4, outsider_merged=0, outsider_ignored=4,
                median_first_response_hours=None, distinct_outsider_authors=3),
    )
    assert v is Verdict.INSUFFICIENT_EVIDENCE
    assert "too_few_attempts" in rule_codes(trace)


def test_many_ignored_attempts_still_reads_as_hostile():
    v, _ = classify(
        findings(repo_kind="real_software"),
        signals(outsider_threads=40, outsider_merged=0, outsider_ignored=36),
    )
    assert v is Verdict.NOT_VIABLE


def test_a_rubber_stamp_is_rejected_even_when_everything_else_looks_healthy():
    """Landing easily and drawing no review is the registry signature."""
    v, trace = classify(
        findings(repo_kind="real_software"),
        signals(reviewed_share=0.09, merge_rate=0.69),
    )
    assert v is Verdict.NOT_VIABLE
    assert "rubber_stamp" in rule_codes(trace)


def test_unreviewed_but_hard_to_land_is_not_a_rubber_stamp():
    """nixpkgs merges without visible review because review happened elsewhere.

    This is the case that killed the first rejection rule, so it has a test.
    """
    v, _ = classify(
        findings(repo_kind="real_software"),
        signals(reviewed_share=0.09, merge_rate=0.15),
    )
    assert v is Verdict.VIABLE


def test_reviewed_and_easy_to_land_is_a_welcoming_project():
    v, _ = classify(
        findings(repo_kind="real_software"),
        signals(reviewed_share=0.80, merge_rate=0.75),
    )
    assert v is Verdict.VIABLE


def test_the_time_budget_changes_what_counts_as_too_slow():
    """A five-day median reply is fine with three months and fatal with three days."""
    s = signals(median_first_response_hours=120.0)
    assert classify(findings(repo_kind="real_software"), s, contributor_days=90)[0] is Verdict.VIABLE
    v, trace = classify(findings(repo_kind="real_software"), s, contributor_days=3)
    assert v is Verdict.INSUFFICIENT_EVIDENCE
    assert any("3 days you have" in t for t in trace)


# ─── contesting the kind ────────────────────────────────────────────────────
#
# `repo_kind` is the only model-derived field that can decide the answer alone,
# and Stage D cannot check it. These hold the rule that checks it against the
# evidence, and — as importantly — the cases it must leave alone.


def test_a_catalogue_claim_survives_evidence_that_looks_like_a_catalogue():
    """`is-a-dev/register`, `plugin-hub`, `homebrew-cask`: one file, one place."""
    f = findings(repo_kind="registry")
    s = signals(merged_with_files=40, merged_files_median=1.0, merged_dirs_median=1.0)
    assert contested_kind(f, s) is None
    assert classify(f, s)[0] is Verdict.NOT_VIABLE


def test_a_registry_of_three_file_manifests_is_still_a_registry():
    """The regression that killed the first version of this rule.

    A `microsoft/winget-pkgs` entry is three YAML manifests — installer, locale,
    version — in one package directory. A median-files threshold called that a
    hallucination on all four of its recordings. Landing in one place is what
    makes a catalogue entry, not weighing little.
    """
    f = findings(repo_kind="registry")
    s = signals(merged_with_files=180, merged_files_median=3.0, merged_dirs_median=1.0)
    assert contested_kind(f, s) is None


def test_a_catalogue_claim_over_work_that_spans_the_tree_is_contested():
    f = findings(repo_kind="registry")
    s = signals(merged_with_files=66, merged_files_median=9.5, merged_dirs_median=3.0)
    reason = contested_kind(f, s)
    assert reason and "set aside" in reason and reason.code == "kind_contested"


def test_a_contested_kind_decides_nothing_and_the_arithmetic_decides_instead():
    f = findings(repo_kind="registry")
    s = signals(merged_with_files=66, merged_dirs_median=3.0)
    f.drop("repo_kind")  # what the pipeline does with a contested field
    verdict, trace = classify(f, s)
    assert verdict is Verdict.VIABLE
    assert not any("repo_kind" in line for line in trace)


def test_too_few_merges_to_have_a_shape_contests_nothing():
    """Four merged pull requests is not a description of what a merge is here."""
    f = findings(repo_kind="registry")
    assert contested_kind(f, signals(merged_with_files=4, merged_dirs_median=4.0)) is None


def test_a_portfolio_is_not_contested_by_the_shape_of_its_diffs():
    """Its reason is whose project it is. A portfolio being real code is not a
    contradiction, and treating it as one would gut the rule."""
    f = findings(repo_kind="portfolio")
    s = signals(merged_with_files=22, merged_files_median=8.0, merged_dirs_median=3.0)
    assert contested_kind(f, s) is None
    assert classify(f, s)[0] is Verdict.NOT_VIABLE


def test_a_mirror_that_merges_outsiders_is_contested():
    """`pytorch/pytorch` called a mirror of `pytorch/pytorch`. GitHub says it is
    not a mirror, and outsiders' pull requests merge."""
    f = findings(repo_kind="mirror")
    s = signals(outsider_merged=15, distinct_merged_authors=15)
    reason = contested_kind(f, s, {"is_mirror": False})
    assert reason and "doesn't mark it as a mirror" in reason


def test_a_real_mirror_keeps_its_verdict():
    """Metadata alone must not decide it: GitHub sets `is_mirror` only for
    repositories created as mirrors, so a genuine mirror reports false. With no
    merges there is nothing disproving the claim, and the rule stands."""
    f = findings(repo_kind="mirror")
    s = signals(outsider_merged=0, distinct_merged_authors=0)
    assert contested_kind(f, s, {"is_mirror": False}) is None
    assert classify(f, s)[0] is Verdict.NOT_VIABLE
    # And a repository GitHub *does* call a mirror is never contested.
    assert contested_kind(
        f, signals(outsider_merged=15, distinct_merged_authors=15), {"is_mirror": True}
    ) is None
