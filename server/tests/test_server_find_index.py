"""/v1/find answers from Holt's own index first (reports + repo_meta), then adds
the GitHub search's repos that aren't already listed; the index still answers
when the search fails or the caller is over their work limit."""

from __future__ import annotations

import sys
import threading
import types
from datetime import timedelta

import pytest

from conftest import STATS, canned_report
from holt.starter import RULES_VERSION
from holt_server import find as find_mod
from holt_server.db import FindCache, RepoMeta, Report, StarterCache, now
from sqlalchemy import select, update


@pytest.fixture
def finder(monkeypatch):
    """A stand-in `holt.starter`: `results` is what the search returns,
    `fail` makes it raise, `gate` holds it; `issues[repo]` is what reading a
    repo's starter issues returns."""
    mod = types.ModuleType("holt.starter")
    mod.RULES_VERSION = RULES_VERSION
    state = types.SimpleNamespace(results=[], fail=None, gate=threading.Event(), calls=[],
                                  issues={}, read=[])
    state.gate.set()

    def find(languages, topics, hacktoberfest, token, limit, screen=None, progress=None,
             days=7, **kw):
        state.calls.append((tuple(languages), tuple(topics), hacktoberfest))
        state.gate.wait(10)
        if state.fail:
            raise state.fail
        return [{"repo": r, "verdict": "viable", "stats": {}, "issues": [issue(9)]}
                for r in state.results]

    def starter_issues(repo, token, limit, as_of=None):
        state.read.append(repo)
        return state.issues.get(repo, [])

    mod.find, mod.starter_issues = find, starter_issues
    monkeypatch.setitem(sys.modules, "holt.starter", mod)
    return state


def issue(number, title="Fix a thing", people=0, open_prs=0):
    return {"number": number, "title": title, "url": f"https://github.com/o/r/issues/{number}",
            "labels": ["good first issue"], "created_at": None, "comments": 0, "why": [],
            "people": people, "open_prs": open_prs}


def add(h, *items):
    async def go():
        async with h.svc.db.session() as s:
            s.add_all(items)
            await s.commit()
    h.client.portal.call(go)


def report(repo, verdict="viable", **stats):
    body = canned_report(repo, "rules", 7, verdict)
    body["stats"] = {**STATS, **stats}
    return Report(repo=repo, repo_key=repo.lower(), mode="rules", days=7, report=body)


def meta(repo, language="Python", topics=("hacktoberfest",), languages=None, **kw):
    return RepoMeta(repo_key=repo.lower(), repo=repo, language=language,
                    languages=list(languages if languages is not None else [language]),
                    stars=kw.pop("stars", 10), topics=list(topics), **kw)


def starters(repo, *issues, age_hours=0):
    return StarterCache(repo_key=repo.lower(), repo=repo, issues=list(issues),
                        rules_version=RULES_VERSION,
                        created_at=now() - timedelta(hours=age_hours))


def indexed(h, repo, verdict="viable", issues=(1,), stats=None, **meta_kw):
    """A checked repo: its report, its details and (with `issues`) its starter issues."""
    items = [report(repo, verdict, **(stats or {})), meta(repo, **meta_kw)]
    if issues is not None:
        items.append(starters(repo, *[issue(n) for n in issues]))
    add(h, *items)


def find(h, ip="10.0.0.1", **body):
    return h.post("/v1/find", {"hacktoberfest": False, **body}, ip=ip)


def names(results):
    return [r["repo"] for r in results]


