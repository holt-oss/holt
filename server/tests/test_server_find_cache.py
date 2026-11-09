"""/v1/find answers from a 6h cache per normalised profile; hits are free."""

from __future__ import annotations

import sys
import threading
import time
import types
from datetime import timedelta

import pytest
from holt.starter import RULES_VERSION
from conftest import STATS, canned_report
from holt_server import discover
from holt_server.db import FindCache, RepoMeta, Report, now
from sqlalchemy import update

LANGS = ["python", "javascript", "typescript", "go", "rust"]


@pytest.fixture
def finder(monkeypatch):
    mod = types.ModuleType("holt.starter")
    calls = []
    gate = threading.Event()
    gate.set()

    def find(languages, topics, hacktoberfest, token, limit, screen=None, progress=None,
             days=7, **kw):
        calls.append((tuple(languages), hacktoberfest, limit))
        gate.wait(10)
        count = kw.get("_n", 3)
        return [{"repo": f"octo/{'-'.join(languages) or 'any'}-{i}", "verdict": "viable",
                 "stats": {}, "issues": []} for i in range(count)]

    def starter_issues(repo, token, limit, as_of=None):
        return []

    mod.find, mod.starter_issues = find, starter_issues
    monkeypatch.setitem(sys.modules, "holt.starter", mod)
    return types.SimpleNamespace(calls=calls, gate=gate)


def find(h, ip="10.0.0.1", **body):
    return h.post("/v1/find", {"hacktoberfest": True, **body}, ip=ip)


def test_clicking_through_language_chips_keeps_the_work_budget(make_harness, finder):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=5)
    for lang in LANGS:  # the first visitor pays for each search once
        h.wait(find(h, ip="1.1.1.1", languages=[lang]).json()["job_id"], kind="find")
    h2 = h  # a second visitor, with a much smaller budget in effect
    for _ in range(3):
        for lang in LANGS:
            r = find(h2, ip="2.2.2.2", languages=[lang])
            assert r.status_code == 200 and r.json()["status"] == "done"
            assert r.json()["results"][0]["repo"] == f"octo/{lang}-0"
    assert len(finder.calls) == 5
    # Fifteen clicks later, their whole work budget is still there.
    for repo in ("octo/one", "octo/two", "octo/three", "octo/four", "pallets/flask"):
        assert h.post("/v1/analyses", {"repo": repo}, ip="2.2.2.2").status_code == 202


def test_profiles_are_normalised(h, finder):
    h.wait(find(h, languages=["Python", "rust"], topics=["CLI"]).json()["job_id"], kind="find")
    r = find(h, languages=["rust", "python", "python"], topics=["cli "])
    assert r.status_code == 200
    assert len(finder.calls) == 1
    # Hacktoberfest and days are part of the question.
    assert find(h, languages=["python", "rust"], topics=["cli"],
                hacktoberfest=False).status_code == 202
    assert find(h, languages=["python", "rust"], topics=["cli"], days=30).status_code == 202


def test_joining_an_in_flight_search_is_free(make_harness, finder):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=1)
    finder.gate.clear()
    try:
        first = find(h, ip="3.3.3.3", languages=["go"])
        second = find(h, ip="3.3.3.3", languages=["go"])  # over the limit, but joins
        assert first.status_code == second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]
    finally:
        finder.gate.set()
    h.wait(first.json()["job_id"], kind="find")
    assert len(finder.calls) == 1


def test_cache_expires_after_six_hours(h, finder):
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")

    async def age():
        async with h.svc.db.session() as s:
            await s.execute(update(FindCache).values(created_at=now() - timedelta(hours=7)))
            await s.commit()

    h.client.portal.call(age)
    assert find(h, languages=["go"]).status_code == 202


