"""`holt start`: starter-issue scoring, the find pipeline, rate limits, and the
discover sourcing fixes. No network: live calls are replayed from recordings in
`tests/recordings/starter/` (see `record.py` there) or faked inline."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from holt import cli, discover, starter
from holt.agent.landing import Area
from holt.profile import Profile
from holt.report import Verdict

DATA = Path(__file__).parent / "recordings" / "starter"
AS_OF = datetime(2026, 9, 25, tzinfo=UTC)


# --- helpers ---------------------------------------------------------------


def iso(days_ago: float) -> str:
    return (AS_OF - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def issue(number=1, *, title="Fix crash", body="x" * 300, labels=("good first issue",),
          updated=3, created=40, comments=2, assignees=0, closing=(), xref=(),
          recent=(), repo="o/r", archived=False):
    return {
        "number": number, "title": title, "body": body, "locked": False,
        "url": f"https://github.com/{repo}/issues/{number}",
        "createdAt": iso(created), "updatedAt": iso(updated),
        "repository": {"nameWithOwner": repo, "isArchived": archived},
        "labels": {"nodes": [{"name": n} for n in labels]},
        "assignees": {"totalCount": assignees},
        "comments": {"totalCount": comments},
        "recent": {"nodes": [{"createdAt": iso(d), "body": b, "author": {"login": "u"}}
                             for d, b in recent]},
        "closedByPullRequestsReferences": {"nodes": [{"state": s} for s in closing]},
        "timelineItems": {"nodes": [{"source": {"state": s}} for s in xref]},
    }


def score(node, **kw):
    return starter.score_issue(node, AS_OF, **kw)


def replay_transport(name: str) -> tuple[starter.GitHub, datetime]:
    """A `starter.GitHub` whose HTTP calls are answered from a recording."""
    recording = json.loads((DATA / name).read_text(encoding="utf-8"))
    by_key = {c["key"]: c["response"] for c in recording["calls"]}

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        key = starter.query_key(sent["query"], sent["variables"])
        if key not in by_key:
            raise AssertionError(f"unrecorded GitHub call: {sent['variables']}")
        return httpx.Response(200, json=by_key[key])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (starter.GitHub(token="test", client=client, sleep=lambda s: None),
            datetime.fromisoformat(recording["as_of"]))


def scripted(responses, sleeps=None):
    """A transport that answers with `responses` in order."""
    queue = list(responses)

    def handler(request):
        return queue.pop(0)

    return starter.GitHub(token="test",
                          client=httpx.Client(transport=httpx.MockTransport(handler)),
                          sleep=(sleeps.append if sleeps is not None else lambda s: None))


# --- labels ----------------------------------------------------------------


@pytest.mark.parametrize("label,kind", [
    ("good first issue", "beginner"), ("Good First Issue", "beginner"),
    ("good-first-issue", "beginner"), ("good first issue :+1:", "beginner"),
    ("first-timers-only", "beginner"), ("Beginner Friendly", "beginner"),
    ("E-easy", "easy"), ("difficulty: easy", "easy"), ("help wanted", "help"),
    ("Hacktoberfest", "hacktoberfest"), ("wontfix", "not_ready"),
    ("question", "not_ready"),
])
def test_label_variants(label, kind):
    assert kind in starter.label_kinds([label])


def test_unrelated_labels_mean_nothing():
    assert starter.label_kinds(["bug", "hacktoberfest-accepted", "area/cli"]) == set()


# --- scoring ---------------------------------------------------------------


def test_labelled_issue_scores_with_reasons():
    got = score(issue(labels=("Good First Issue",), updated=2))
    assert got is not None
    points, result = got
    assert points > 4
    assert result.why[0] == "Labelled “Good First Issue” by the maintainers"
    assert any("Active recently" in w for w in result.why)
    assert result.url == "https://github.com/o/r/issues/1"


@pytest.mark.parametrize("node", [
    issue(assignees=1),
    issue(closing=("OPEN",)),
    issue(xref=("OPEN",)),
    issue(updated=starter.ACTIVE_DAYS + 1),
    issue(labels=("good first issue", "needs design")),
    issue(labels=(), title="Refactor the scheduler"),
    issue(archived=True),
])
def test_excluded(node):
    assert score(node) is None


def test_closed_or_merged_linked_prs_do_not_exclude():
    assert score(issue(closing=("MERGED",), xref=("CLOSED",))) is not None


def test_unlabelled_small_fix_qualifies():
    _, result = score(issue(labels=(), title="Typo in README", body="teh -> the"))
    assert result.why[0] == "Looks like a small fix (about typo)"


def test_unlabelled_long_issue_does_not_qualify():
    assert score(issue(labels=(), title="Docs are confusing", body="x" * 3000)) is None


def test_hacktoberfest_mode_weighs_the_label_more():
    node = issue(labels=("hacktoberfest",))
    assert score(node, hacktoberfest=True)[0] > score(node)[0]


def test_fresh_claim_and_long_thread_are_cautions_and_cost_points():
    plain = score(issue())[0]
    points, result = score(issue(recent=[(3, "Hi! Can I work on this?")]))
    assert points < plain
    assert result.why[-1].startswith("Someone asked to work on this 3 days ago")
    old_claim = score(issue(recent=[(200, "can i take this")]))[0]
    assert old_claim == plain
    points, result = score(issue(comments=30))
    assert points < plain and "Long discussion (30 comments)" in result.why[-1]


LANDING = [Area("docs", 8, 10), Area("src/widgets", 4, 6), Area("src", 9, 20),
           Area("r", 5, 5), Area("tests", 1, 9)]


def test_landing_boost_for_a_named_area():
    points, result = score(issue(title="Fix wording in the docs"), landing=LANDING)
    assert points > score(issue(title="Fix wording in the docs"))[0]
    assert ("Mentions docs/, where 8 of 10 pull requests from first-time "
            "contributors were merged") in result.why


def test_landing_boost_for_a_nested_path_or_its_distinctive_name():
    for body in ("see src/widgets/button.py", "the widgets module is wrong"):
        _, result = score(issue(body=body + " " + "x" * 200), landing=LANDING)
        assert any(w.startswith("Mentions src/widgets/") for w in result.why), body


def test_no_boost_for_generic_dirs_the_project_name_or_poor_areas():
    # `src/` is generic, `r` is the repository's own name, `tests` rarely lands.
    body = "crash in src/main.py; r is great; please add tests " + "x" * 200
    _, result = score(issue(body=body), landing=LANDING)
    assert not any(w.startswith("Mentions") for w in result.why)


def test_rank_dedupes_sorts_and_limits():
    nodes = [issue(1, labels=("help wanted",)), issue(2), issue(2),
             issue(3, labels=("good first issue", "easy")), issue(4, assignees=1)]
    ranked = starter.rank(nodes, AS_OF, limit=2)
    assert [i.number for _, i in ranked] == [3, 2]


# --- one repository (recorded) ---------------------------------------------


def test_starter_issues_from_recording():
    transport, as_of = replay_transport("repo.json")
    issues = starter.starter_issues("https://github.com/ManimCommunity/manim", None,
                                    as_of=as_of, transport=transport)
    assert issues
    assert len({i.number for i in issues}) == len(issues)
    for i in issues:
        assert i.url.startswith("https://github.com/ManimCommunity/manim/issues/")
        assert i.why
        assert set(i.as_dict()) == {"number", "title", "url", "labels", "created_at",
                                    "comments", "why"}
    # Everything listed is labelled for newcomers or a small unlabelled fix.
    assert all(starter.label_kinds(i.labels) or i.why[0].startswith("Looks like")
               for i in issues)


def test_missing_repository_is_not_found():
    transport = scripted([httpx.Response(200, json={
        "data": {"repository": None, "labelled": {"nodes": []}},
        "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]})])
    with pytest.raises(starter.RepoNotFound):
        starter.starter_issues("nobody/nothing", None, as_of=AS_OF, transport=transport)


@pytest.mark.parametrize("raw,slug", [
    ("pallets/flask", "pallets/flask"),
    ("https://github.com/pallets/flask/tree/main", "pallets/flask"),
    ("github.com/pallets/flask.git", "pallets/flask"),
    ("https://github.com/pallets/flask?tab=readme", "pallets/flask"),
])
def test_normalise_repo(raw, slug):
    assert starter.normalise_repo(raw) == slug


# --- find (recorded) -------------------------------------------------------

FIND_ARGS = {"languages": ["python"], "topics": [], "hacktoberfest": True,
             "max_repos": 3, "per_repo": 3, "limit": 3}


def test_find_from_recording_returns_only_viable_repos_with_issues():
    transport, as_of = replay_transport("find.json")
    messages: list[str] = []
    results = starter.find(token=None, transport=transport, as_of=as_of,
                           progress=messages.append, budget_seconds=60, **FIND_ARGS)
    assert results
    assert messages[0] == "Searching GitHub for beginner-friendly issues"
    for r in results:
        assert r.verdict == "viable" and r.headline == "Worth your time"
        assert 1 <= len(r.issues) <= 3
        assert {"outsider_attempts", "outsider_merged",
                "median_first_response_hours"} <= set(r.stats)
        body = r.as_dict()
        assert set(body) == {"repo", "headline", "verdict", "stats", "issues"}
        json.dumps(body)  # the API shape is plain JSON


def test_find_uses_the_screen_it_is_given():
    transport, as_of = replay_transport("find.json")
    asked: list[str] = []

    def reject(repo):
        asked.append(repo)
        return starter.RepoScreen(verdict="not_viable")

    assert starter.find(token=None, transport=transport, as_of=as_of, screen=reject,
                        budget_seconds=60, **FIND_ARGS) == []
    assert len(asked) == 3


def test_find_passes_cached_stats_through():
    transport, as_of = replay_transport("find.json")
    cached = starter.RepoScreen(verdict=Verdict.VIABLE, stats={"outsider_merged": 99})
    results = starter.find(token=None, transport=transport, as_of=as_of,
                           screen=lambda repo: cached, budget_seconds=60, **FIND_ARGS)
    assert results and all(r.stats == {"outsider_merged": 99} for r in results)


def test_find_stops_at_its_budget():
    transport, as_of = replay_transport("find.json")

    def slow(repo):
        time.sleep(0.3)
        return starter.RepoScreen(verdict="viable")

    started = time.monotonic()
    messages: list[str] = []
    results = starter.find(token=None, transport=transport, as_of=as_of, screen=slow,
                           budget_seconds=0.1, progress=messages.append, **FIND_ARGS)
    assert time.monotonic() - started < 0.3 + 0.2
    assert results == []
    assert any(m.startswith("Stopped after") for m in messages)


def test_source_queries():
    issue_qs = starter.issue_source_queries(["python", "rust"], False, AS_OF)
    assert len(issue_qs) == 2 and all("-linked:pr" in q and "no:assignee" in q
                                      for q in issue_qs)
    assert "label:hacktoberfest" in starter.issue_source_queries(["go"], True, AS_OF)[0]
    repo_qs = starter.repo_source_queries(["python"], ["cli", "web"], True, AS_OF)
    assert len(repo_qs) == 2
    assert all("topic:hacktoberfest" in q for q in repo_qs)
    assert not any("topic:cli" in q and "topic:web" in q for q in repo_qs)
    (only,) = starter.repo_source_queries([], [], True, AS_OF)
    assert only.startswith("topic:hacktoberfest")


# --- rate limits -----------------------------------------------------------

OK = {"data": {"rateLimit": {"remaining": 10}, "x": 1}}


def test_short_rate_limit_waits_and_retries():
    sleeps: list[float] = []
    transport = scripted([httpx.Response(403, headers={"retry-after": "2"}),
                          httpx.Response(200, json=OK)], sleeps)
    assert transport.query("q")["x"] == 1
    assert sleeps == [2.0]
    assert transport.remaining == 10


def test_long_rate_limit_raises_with_retry_after():
    transport = scripted([httpx.Response(429, headers={"retry-after": "120"})])
    with pytest.raises(starter.RateLimited) as err:
        transport.query("q")
    assert err.value.retry_after == 120


def test_primary_limit_uses_the_reset_header():
    reset = str(int(time.time()) + 600)
    transport = scripted([httpx.Response(403, headers={
        "x-ratelimit-remaining": "0", "x-ratelimit-reset": reset})])
    with pytest.raises(starter.RateLimited) as err:
        transport.query("q")
    assert 590 <= err.value.retry_after <= 601


def test_graphql_rate_limited_error():
    transport = scripted([httpx.Response(200, json={
        "data": None, "errors": [{"type": "RATE_LIMITED", "message": "slow down"}]})])
    with pytest.raises(starter.RateLimited):
        transport.query("q")


def test_plain_forbidden_is_not_a_rate_limit():
    transport = scripted([httpx.Response(403, text="Resource not accessible")])
    with pytest.raises(httpx.HTTPStatusError):
        transport.query("q")


def test_transient_errors_retry():
    transport = scripted([httpx.Response(502), httpx.Response(200, json=OK)])
    assert transport.query("q")["x"] == 1


def test_find_raises_rate_limit_when_nothing_was_found():
    class Limited(starter.GitHub):
        def __init__(self):
            pass

        def query(self, document, **variables):
            raise starter.RateLimited(30)

    with pytest.raises(starter.RateLimited):
        starter.find(["python"], [], False, None, transport=Limited(), as_of=AS_OF)


# --- discover fixes --------------------------------------------------------


def test_discover_ors_topics_with_one_query_each():
    queries = discover.build_queries(
        Profile(languages=["python"], topics=["cli", "web"]), AS_OF)
    assert len(queries) == 2
    assert not any("topic:cli" in q and "topic:web" in q for q in queries)
    assert discover.build_queries(Profile(topics=["a", "b"]), AS_OF)[1].startswith("topic:b")


def test_discover_takes_repos_with_starter_issues_first():
    class Search:
        def search_repositories(self, q, max_pages):
            return [{"nameWithOwner": f"o/{n}", "goodFirstIssues": {"totalCount": c}}
                    for n, c in (("none", 0), ("some", 3), ("many", 9), ("also", 3))]

    got, _ = discover.source(Search(), Profile(languages=["go"]), AS_OF, limit=3)
    assert [c.slug for c in got] == ["o/many", "o/some", "o/also"]
    assert got[0].as_dict()["good_first_issues"] == 9


def test_discover_merges_topic_queries_without_duplicates():
    class Search:
        def search_repositories(self, q, max_pages):
            name = "cli" if "topic:cli" in q else "web"
            return [{"nameWithOwner": "o/both"}, {"nameWithOwner": f"o/{name}"}]

    got, queries = discover.source(Search(), Profile(topics=["cli", "web"]), AS_OF, 4)
    assert len(queries) == 2
    assert [c.slug for c in got] == ["o/both", "o/cli", "o/web"]


# --- CLI -------------------------------------------------------------------


def test_cli_start_needs_a_token(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert cli.main(["start", "--lang", "python"]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_cli_start_needs_something_to_search_for(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert cli.main(["start"]) == 2
    assert "--lang" in capsys.readouterr().err


def _result():
    return starter.FindResult(
        repo="o/r", headline="Worth your time", verdict="viable",
        stats={"outsider_attempts": 10, "outsider_merged": 4,
               "median_first_response_hours": 0.5},
        issues=[starter.StarterIssue(7, "Fix typo", "https://github.com/o/r/issues/7",
                                     ["good first issue"], iso(3), 1,
                                     ["Labelled “good first issue” by the maintainers"])])


def test_cli_start_find_text_and_json(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    seen = {}

    def fake_find(languages, topics, hacktoberfest, token, **kw):
        seen.update(languages=languages, topics=topics, hacktoberfest=hacktoberfest)
        return [_result()]

    monkeypatch.setattr(starter, "find", fake_find)
    assert cli.main(["start", "--lang", "python,rust", "--topic", "cli",
                     "--hacktoberfest"]) == 0
    out = capsys.readouterr().out
    assert seen == {"languages": ["python", "rust"], "topics": ["cli"],
                    "hacktoberfest": True}
    assert "1. o/r: Worth your time" in out
    assert "4 of 10 recent pull requests from first-time contributors" in out
    assert "https://github.com/o/r/issues/7" in out

    assert cli.main(["start", "--lang", "python", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["results"][0]["issues"][0]["number"] == 7


def test_cli_start_single_repo(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    transport, as_of = replay_transport("repo.json")
    monkeypatch.setattr(starter, "GitHub", lambda token: transport)
    # No recorded screen for this repository: the command still lists issues.
    monkeypatch.setattr(starter, "rules_screen",
                        lambda *a: (lambda repo: (_ for _ in ()).throw(RuntimeError("x"))))
    real = starter.starter_issues
    monkeypatch.setattr(starter, "starter_issues",
                        lambda *a, **kw: real(*a, **{**kw, "as_of": as_of}))
    assert cli.main(["start", "ManimCommunity/manim", "--limit", "2"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("# Where to start in ManimCommunity/manim")
    assert captured.out.count("https://github.com/ManimCommunity/manim/issues/") == 2
    assert "listing issues only" in captured.err