def test_the_index_answers_at_once_while_the_search_runs(h, finder):
    indexed(h, "py/fair", stats={"outsider_merged": 3, "no_reply": 2})  # fair odds
    indexed(h, "py/good", stats={"outsider_merged": 12, "no_reply": 1})  # good odds
    indexed(h, "go/one", language="Go")
    finder.gate.clear()
    try:
        r = find(h, languages=["python"])
        assert r.status_code == 202
        body = r.json()
        # Ranked like the welcoming board: best odds first.
        assert names(body["results"]) == ["py/good", "py/fair"]
        first = body["results"][0]
        assert first["headline"] == "Worth your time" and first["language"] == "Python"
        assert [i["number"] for i in first["issues"]] == [1]
        assert first["stats"]["outsider_merged"] == 12
        # Someone else asking meanwhile joins the search and gets the index too.
        again = find(h, languages=["python"], ip="10.9.9.9")
        assert again.json()["job_id"] == body["job_id"]
        assert names(again.json()["results"]) == ["py/good", "py/fair"]
    finally:
        finder.gate.set()
    h.wait(body["job_id"], kind="find")


def test_filters_read_repo_meta(h, finder):
    indexed(h, "py/second", language="Rust", languages=["Rust", "Python"], topics=("cli",))
    indexed(h, "py/tagged", topics=("cli", "hacktoberfest"))
    indexed(h, "js/tagged", language="JavaScript", topics=("hacktoberfest",))
    indexed(h, "py/untagged", topics=())
    finder.gate.clear()
    try:
        # A real second language counts, as on the Discover cards.
        assert names(find(h, languages=["python"]).json()["results"]) == [
            "py/second", "py/tagged", "py/untagged"]
        assert names(find(h, languages=["python"], hacktoberfest=True).json()["results"]) == [
            "py/tagged"]
        assert names(find(h, topics=["cli"]).json()["results"]) == ["py/second", "py/tagged"]
        # Any one of the picked languages, as the search.
        assert names(find(h, languages=["javascript", "typescript"],
                          hacktoberfest=True).json()["results"]) == ["js/tagged"]
        assert names(find(h, hacktoberfest=True).json()["results"]) == [
            "js/tagged", "py/tagged"]
    finally:
        finder.gate.set()


def test_only_worth_your_time_open_repos_with_known_issues_are_listed(h, finder):
    indexed(h, "o/viable")
    indexed(h, "o/long", verdict="long_shot")
    # Closed to outside pull requests: "Not worth your time" by its verdict.
    indexed(h, "o/closed", verdict="not_viable")
    indexed(h, "o/archived", archived=True)
    indexed(h, "o/fork", fork=True)
    indexed(h, "o/no-issues", issues=())            # known: none to start on
    indexed(h, "o/stale-issues", issues=None)
    add(h, starters("o/stale-issues", issue(1), age_hours=100))
    indexed(h, "o/slow", stats={"median_first_response_hours": 60.0})
    finder.gate.clear()
    try:
        assert names(find(h, languages=["python"]).json()["results"]) == [
            "o/viable", "o/slow"]
        # Two and a half days to a first reply doesn't fit an evening.
        assert names(find(h, languages=["python"], days=1).json()["results"]) == ["o/viable"]
    finally:
        finder.gate.set()


def test_a_report_from_an_older_engine_is_not_the_index(h, finder):
    indexed(h, "o/old")

    async def age():
        async with h.svc.db.session() as s:
            await s.execute(update(Report).values(engine_version=1))
            await s.commit()

    h.client.portal.call(age)
    finder.gate.clear()
    try:
        assert find(h, languages=["python"]).json()["results"] == []
    finally:
        finder.gate.set()


def test_search_results_follow_the_index_without_duplicates(h, finder):
    indexed(h, "py/good", stats={"outsider_merged": 12, "no_reply": 1})
    indexed(h, "py/fair", stats={"outsider_merged": 3})
    finder.results = ["new/one", "PY/Good", "new/two"]
    done = h.wait(find(h, languages=["python"]).json()["job_id"], kind="find")
    assert done["status"] == "done"
    assert names(done["results"]) == ["py/good", "py/fair", "new/one", "new/two"]
    # The cached search is served the same way, free.
    again = find(h, languages=["python"], ip="10.8.8.8")
    assert again.status_code == 200 and again.json()["complete"] is True
    assert names(again.json()["results"]) == ["py/good", "py/fair", "new/one", "new/two"]
    # `limit` cuts the merged list.
    assert names(find(h, languages=["python"], limit=3).json()["results"]) == [
        "py/good", "py/fair", "new/one"]


