"""Refresh tiers: repos people saved or viewed lately are refreshed weekly,
the rest of the seed list monthly (warm.py --tier)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from holt_server import warm
from holt_server.db import RepoMeta, Report, RepoView, SavedRepo

from conftest import canned_report


@pytest.fixture
def th(h, monkeypatch):
    monkeypatch.setattr(warm, "POLL_S", 0.02)

    async def remaining():
        return 5000
    h.svc.lookup.remaining = remaining
    return h


def add(h, *rows):
    async def go():
        async with h.svc.db.session() as s:
            s.add_all(rows)
            await s.commit()
    h.client.portal.call(go)


def viewed(repo, days_ago, user="u1"):
    at = datetime.now(UTC) - timedelta(days=days_ago)
    return RepoView(user_id=user, repo_key=repo.lower(), repo=repo, first_viewed_at=at,
                    last_viewed_at=at, views=1)


def saved(repo, user="u1"):
    return SavedRepo(user_id=user, repo_key=repo.lower(), repo=repo)


def reported(repo, days_ago):
    return Report(repo=repo, repo_key=repo.lower(), mode="rules", days=7,
                  report=canned_report(repo),
                  created_at=datetime.now(UTC) - timedelta(days=days_ago))


def dormant(repo):
    return RepoMeta(repo_key=repo.lower(), repo=repo,
                    pushed_at=datetime.now(UTC) - timedelta(days=200))


def asked_for(h):
    return [c["repo"] for c in h.engine.calls]


SEEDS = ["octo/one", "octo/two", "octo/three", "pallets/flask"]


def tiers(h, seeds=SEEDS):
    return {t: h.client.portal.call(lambda t=t: warm.tier_repos(h.svc, t, seeds))
            for t in warm.TIERS}


def test_saved_or_recently_viewed_repos_are_weekly_the_rest_monthly(th):
    add(th, saved("octo/One"), saved("octo/four"),                 # octo/four: not a seed
        viewed("octo/two", days_ago=10), viewed("octo/two", 40, user="u2"),
        viewed("octo/three", days_ago=40))                          # too long ago
    got = tiers(th)
    assert sorted(got["weekly"]) == ["octo/One", "octo/four", "octo/two"]
    assert sorted(got["monthly"]) == ["octo/three", "pallets/flask"]


def test_nobody_saved_or_viewed_anything(th):
    assert tiers(th) == {"weekly": [], "monthly": SEEDS}


def test_a_tier_pass_runs_only_that_tiers_reports(th):
    add(th, saved("octo/one"))
    result = th.client.portal.call(lambda: warm.warm_once(th.svc, seeds=SEEDS, tier="weekly"))
    assert [c["repo"] for c in th.engine.calls] == ["octo/one"]
    assert (result.reports_run, result.starter_run, result.finds_run, result.meta_run) == (
        1, 0, 0, 0)


def test_a_tier_pass_takes_the_oldest_report_first(th):
    # Never reported first (in seed order), then the oldest report: when the
    # GitHub budget runs out, what's left is what was refreshed most recently.
    th.wait(th.post("/v1/analyses", {"repo": "octo/three"}).json()["job_id"])
    th.wait(th.post("/v1/analyses", {"repo": "octo/one"}).json()["job_id"])
    th.svc.settings.refresh_monthly_hours = 0  # everything is due
    th.engine.calls.clear()
    th.client.portal.call(lambda: warm.warm_once(th.svc, seeds=SEEDS, tier="monthly",
                                                 parallel=1))
    assert [c["repo"] for c in th.engine.calls] == [
        "octo/two", "pallets/flask", "octo/three", "octo/one"]


def test_a_tier_pass_uses_its_tiers_age_never_the_twenty_hour_default(th):
    # Production, 6 Oct 2026: `warm.sh --tier monthly` got no age from
    # anywhere, so it read every report over 20 hours old again.
    add(th, saved("octo/one"), reported("octo/one", days_ago=8),
        saved("octo/two"), reported("octo/two", days_ago=3),
        reported("octo/three", days_ago=3), reported("pallets/flask", days_ago=31))
    lines: list[str] = []
    monthly = th.client.portal.call(lambda: warm.warm_once(
        th.svc, seeds=SEEDS, tier="monthly", say=lines.append))
    assert asked_for(th) == ["pallets/flask"]         # over a month old
    assert (monthly.reports_run, monthly.reports_fresh) == (1, 1)
    assert lines[0] == ("monthly tier: 2 repos; reports older than 720 hours (30 days) "
                        "are read again (HOLT_REFRESH_MONTHLY_HOURS)")

    th.engine.calls.clear()
    lines.clear()
    th.client.portal.call(lambda: warm.warm_once(
        th.svc, seeds=SEEDS, tier="weekly", say=lines.append))
    assert asked_for(th) == ["octo/one"]              # over a week old
    assert lines[0].startswith("weekly tier: 2 repos; reports older than 168 hours (7 days) ")


def test_a_pass_without_a_tier_says_the_age_it_uses(th):
    lines: list[str] = []
    th.client.portal.call(lambda: warm.warm_once(
        th.svc, seeds=["octo/one"], starter=False, meta=False, finds=False,
        say=lines.append))
    assert lines[0] == "reports older than 20 hours are read again (HOLT_WARM_MAX_AGE_HOURS)"


@pytest.mark.parametrize("tier", [None, "monthly"])
def test_seeds_never_reported_go_before_any_report_is_read_again(th, tier):
    # A missing report comes before every refresh: also when the seed is far
    # down the list, or its details say dormant (those used to go behind
    # every report that was due again).
    seeds = ["octo/one", "octo/two", "octo/three", "pallets/flask", "octo/four"]
    add(th, reported("octo/one", days_ago=40), reported("octo/two", days_ago=50),
        dormant("octo/four"))
    lines: list[str] = []
    result = th.client.portal.call(lambda: warm.warm_once(
        th.svc, seeds=seeds, tier=tier, parallel=1, starter=False, meta=False, finds=False,
        say=lines.append))
    refreshed = ["octo/two", "octo/one"] if tier else ["octo/one", "octo/two"]
    assert asked_for(th) == ["octo/three", "pallets/flask", "octo/four", *refreshed]
    assert result.never_reported == 3
    assert "3 seeds have no report yet and go first" in lines
