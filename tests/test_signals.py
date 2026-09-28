"""Signals are arithmetic, so they are tested as arithmetic."""

from __future__ import annotations

from datetime import timedelta

import pytest

from holt.agent import people
from holt.agent.signals import build_threads, compute, first_timer_threads, outsider_threads
from holt.evidence.fixtures import FixtureProvider, fixture_root
from holt.types import T_CUTOFF, EvidenceRecord, Window

T0 = T_CUTOFF - timedelta(days=30)


def rec(eid, offset_h, author, extra=None):
    payload = {"author": author, "author_is_bot": False}
    payload.update(extra or {})
    return EvidenceRecord(eid, "github", "https://x", T0 + timedelta(hours=offset_h), payload)


def test_merge_authors_are_counted_separately_from_attempters():
    """Conflating them printed "15 merges from 72 people" in a user-visible report."""
    threads = build_threads([
        rec("pr:a/b#1:opened", 0, "sam"),
        rec("pr:a/b#1:merged", 2, "sam"),
        rec("pr:a/b#2:opened", 4, "kim"),
        rec("pr:a/b#3:opened", 6, "lee"),
    ])
    s = compute(threads)
    assert s.distinct_outsider_authors == 3
    assert s.distinct_merged_authors == 1


def test_a_second_contribution_is_not_a_first_one():
    """The bug this replaced: defining outsider as 'has not merged' makes
    outsider-merge counts zero by construction."""
    threads = build_threads([
        rec("pr:a/b#1:opened", 0, "sam"),
        rec("pr:a/b#1:merged", 2, "sam"),
        rec("pr:a/b#2:opened", 10, "sam"),
        rec("pr:a/b#2:merged", 12, "sam"),
    ])
    firsts = {t.key for t in outsider_threads(threads)}
    assert firsts == {"pr:a/b#1"}, "only the first landing counts as a newcomer landing"
    assert compute(threads).outsider_merged == 1


def test_reviewed_share_and_merge_rate_are_computed_over_every_merge():
    threads = build_threads([
        rec("pr:a/b#1:opened", 0, "sam"), rec("pr:a/b#1:merged", 2, "sam"),
        rec("pr:a/b#1:comment:0", 1, "maintainer"),
        rec("pr:a/b#2:opened", 4, "kim"), rec("pr:a/b#2:merged", 5, "kim"),
        rec("pr:a/b#3:opened", 6, "lee"),
    ])
    s = compute(threads)
    assert s.reviewed_share == 0.5      # one of two merges drew a reply
    assert round(s.merge_rate, 2) == 0.67  # two of three attempts landed


def test_bots_are_never_newcomers():
    threads = build_threads([
        EvidenceRecord("pr:a/b#1:opened", "github", "https://x", T0,
                       {"author": "dependabot[bot]", "author_is_bot": True}),
    ])
    assert outsider_threads(threads) == []
    assert compute(threads).bot_share == 1.0


def test_first_response_ignores_the_author_talking_to_themselves():
    threads = build_threads([
        rec("pr:a/b#1:opened", 0, "sam"),
        rec("pr:a/b#1:comment:0", 1, "sam"),
        rec("pr:a/b#1:comment:1", 5, "maintainer"),
    ])
    assert threads["pr:a/b#1"].first_response_hours == 5.0
    assert threads["pr:a/b#1"].engaged


def test_a_thread_nobody_answered_counts_as_ignored():
    threads = build_threads([rec("pr:a/b#1:opened", 0, "sam")])
    s = compute(threads)
    assert s.outsider_ignored == 1 and s.median_first_response_hours is None


def test_merged_threads_are_not_ignored_even_without_comments():
    threads = build_threads([rec("pr:a/b#1:opened", 0, "sam"), rec("pr:a/b#1:merged", 1, "sam")])
    assert compute(threads).outsider_ignored == 0


# --- who is an outsider (ticket 03) ------------------------------------------


def opened(n, offset_h, author, association=None, labels=None):
    extra = {}
    if association is not None:
        extra["author_association"] = association
    if labels is not None:
        extra["labels"] = labels
    return rec(f"pr:a/b#{n}:opened", offset_h, author, extra)


def merged(n, offset_h, author, by=None, association=None):
    extra = {} if association is None else {"author_association": association}
    if by is not None:
        extra.update(merged_by=by, merged_by_is_bot=False)
    return rec(f"pr:a/b#{n}:merged", offset_h, author, extra)


def keys(threads_list):
    return {t.key for t in threads_list}