def test_a_cached_search_reads_the_index_as_it_is_now(h, finder):
    finder.results = ["new/one"]
    h.wait(find(h, languages=["python"]).json()["job_id"], kind="find")
    indexed(h, "py/later")
    assert names(find(h, languages=["python"]).json()["results"]) == ["py/later", "new/one"]


def test_the_cache_keeps_the_search_only(h, finder):
    indexed(h, "py/good")
    finder.results = ["new/one"]
    h.wait(find(h, languages=["python"]).json()["job_id"], kind="find")

    async def cached():
        async with h.svc.db.session() as s:
            return [r["repo"] for row in (await s.execute(select(FindCache))).scalars()
                    for r in row.results]

    assert h.client.portal.call(cached) == ["new/one"]


def test_a_failed_search_still_leaves_the_index(h, finder):
    indexed(h, "py/good")
    finder.fail = RuntimeError("GitHub is down")
    r = find(h, languages=["python"])
    assert r.status_code == 202 and names(r.json()["results"]) == ["py/good"]
    assert h.wait(r.json()["job_id"], kind="find")["status"] == "error"


def test_over_the_work_limit_the_index_is_the_answer(make_harness, finder):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=1)
    indexed(h, "py/good")
    indexed(h, "go/good", language="Go")
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")  # spends the limit
    r = find(h, languages=["python"])
    assert r.status_code == 200
    assert r.json() == {**r.json(), "status": "done", "complete": False}
    assert names(r.json()["results"]) == ["py/good"]
    assert len(finder.calls) == 1
    # With nothing in the index, the limit is still the answer.
    assert find(h, languages=["rust"]).status_code == 429


def test_a_search_reads_issues_for_index_repos_that_have_none_known(h, finder):
    indexed(h, "py/listed")
    indexed(h, "py/unread", issues=None)
    indexed(h, "py/empty", issues=())
    finder.issues = {"py/unread": [issue(5)]}

    async def canonical(repo):
        return repo

    h.svc.canonical = canonical
    r = find(h, languages=["python"])
    assert names(r.json()["results"]) == ["py/listed"]
    done = h.wait(r.json()["job_id"], kind="find")
    # Read during the search, so it's in the answer; a repo known to have
    # none isn't read again.
    assert finder.read == ["py/unread"]
    assert sorted(names(done["results"])) == ["py/listed", "py/unread"]
    assert find(h, languages=["python"]).json()["results"][1]["issues"][0]["number"] == 5


def test_a_search_reads_issues_for_the_first_few_only(h, finder):
    for i in range(4):
        indexed(h, f"py/r{i}", issues=None)
    got = h.client.portal.call(find_mod.unlisted, h.svc,
                               {"languages": ["python"], "days": 7}, 2)
    assert len(got) == 2


def test_a_search_reads_again_the_first_listed_whose_issues_have_aged(h, finder):
    indexed(h, "py/fresh")
    add(h, report("py/aged"), meta("py/aged"), starters("py/aged", issue(1), age_hours=7))
    add(h, report("py/gone"), meta("py/gone"), starters("py/gone", issue(2), age_hours=30))
    finder.issues = {"py/aged": [issue(8)]}  # #1 was closed; py/gone has none left

    async def canonical(repo):
        return repo

    h.svc.canonical = canonical
    r = find(h, languages=["python"])
    assert sorted(names(r.json()["results"])) == ["py/aged", "py/fresh", "py/gone"]
    done = h.wait(r.json()["job_id"], kind="find")
    assert sorted(finder.read) == ["py/aged", "py/gone"]
    listed = {x["repo"]: [i["number"] for i in x["issues"]] for x in done["results"]}
    assert listed == {"py/aged": [8], "py/fresh": [1]}