def test_a_search_cached_before_issues_said_who_is_on_them_runs_again():
    from holt_server.db import ENGINE_VERSION

    def row(issue):
        return FindCache(key="k", params={"engine_version": ENGINE_VERSION,
                                          "starter_rules": RULES_VERSION},
                         results=[{"repo": "o/r", "issues": [issue]}])

    assert row({"number": 1, "title": "t"}).outdated
    assert not row({"number": 1, "title": "t", "people": 0, "open_prs": 0}).outdated


@pytest.mark.parametrize("rules", [None, RULES_VERSION - 1])
def test_a_search_older_starter_rules_picked_runs_again(rules):
    from holt_server.db import ENGINE_VERSION

    params = {"engine_version": ENGINE_VERSION}
    if rules is not None:
        params["starter_rules"] = rules
    assert FindCache(key="k", params=params, results=[]).outdated


def test_limit_beyond_what_was_computed_is_a_miss(h, finder):
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")  # 3 results < 20
    # The search ran dry below its limit, so a bigger page would find nothing new.
    r = find(h, languages=["go"], limit=50)
    assert r.status_code == 200 and len(r.json()["results"]) == 3
    assert len(find(h, languages=["go"], limit=2).json()["results"]) == 2
    assert finder.calls[0][2] == 20  # computed for at least the default page


def add(h, *items):
    async def go():
        async with h.svc.db.session() as s:
            s.add_all(items)
            await s.commit()
    h.client.portal.call(go)


def meta(repo, **kw):
    return RepoMeta(repo_key=repo.lower(), repo=repo, description=kw.get("description"),
                    language=kw.get("language"), stars=kw.get("stars", 0), topics=[],
                    open_issues=kw.get("open_issues"), pull_requests=kw.get("pull_requests"),
                    open_pull_requests=kw.get("open_pull_requests"), contributors=kw.get("contributors"), links=[])


def details(results):
    return {r["repo"]: (r["description"], r["language"], r["stars"]) for r in results}


def test_results_carry_the_repo_details_holt_already_has(h, finder):
    # The finder knows nothing about a repo beyond its screen; `repo_meta` does.
    add(h, meta("Octo/Go-0", description="A tool.", language="Go", stars=321))
    done = h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    assert details(done["results"]) == {
        "octo/go-0": ("A tool.", "Go", 321),
        "octo/go-1": (None, None, None),  # not fetched yet: null, never guessed
        "octo/go-2": (None, None, None),
    }
    assert details(find(h, languages=["go"]).json()["results"])["octo/go-0"] == (
        "A tool.", "Go", 321)


def test_results_carry_the_repo_counts(h, finder):
    add(h, meta("Octo/Go-0", open_issues=57, pull_requests=4100, open_pull_requests=12, contributors=812))
    for results in (h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")["results"],
                    find(h, languages=["go"]).json()["results"]):
        by = {r["repo"]: r for r in results}
        assert [by["octo/go-0"][k] for k in ("open_issues", "pull_requests", "open_pull_requests", "contributors")] == [57, 4100, 12, 812]
        assert by["octo/go-1"]["contributors"] is None  # not read yet


def test_a_cached_search_picks_up_details_that_arrived_later(h, finder):
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    add(h, meta("octo/go-1", description="Later.", language="Go", stars=7))
    got = details(find(h, languages=["go"]).json()["results"])
    assert got["octo/go-1"] == ("Later.", "Go", 7)
    assert got["octo/go-0"] == (None, None, None)


def test_the_warm_pass_fetches_details_for_found_repos(h, finder):
    from holt_server import discover

    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    add(h, meta("octo/go-0", language="Go"))
    stale = h.client.portal.call(discover.stale_meta, h.svc)
    assert sorted(stale) == ["octo/go-1", "octo/go-2"]


def queued_reports(h):
    from holt_server.db import Job
    from sqlalchemy import select

    async def go():
        async with h.svc.db.session() as s:
            return sorted((j.repo, j.days, j.priority, j.user_id) for j in (await s.execute(
                select(Job).where(Job.kind == "analysis"))).scalars())
    return h.client.portal.call(go)