def test_members_are_never_outsiders_however_new():
    threads = build_threads([
        opened(1, 0, "owner", "OWNER"), opened(2, 1, "staff", "MEMBER"),
        opened(3, 2, "helper", "COLLABORATOR"), opened(4, 3, "sam", "NONE"),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#4"}
    assert compute(threads).outsider_threads == 1


def test_a_returning_outsider_still_counts_as_one():
    # The old rule dropped sam's second pull request once the first landed.
    threads = build_threads([
        opened(1, 0, "sam", "CONTRIBUTOR"), merged(1, 2, "sam", association="CONTRIBUTOR"),
        opened(2, 10, "sam", "CONTRIBUTOR"), merged(2, 12, "sam", association="CONTRIBUTOR"),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#1", "pr:a/b#2"}
    s = compute(threads)
    assert (s.outsider_threads, s.outsider_merged, s.distinct_merged_authors) == (2, 2, 1)


def test_without_association_the_old_rule_still_applies():
    # A capture from before the field existed replays as it was computed.
    threads = build_threads([
        opened(1, 0, "sam"), merged(1, 2, "sam"),
        opened(2, 10, "sam"), merged(2, 12, "sam"),
        opened(3, 11, "kim", "MEMBER"),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#1"}


def test_someone_who_merges_others_work_is_staff_whatever_github_says():
    threads = build_threads([
        opened(1, 0, "dev", "CONTRIBUTOR"),
        opened(2, 1, "sam", "NONE"), merged(2, 3, "sam", by="dev"),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#2"}


def test_closing_someone_elses_pull_request_is_staff_too_but_closing_your_own_is_not():
    threads = build_threads([
        opened(1, 0, "dev", "CONTRIBUTOR"),
        opened(2, 1, "sam", "NONE"),
        rec("pr:a/b#2:closed", 3, "sam", {"closed_by": "dev", "closed_by_is_bot": False}),
        opened(3, 2, "kim", "NONE"),
        rec("pr:a/b#3:closed", 4, "kim", {"closed_by": "kim", "closed_by_is_bot": False}),
        opened(4, 3, "lee", "NONE"), merged(4, 5, "lee", by="lee"),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#2", "pr:a/b#3", "pr:a/b#4"}


def test_a_bot_merging_is_not_a_maintainer():
    threads = build_threads([
        opened(1, 0, "sam", "NONE"),
        rec("pr:a/b#1:merged", 2, "sam", {"merged_by": "mergebot-app", "merged_by_is_bot": True}),
    ])
    assert keys(outsider_threads(threads)) == {"pr:a/b#1"}


def _labelled_repo(outside: int, staff: int, label: str = "open source"):
    records = [opened(i, i, f"out{i}", "CONTRIBUTOR", [label, "module: x"])
               for i in range(outside)]
    records += [opened(100 + i, i, f"staff{i}", "CONTRIBUTOR", ["module: x"])
                for i in range(staff)]
    return build_threads(records)


def test_where_a_project_labels_outside_work_the_unlabelled_are_staff():
    # PyTorch: "open source" on every pull request from outside Meta.
    threads = _labelled_repo(outside=12, staff=8)
    assert {t.author for t in outsider_threads(threads)} == {f"out{i}" for i in range(12)}


def test_the_label_is_matched_whatever_its_case_and_by_author():
    records = [opened(i, i, f"out{i}", "NONE", ["Community-Contribution"]) for i in range(10)]
    # out0's second pull request is not labelled yet: still an outsider's.
    records.append(opened(50, 60, "out0", "NONE", []))
    records.append(opened(51, 61, "staff", "CONTRIBUTOR", []))
    outs = outsider_threads(build_threads(records))
    assert "pr:a/b#50" in keys(outs) and "staff" not in {t.author for t in outs}


def test_an_occasional_outside_label_is_not_a_policy():
    # react-native's "Contributor" label: 7 of 156. Nobody becomes staff.
    threads = _labelled_repo(outside=7, staff=149)
    assert len(outsider_threads(threads)) == 156
    # Nor does a majority of a tiny sample.
    assert len(outsider_threads(_labelled_repo(outside=6, staff=1))) == 7


def test_captures_without_labels_are_left_alone():
    threads = build_threads([opened(i, i, f"p{i}", "CONTRIBUTOR") for i in range(20)])
    assert len(outsider_threads(threads)) == 20


# --- people new to this repo -------------------------------------------------


def test_first_timers_are_outsiders_with_nothing_landed_here_yet():
    threads = build_threads([
        # Never landed anything: new, on every attempt.
        opened(1, 0, "ann", "NONE"), opened(2, 5, "ann", "NONE"),
        # Landed something before the sample began: not new.
        opened(3, 0, "bob", "CONTRIBUTOR"),
        # Their first merge is in the sample: new until it landed.
        opened(4, 0, "cat", "CONTRIBUTOR"), opened(5, 2, "cat", "CONTRIBUTOR"),
        merged(5, 3, "cat", association="CONTRIBUTOR"),
        opened(6, 10, "cat", "CONTRIBUTOR"),
        # Maintainers are never first-timers.
        opened(7, 0, "dev", "MEMBER"),
    ])
    firsts = keys(first_timer_threads(threads))
    assert firsts == {"pr:a/b#1", "pr:a/b#2", "pr:a/b#4", "pr:a/b#5"}
    s = compute(threads)
    assert (s.first_timer_threads, s.first_timer_merged) == (4, 1)
    assert (s.distinct_first_timer_authors, s.distinct_first_timer_merged_authors) == (2, 1)
    assert s.outsider_threads == 6


def test_first_timers_are_the_outsiders_when_association_is_missing():
    threads = build_threads([
        opened(1, 0, "sam"), merged(1, 2, "sam"), opened(2, 10, "sam"), opened(3, 1, "kim"),
    ])
    assert keys(first_timer_threads(threads)) == keys(outsider_threads(threads))


# --- the recorded runs replay unchanged --------------------------------------


def _pre_ticket_outsiders(threads):
    """The rule outsiders were counted by before ticket 03, kept verbatim."""
    merged_opens = {}
    for t in threads.values():
        if t.merged and not t.author_is_bot:
            merged_opens.setdefault(t.author, []).append(t.opened_at)
    return [
        t for t in threads.values()
        if not t.author_is_bot
        and not any(earlier < t.opened_at for earlier in merged_opens.get(t.author, []))
    ]


# Split so pytest-xdist can spread the committed fixtures over workers.
SHARDS = 4


@pytest.mark.parametrize("shard", range(SHARDS))
def test_every_committed_fixture_counts_outsiders_exactly_as_before(shard):
    paths = sorted((fixture_root() / Window.PRE_T.value).glob("*.json"))
    assert len(paths) > 50
    provider = FixtureProvider(Window.PRE_T)
    for path in paths[shard::SHARDS]:
        threads = build_threads(provider.fetch(path.stem.replace("__", "/")))
        assert keys(outsider_threads(threads)) == keys(_pre_ticket_outsiders(threads)), path.name


# --- the team, shared with replies (people.maintainers) ----------------------


def review(n, i, offset_h, author, state, association="CONTRIBUTOR"):
    return rec(f"pr:a/b#{n}:review:{i}", offset_h, author,
               {"state": state, "author_association": association, "body": ""})


def test_a_contributor_who_formally_reviews_three_others_prs_is_on_the_team():
    records = [opened(n, n, f"p{n}", "NONE") for n in range(1, 5)]
    records += [review(n, 0, n + 1, "rev", "APPROVED") for n in (1, 2)]
    records.append(review(3, 0, 4, "rev", "CHANGES_REQUESTED"))
    records.append(opened(9, 9, "rev", "CONTRIBUTOR"))
    assert "rev" in people.maintainers(records)
    assert "pr:a/b#9" not in keys(outsider_threads(build_threads(records)))


def test_comments_or_two_reviews_do_not_make_anyone_team():
    records = [opened(n, n, f"p{n}", "NONE") for n in range(1, 5)]
    records += [review(n, 0, n + 1, "chatty", "COMMENTED") for n in (1, 2, 3)]
    records += [rec(f"pr:a/b#{n}:comment:0", n + 1, "chatty",
                    {"author_association": "CONTRIBUTOR", "body": "+1"}) for n in (1, 2, 3)]
    records += [review(n, 1, n + 1, "light", "APPROVED") for n in (1, 2)]
    # Reviewing your own pull request three times is not reviewing others'.
    records += [review(4, i, 5 + i, "p4", "APPROVED") for i in range(3)]
    assert people.maintainers(records) & {"chatty", "light", "p4"} == set()


def test_automation_is_never_on_the_team():
    records = [opened(1, 0, "sam", "NONE"), opened(2, 1, "ci-bot", "MEMBER"),
               rec("pr:a/b#1:merged", 2, "sam",
                   {"merged_by": "pytorchmergebot", "merged_by_is_bot": False})]
    assert people.maintainers(records) == frozenset()