def test_only_the_first_listed_are_read_again(h, finder):
    for i in range(4):
        add(h, report(f"py/r{i}"), meta(f"py/r{i}"), starters(f"py/r{i}", issue(1), age_hours=9))
    got = h.client.portal.call(find_mod.aged, h.svc, {"languages": ["python"], "days": 7}, 2)
    assert len(got) == 2


def test_repos_whose_issues_are_all_taken_are_listed_last(h, finder):
    # Better odds, but someone is on its only issue.
    add(h, report("py/taken", outsider_merged=12, no_reply=1), meta("py/taken"),
        starters("py/taken", issue(1, open_prs=1, people=1)))
    add(h, report("py/free", outsider_merged=3, no_reply=2), meta("py/free"),
        starters("py/free", issue(2, people=1), issue(3)))
    results = find(h, languages=["python"]).json()["results"]
    assert names(results) == ["py/free", "py/taken"]
    # Nobody-on-it first within a repo.
    assert [i["number"] for i in results[0]["issues"]] == [3, 2]
    assert results[1]["issues"][0]["on_it"] == "1 open pull request"


def test_taken_issues_are_left_out_when_enough_are_free(h, finder):
    add(h, report("py/busy"), meta("py/busy"),
        starters("py/busy", issue(1, people=1), issue(2), issue(3), issue(4)))
    (result,) = find(h, languages=["python"]).json()["results"]
    assert [i["number"] for i in result["issues"]] == [2, 3, 4]


# --- the rest of the index, in parts ------------------------------------------------


def index_parts(h, limit, **body):
    out, cursor = [], None
    while True:
        r = h.post("/v1/find/index", {"limit": limit, "cursor": cursor, **body})
        assert r.status_code == 200, r.text
        out.append(r.json())
        cursor = out[-1]["next"]
        if cursor is None:
            return out


def test_the_index_comes_in_parts_in_find_order_with_no_repeats(h, finder):
    for i in range(5):
        indexed(h, f"py/r{i}", stats={"outsider_merged": 12 - i, "no_reply": 1})
    indexed(h, "go/other", language="Go")
    first = find(h, languages=["python"], limit=2)
    whole = [f"py/r{i}" for i in range(5)]
    assert names(first.json()["results"]) == whole[:2]
    got = index_parts(h, 2, languages=["Python"])
    assert [names(p["results"]) for p in got] == [whole[:2], whole[2:4], whole[4:]]
    assert {p["total"] for p in got} == {5} and got[-1]["next"] is None
    assert got[0]["results"][0]["issues"], "the same cards a find lists"


def test_scrolling_the_index_never_searches_or_spends_anything(make_harness, finder):
    h = make_harness(anon_rate_per_hour=1)
    for i in range(3):
        indexed(h, f"py/r{i}")
    for _ in range(4):
        assert len(index_parts(h, 1, languages=["python"])) == 3
    assert finder.calls == [] and finder.read == []
    assert h.client.post("/v1/find/index", json={}).status_code == 401, "the internal key"
    assert h.post("/v1/find/index", {"cursor": "nope"}).status_code == 400


def test_a_kept_index_part_reads_nothing(h, finder):
    from sqlalchemy import event
    for i in range(3):
        indexed(h, f"py/r{i}")
    first = h.post("/v1/find/index", {"limit": 2}).json()
    seen = []
    engine = h.svc.db.engine.sync_engine
    note = lambda conn, cursor, statement, *rest: seen.append(statement)  # noqa: E731
    event.listen(engine, "before_cursor_execute", note)
    try:
        second = h.post("/v1/find/index", {"limit": 2, "cursor": first["next"]}).json()
    finally:
        event.remove(engine, "before_cursor_execute", note)
    assert names(second["results"]) == ["py/r2"] and seen == []