def settle(h, n):
    deadline = time.monotonic() + 10
    while len(queued_reports(h)) < n and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)  # and nothing more arrives
    return queued_reports(h)


def test_a_search_queues_reports_for_its_top_results_only(h, finder, monkeypatch):
    from holt_server import jobs

    monkeypatch.setattr(jobs, "FOUND_PER_SEARCH", 2)
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    assert [r[0] for r in settle(h, 2)] == ["octo/go-0", "octo/go-1"]


def test_a_long_background_queue_stops_searches_queueing_more(h, finder, monkeypatch):
    from holt_server import jobs

    monkeypatch.setattr(jobs, "FOUND_QUEUE_MAX", 0)
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    assert settle(h, 0) == []


def test_searches_queue_nothing_when_github_points_run_low(h, finder):
    # Two tokens, each still usable, 1200 points between them: under the
    # warm pass's 1500 floor, which is kept for people's own checks.
    h.svc.pool.note_points(0, 600)
    h.svc.pool.note_points(1, 600)
    assert h.svc.pool.points_left() == 1200
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    assert settle(h, 0) == []


def test_a_points_count_past_its_reset_doesnt_stop_searches_queueing(h, finder):
    # points_left()'s other caller: the same out-of-date count held it back too.
    from datetime import UTC, datetime, timedelta

    gone = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    h.svc.pool.note_points(0, 600, gone)
    h.svc.pool.note_points(1, 600, gone)
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")
    assert settle(h, 3)


def test_found_repos_without_a_report_get_one_queued(h, finder):
    # A search screens repos without storing reports, so each one it lists
    # gets a background rules report: its "report →" link then has something
    # to show (beets was "Worth your time" on /hacktoberfest, "not checked yet"
    # on its report page).
    from holt_server.db import BADGE_PRIORITY, ENGINE_VERSION, Job, Report
    from sqlalchemy import select

    add(h, Report(repo="octo/go-1", repo_key="octo/go-1", mode="rules", days=30,
                  report={"verdict": "viable"}, engine_version=ENGINE_VERSION))
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")

    async def queued():
        async with h.svc.db.session() as s:
            return sorted((j.repo, j.days, j.priority, j.user_id) for j in (await s.execute(
                select(Job).where(Job.kind == "analysis"))).scalars())

    # Queued just after the search is marked done.
    deadline = time.monotonic() + 10
    while len(h.client.portal.call(queued)) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert h.client.portal.call(queued) == [
        ("octo/go-0", 7, BADGE_PRIORITY, None),
        ("octo/go-2", 7, BADGE_PRIORITY, None),
    ]
    # The same search again (from the cache) queues nothing new.
    find(h, languages=["go"])
    assert len(h.client.portal.call(queued)) == 2


def test_results_borrow_the_reports_breakdown_so_the_bar_matches_discover(h):
    full = {**STATS, "closed_silently": 4, "closed_by_bot": 1, "withdrawn": 0, "still_open": 3}
    add(h, Report(repo="octo/a", repo_key="octo/a", mode="rules", days=7, created_at=now(),
                  report={**canned_report("octo/a"), "stats": full}))
    screen = {"outsider_attempts": 20, "outsider_merged": 8}
    found = [
        {"repo": "octo/a", "stats": screen},
        {"repo": "octo/a", "stats": {**screen, "outsider_merged": 9}},  # another window: not the same pull requests
        {"repo": "octo/nope", "stats": screen},
    ]

    async def run():
        async with h.svc.db.session() as s:
            return await discover.with_meta(s, found)
    same, other, unknown = h.client.portal.call(run)
    assert same["stats"]["closed_silently"] == 4 and same["stats"]["still_open"] == 3
    assert "closed_silently" not in other["stats"] and "closed_silently" not in unknown["stats"]
