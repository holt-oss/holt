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

from holt import cli, discover, model, starter
from holt.agent.landing import Area
from holt.profile import Profile
from holt.report import Verdict

DATA = Path(__file__).parent / "recordings" / "starter"
AS_OF = datetime(2026, 9, 25, tzinfo=UTC)


# --- helpers ---------------------------------------------------------------


def iso(days_ago: float) -> str:
    return (AS_OF - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _pr(entry):
    """A linked pull request: a state, or (state, author login)."""
    state, author = (entry, "prauthor") if isinstance(entry, str) else entry
    return {"state": state, "author": {"login": author}}


def issue(number=1, *, title="Fix crash", body="x" * 300, labels=("good first issue",),
          updated=3, created=40, comments=2, assignees=0, closing=(), xref=(),
          recent=(), repo="o/r", archived=False, author="", assigned=(),
          association="NONE"):
    """A GraphQL issue node. `recent` comments are (days ago, body) or (days ago,
    body, login); `assigned` is (login, days ago) for each current assignee."""
    return {
        "number": number, "title": title, "body": body, "locked": False,
        # By default each issue has its own author, so helpers never form a farm.
        "author": None if author is None else {"login": author or f"user{number}"},
        "authorAssociation": association,
        "url": f"https://github.com/{repo}/issues/{number}",
        "createdAt": iso(created), "updatedAt": iso(updated),
        "repository": {"nameWithOwner": repo, "isArchived": archived},
        "labels": {"nodes": [{"name": n} for n in labels]},
        "assignees": ({"totalCount": len(assigned),
                       "nodes": [{"login": login} for login, _ in assigned]}
                      if assigned else {"totalCount": assignees}),
        "comments": {"totalCount": comments},
        "recent": {"nodes": [{"createdAt": iso(c[0]), "body": c[1],
                              "author": {"login": c[2] if len(c) > 2 else "u"}}
                             for c in recent]},
        "closedByPullRequestsReferences": {"nodes": [_pr(e) for e in closing]},
        "timelineItems": {"nodes": [
            *({"source": _pr(e)} for e in xref),
            *({"createdAt": iso(days), "assignee": {"login": login}}
              for login, days in assigned)]},
    }


def score(node, **kw):
    return starter.score_issue(node, AS_OF, **kw)


# The evidence queries as they were when `find.json` was recorded, before the
# v2 capture added fields to them. Recordings are keyed by query text, so a
# v2 query is looked up under its v1 text: the recorded v1 answer lacks the v2
# fields, which the projection treats as optional, so it replays unchanged.
V1_REPO_META = """
query($owner:String!, $name:String!, $until:GitTimestamp!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    createdAt pushedAt isArchived isMirror isFork stargazerCount
    description homepageUrl primaryLanguage { name }
    defaultBranchRef {
      name
      target {
        ... on Commit { history(until:$until, first:1) { nodes { oid committedDate } } }
      }
    }
  }
}
"""
V1_PR_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { remaining resetAt }
  search(query:$q, type:ISSUE, first:25, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title createdAt mergedAt closedAt merged
        additions deletions changedFiles
        author { login __typename }
        files(first:20) { nodes { path additions deletions } }
        reviews(first:20) { nodes { createdAt state body author { login __typename } } }
        comments(first:30) { nodes { createdAt body author { login __typename } } }
      }
    }
  }
}
"""

# The issue fields before linked pull requests carried their author and merged
# ones were fetched. Recorded issues lack those fields: an assignee with no
# login reads as taken, as it did then.
V1_ISSUE_FIELDS = """
fragment StarterFields on Issue {
  number title url createdAt updatedAt body locked
  author { login }
  repository { nameWithOwner isArchived }
  labels(first:15) { nodes { name } }
  assignees { totalCount }
  comments { totalCount }
  recent: comments(last:10) { nodes { createdAt body author { login } } }
  closedByPullRequestsReferences(first:5, includeClosedPrs:false) { nodes { state } }
  timelineItems(last:10, itemTypes:[CROSS_REFERENCED_EVENT, CONNECTED_EVENT]) {
    nodes {
      ... on CrossReferencedEvent { source { ... on PullRequest { state } } }
      ... on ConnectedEvent { subject { ... on PullRequest { state } } }
    }
  }
}
"""
V1_REPO_ISSUES = V1_ISSUE_FIELDS + """
query($owner:String!, $name:String!, $q:String!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    nameWithOwner isArchived
    issues(states:OPEN, first:40, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { ...StarterFields }
    }
  }
  labelled: search(query:$q, type:ISSUE, first:50) {
    nodes { ...StarterFields }
  }
}
"""


PR_SETTINGS = "    hasPullRequestsEnabled pullRequestCreationPolicy\n"


def as_recorded(document: str) -> str:
    from holt.evidence import github_graphql as gql

    v1 = {gql.REPO_META: V1_REPO_META, gql.PR_SEARCH: V1_PR_SEARCH,
          gql.PR_SEARCH_SCREEN: V1_PR_SEARCH, starter.REPO_ISSUES: V1_REPO_ISSUES}
    return v1.get(document) or document.replace(
        "rateLimit { cost remaining resetAt }", "rateLimit { remaining resetAt }"
    )


def replay_transport(name: str) -> tuple[starter.GitHub, datetime]:
    """A `starter.GitHub` whose HTTP calls are answered from a recording."""
    recording = json.loads((DATA / name).read_text(encoding="utf-8"))
    by_key = {c["key"]: c["response"] for c in recording["calls"]}

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        # Recorded before the issues query also asked search which are assigned.
        sent["variables"].pop("assigned", None)
        key = starter.query_key(sent["query"], sent["variables"])
        if key not in by_key:
            key = starter.query_key(as_recorded(sent["query"]), sent["variables"])
        if key not in by_key:
            # Recorded before engine 6 read the pull request settings and AI
            # policies, and engine 7 the stale bot's config.
            before = "\n".join(line for line in sent["query"].replace(PR_SETTINGS, "").split("\n")
                               if "ai_policy" not in line and "stale_" not in line
                               and "workflows:" not in line)
            key = starter.query_key(before, sent["variables"])
        if key not in by_key:
            key = starter.query_key(as_recorded(before), sent["variables"])
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
    ("good first task", "beginner"), ("good first feature", "beginner"),
    ("first-timers-only", "beginner"), ("Beginner Friendly", "beginner"),
    ("E-easy", "easy"), ("difficulty: easy", "easy"), ("help wanted", "help"),
    ("Hacktoberfest", "hacktoberfest"), ("wontfix", "not_ready"),
    ("question", "not_ready"), ("good first issue (taken)", "taken"),
    ("status: claimed", "taken"), ("In Progress", "taken"), ("has PR", "taken"),
    ("🚧 WIP", "taken"),
])
def test_label_variants(label, kind):
    assert kind in starter.label_kinds([label])


def test_unrelated_labels_mean_nothing():
    assert starter.label_kinds(["bug", "hacktoberfest-accepted", "area/cli",
                                "unassigned", "not taken"]) == set()


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
    issue(updated=starter.ACTIVE_DAYS + 1),
    issue(labels=("good first issue", "needs design")),
    issue(labels=(), title="Refactor the scheduler"),
    issue(archived=True),
    # Taken: React's label, and other ways maintainers say it.
    issue(labels=("good first issue (taken)",)),
    issue(labels=("good first issue", "status: in progress")),
    # Opened more than a year ago, however active since.
    issue(created=starter.MAX_ISSUE_AGE_DAYS + 1, updated=1),
])
def test_excluded(node):
    assert score(node) is None


def test_closed_unmerged_linked_prs_do_not_exclude():
    assert score(issue(closing=("CLOSED",), xref=("CLOSED",))) is not None


@pytest.mark.parametrize("node", [
    # nushell #19003: three merged PRs referenced it, one as its closing PR,
    # and the issue was still open and still served.
    issue(closing=("MERGED",)),
    issue(xref=("MERGED", "MERGED", "MERGED")),
])
def test_an_issue_with_a_merged_pull_request_is_solved(node):
    assert score(node) is None


def test_unlabelled_small_fix_qualifies():
    _, result = score(issue(labels=(), title="Typo in README", body="teh -> the"))
    assert result.why[0] == "Looks like a small fix (about typo)"


def test_unlabelled_long_issue_does_not_qualify():
    assert score(issue(labels=(), title="Docs are confusing", body="x" * 3000)) is None


def test_hacktoberfest_mode_weighs_the_label_more():
    node = issue(labels=("hacktoberfest",))
    assert score(node, hacktoberfest=True)[0] > score(node)[0]


def test_a_year_old_issue_is_still_listed():
    assert score(issue(created=starter.MAX_ISSUE_AGE_DAYS - 1)) is not None


@pytest.mark.parametrize("comment", [
    "Hi! Can I work on this?", "I'll take this one", "Please assign me",
    "I'm working on it, PR soon", "I would like to work on this issue",
    "I’ll pick this up",
])
def test_a_fresh_claim_puts_someone_on_it(comment):
    _, result = score(issue(recent=[(10, "Looks right to me", "a"), (3, comment, "b")]))
    assert (result.people, result.open_prs) == (1, 0)
    assert result.on_it == "1 person already on it"


def test_nobody_on_it():
    _, result = score(issue())
    assert (result.people, result.open_prs, result.on_it) == (0, 0, "Nobody on it yet")


def test_open_pull_requests_and_claims_count_distinct_people():
    node = issue(closing=(("OPEN", "ann"),), xref=(("OPEN", "ann"),),
                 recent=[(9, "can I work on this?", "cat"), (4, "assign me please", "cat"),
                         (2, "I'd like to take this", "ann")])
    _, result = score(node)
    assert (result.people, result.open_prs) == (2, 1)
    assert result.on_it == "2 people already on it, 1 open pull request"


def test_a_crowded_issue_is_not_listed():
    node = issue(recent=[(5, "can I work on this?", "a"), (4, "assign me", "b"),
                         (3, "I'd like to take this", "c")])
    assert score(node) is None


def test_one_open_pull_request_alone():
    _, result = score(issue(xref=("OPEN",)))
    assert result.on_it == "1 open pull request"


def test_a_pull_request_in_another_repository_is_not_work_on_this_issue():
    node = issue()
    node["timelineItems"]["nodes"].append({"source": {
        "state": "MERGED", "author": {"login": "x"},
        "repository": {"nameWithOwner": "someone/fork-tool"}}})
    assert score(node)[1].on_it == "Nobody on it yet"


def test_an_assignee_who_went_quiet_counts_but_does_not_hide_the_issue():
    _, result = score(issue(assigned=[("old", 120)]))
    assert result.people == 1


@pytest.mark.parametrize("node", [
    issue(assigned=[("new", 5)]),                                   # just assigned
    issue(assigned=[("old", 120)], recent=[(3, "on it, PR soon", "old")]),  # talking
    issue(assigned=[("old", 120)], xref=(("OPEN", "old"),)),        # has a PR up
])
def test_an_active_assignee_means_taken(node):
    assert score(node) is None


def test_nobody_on_it_ranks_first():
    busy = issue(1, labels=("good first issue", "easy"), xref=("OPEN",))
    free = issue(2, labels=("help wanted",))
    assert [i.number for _, i in starter.rank([busy, free], AS_OF)] == [2, 1]


def test_taking_another_look_is_not_a_claim():
    assert score(issue(recent=[(3, "I'll take another look in a few hours")])) is not None


def test_a_claim_handed_back_is_free_again():
    node = issue(recent=[(20, "can I take this?", "a"),
                         (5, "Sorry, I'm no longer working on this. Feel free to take it", "a")])
    assert score(node)[1].people == 0


def test_an_old_claim_is_a_caution_not_a_penalty():
    plain = score(issue())[0]
    points, result = score(issue(recent=[(200, "can i take this")]))
    assert points == plain
    assert result.why[-1] == ("Someone asked to work on this 200 days ago; ask whether "
                              "it is still free before you start")


def test_long_thread_is_a_caution_and_costs_points():
    plain = score(issue())[0]
    points, result = score(issue(comments=30))
    assert points < plain and "Long discussion (30 comments)" in result.why[-1]


# --- issue farms -------------------------------------------------------------


def test_near_identical_batch_from_one_account_is_dropped():
    langs = ["Japanese", "Korean", "Italian", "Spanish", "Hindi"]
    farm = [issue(10 + i, title=f"Add a {lang} idiom", author="farmer",
                  labels=("hacktoberfest",), created=5 + i * 3)
            for i, lang in enumerate(langs)]
    real = issue(1, title="Fix crash when the config file is empty")
    ranked = starter.rank([*farm, real], AS_OF)
    assert [i.number for _, i in ranked] == [1]
    assert starter.farmed_issues(farm) == {10, 11, 12, 13, 14}


def test_a_scripted_burst_from_one_account_is_dropped():
    titles = ["Unit tests download from the Hub", "unsloth loads on seven tasks",
              "add_new_tokens loads everywhere", "Windows tests still skip"]
    burst = [issue(20 + i, title=t, author="owner", created=2 + i / 86400 * 3)
             for i, t in enumerate(titles)]
    assert starter.farmed_issues(burst) == {20, 21, 22, 23}


@pytest.mark.parametrize("nodes", [
    # Three is a short series, not a farm.
    [issue(i, title=f"Add a {w} idiom", author="a") for i, w in enumerate("xyz")],
    # Similar titles from different people.
    [issue(i, title=f"Add a {w} idiom", author=f"u{i}") for i, w in enumerate("wxyz")],
    # One maintainer's distinct issues, days apart.
    [issue(i, title=t, author="m", created=10 + i) for i, t in enumerate(
        ["Fix crash in parser", "Document the CLI flags", "Typo in README",
         "Add type hints to utils"])],
    # No author known.
    [issue(i, title=f"Add a {w} idiom", author=None) for i, w in enumerate("wxyz")],
])
def test_farm_detection_leaves_ordinary_issues_alone(nodes):
    assert starter.farmed_issues(nodes) == set()


# holt-oss/holt: distinct starter issues one maintainer filed two seconds apart
# for Hacktoberfest, all dropped as a farm before.
HOLT_TITLES = ["Document `holt start`", "Hide `ctrl+t mode` when there is nothing to switch to",
               "`holt profile` writes broken TOML if a value contains a quote",
               "Recognise good first task labels", "Show examples in `holt start --help`"]


def _batch(**kw):
    return [issue(16 + i, title=t, author="aahil-khan", created=4 + i * 2 / 86400,
                  labels=("good first issue", "hacktoberfest"), **kw)
            for i, t in enumerate(HOLT_TITLES)]


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_a_maintainers_scripted_batch_is_kept(association):
    batch = _batch(association=association)
    assert starter.farmed_issues(batch) == set()
    ranked = starter.rank(batch, AS_OF)
    assert sorted(i.number for _, i in ranked) == [16, 17, 18, 19, 20]


def test_a_team_member_the_pull_requests_show_is_exempt_too():
    # A private org member reads CONTRIBUTOR on their own issues.
    batch = _batch(association="CONTRIBUTOR")
    assert starter.farmed_issues(batch) == {16, 17, 18, 19, 20}
    assert starter.farmed_issues(batch, team={"Aahil-Khan"}) == set()


def test_a_scripted_burst_from_someone_else_is_still_dropped():
    batch = [*_batch(association="CONTRIBUTOR"),
             issue(1, title="Fix crash when the config file is empty", association="OWNER")]
    assert [i.number for _, i in starter.rank(batch, AS_OF)] == [1]


def test_a_maintainers_templated_batch_is_still_dropped():
    farm = [issue(10 + i, title=f"Add a {lang} idiom", author="m", association="OWNER",
                  labels=("hacktoberfest",), created=5 + i * 3)
            for i, lang in enumerate(["Japanese", "Korean", "Italian", "Spanish"])]
    assert starter.farmed_issues(farm) == {10, 11, 12, 13}


def _one_repo(nodes, merged_by=(), recent=(), assigned=None):
    data = {"repository": {"nameWithOwner": "o/r", "isArchived": False,
                           "issues": {"nodes": list(recent)},
                           "mergers": {"nodes": [{"mergedBy": m} for m in merged_by]}},
            "labelled": {"nodes": nodes}}
    if assigned is not None:
        data["assigned"] = {"nodes": [{"number": n} for n in assigned]}
    return scripted([httpx.Response(200, json={"data": data})])


def test_an_issue_assigned_to_a_hidden_account_is_not_listed():
    # processing/p5.js#9176: assigned to an account GitHub hides, so the
    # issue's assignees read empty; only search still knows it is assigned.
    hidden = issue(9176, recent=[(12, "Thanks @someone, I'll assign this to you.", "m")])
    free = issue(2)
    transport = _one_repo([], recent=[hidden, free], assigned=[9176])
    issues = starter.starter_issues("o/r", None, as_of=AS_OF, transport=transport)
    assert [i.number for i in issues] == [2]


def test_starter_issues_keeps_a_maintainers_batch_end_to_end():
    transport = _one_repo(_batch(association="MEMBER"))
    issues = starter.starter_issues("o/r", None, as_of=AS_OF, transport=transport)
    assert sorted(i.number for i in issues) == [16, 17, 18, 19, 20]


def test_starter_issues_counts_whoever_merges_pull_requests_as_team():
    # Staging's token reads holt's private org owner as CONTRIBUTOR; they merge
    # every pull request, which needs write access.
    merged_by = [{"login": "aahil-khan", "__typename": "User"}, None]
    transport = _one_repo(_batch(association="CONTRIBUTOR"), merged_by)
    issues = starter.starter_issues("o/r", None, as_of=AS_OF, transport=transport)
    assert sorted(i.number for i in issues) == [16, 17, 18, 19, 20]


def test_a_bot_merging_pull_requests_is_not_team():
    merged_by = [{"login": "aahil-khan", "__typename": "Bot"}]
    transport = _one_repo(_batch(association="CONTRIBUTOR"), merged_by)
    assert starter.starter_issues("o/r", None, as_of=AS_OF, transport=transport) == []


LANDING = [Area("docs", 8, 10), Area("src/widgets", 4, 6), Area("src", 9, 20),
           Area("r", 5, 5), Area("tests", 1, 9)]


def test_landing_boost_for_a_named_area():
    points, result = score(issue(title="Fix wording in the docs"), landing=LANDING)
    assert points > score(issue(title="Fix wording in the docs"))[0]
    assert ("Mentions docs/, where 8 of 10 pull requests from outside "
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
    issues = starter.starter_issues("https://github.com/beetbox/beets", None,
                                    as_of=as_of, transport=transport)
    assert issues
    assert len({i.number for i in issues}) == len(issues)
    for i in issues:
        assert i.url.startswith("https://github.com/beetbox/beets/issues/")
        assert i.why
        assert set(i.as_dict()) == {"number", "title", "url", "labels", "created_at",
                                    "comments", "why", "people", "open_prs", "on_it"}
    # Everything listed is labelled for newcomers or a small unlabelled fix.
    assert all(starter.label_kinds(i.labels) or i.why[0].startswith("Looks like")
               for i in issues)


def test_missing_repository_is_not_found():
    transport = scripted([httpx.Response(200, json={
        "data": {"repository": None, "labelled": {"nodes": []}},
        "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]})])
    with pytest.raises(starter.RepoNotFound):
        starter.starter_issues("nobody/nothing", None, as_of=AS_OF, transport=transport)


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
    # Nothing opened over a year ago is asked for.
    assert all("created:>2025-09-25" in q for q in issue_qs)


@pytest.mark.parametrize("created,stars,skipped", [
    (30, 50, True),      # a month old, 50 stars: no track record yet
    (30, 5000, False),   # new but already big
    (400, 50, False),    # small but has been around
])
def test_brand_new_tiny_repos_are_not_sourced(created, stars, skipped):
    node = {"nameWithOwner": "o/r", "isArchived": False, "isFork": False,
            "stargazerCount": stars, "createdAt": iso(created),
            "goodFirstIssues": {"totalCount": 5}}
    issue_hit = {"number": 1, "repository": node}

    def handler(request):
        doc = json.loads(request.content)["query"]
        nodes = [issue_hit] if doc == starter.ISSUE_SOURCE else [node]
        return httpx.Response(200, json={"data": {"search": {"nodes": nodes}}})

    transport = starter.GitHub(token="t", client=httpx.Client(
        transport=httpx.MockTransport(handler)))
    got = starter.source_candidates(transport, ["python"], [], False, AS_OF, 10)
    assert got == ([] if skipped else ["o/r"])


# --- errors and recording --------------------------------------------------
# Retries and rate limits belong to the base transport and are tested with it
# (tests/test_github_transport.py). What starter adds is the recorder.


def test_starter_uses_the_engine_error_types():
    from holt.evidence import errors

    assert starter.RateLimited is errors.RateLimited
    assert starter.RepoNotFound is errors.RepoNotFound


def test_recorder_writes_replayable_answers():
    recorded: list[dict] = []
    ok = {"data": {"rateLimit": {"remaining": 10}, "x": 1}}
    transport = starter.GitHub(
        token="test", recorder=recorded,
        client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=ok))))
    assert transport.query("q", a=1)["x"] == 1
    (call,) = recorded
    assert call["key"] == starter.query_key("q", {"a": 1})
    assert call["response"]["data"]["x"] == 1
    assert "test" not in json.dumps(recorded)


def test_find_raises_rate_limit_when_nothing_was_found():
    class Limited(starter.GitHub):
        def __init__(self):
            pass

        def query(self, document, *, timeout=None, **variables):
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
    err = capsys.readouterr().err
    # The same message every command gives, with the link and the fix.
    from holt import credentials

    assert err.strip() == credentials.missing_token_message().strip()


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
    assert "4 of 10 recent pull requests from outside contributors" in out
    assert "https://github.com/o/r/issues/7" in out

    assert cli.main(["start", "--lang", "python", "--json"]) == 0
    raw = capsys.readouterr().out
    assert "“good first issue”" in raw  # non-ASCII text is not \\u-escaped
    body = json.loads(raw)
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
    assert cli.main(["start", "beetbox/beets", "--limit", "2"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("# Where to start in beetbox/beets")
    assert captured.out.count("https://github.com/beetbox/beets/issues/") == 2
    assert "listing issues only" in captured.err


# --- discover --record ------------------------------------------------------


@pytest.mark.parametrize("record", [None, "session"])
def test_discover_live_asks_for_recording_only_under_record(monkeypatch, tmp_path, record):
    """Trajectory recording is opt-in, so `--record` has to ask for it."""
    from holt.evidence import github_graphql

    cand = discover.Candidate(slug="o/r")
    survivor = discover.Screened(cand, Verdict.VIABLE, [], None, None)

    class Search:
        as_of, transport, queries, candidates = AS_OF, None, ["q"], [cand]

        def screen(self):
            yield discover.ScreenedStep(1, 1, cand, result=survivor)

    class Provider:
        def __init__(self, *a, **kw):
            pass

        def fetch(self, slug):
            return []

    asked = {}

    def fake_client(path=None, record=None):
        asked["record"] = record
        raise RuntimeError("stop here")

    monkeypatch.setattr(discover, "DISCOVER_ROOT", tmp_path)
    monkeypatch.setattr(discover, "source_live", lambda *a, **kw: Search())
    monkeypatch.setattr(discover, "write_fixture", lambda *a, **kw: None)
    monkeypatch.setattr(github_graphql, "LiveGitHubProvider", Provider)
    monkeypatch.setattr(model, "live_client", fake_client)
    with pytest.raises(RuntimeError, match="stop here"):
        discover.run_live(Profile(languages=["go"]), record=record)
    assert asked["record"] is bool(record)


def test_discover_table_shows_headlines_not_enum_values():
    row = discover.SurvivorRow(slug="o/r", verdict="not_viable", landed="0/3",
                               reply="never", why="w", notes=[])
    screened = [discover.Screened(discover.Candidate(slug="o/r"), Verdict.NOT_VIABLE,
                                  [], None, None)]
    out = discover.render(Profile(languages=["go"]), ["q"], screened, [row],
                          replayed=False, as_of=AS_OF, skipped=[], unanalysed=0)
    assert "| Not worth your time |" in out
    assert "not_viable" not in out


def test_beginner_issue_means_a_first_timer_label():
    assert starter.is_beginner_issue(["Good First Issue"])
    assert starter.is_beginner_issue(["first-timers-only"])
    assert not starter.is_beginner_issue(["help wanted"])
    assert not starter.is_beginner_issue([])


def test_issue_areas_from_labels_and_title():
    assert starter.issue_areas(["documentation"], "Clarify install steps") == ["docs"]
    assert starter.issue_areas([], "Fix typo in README") == ["docs"]
    assert starter.issue_areas(["area: testing"], "x") == ["tests"]
    assert starter.issue_areas(["UI/UX"], "Button overlaps") == ["design"]
    assert starter.issue_areas(["i18n"], "Add German") == ["translations"]
    assert starter.issue_areas([], "Crash on empty config") == ["code"]
    # A bug label makes it code as well as whatever else it touches.
    assert starter.issue_areas(["bug", "docs"], "x") == ["code", "docs"]
    # A language label is not a translation.
    assert starter.issue_areas(["language: python"], "x") == ["code"]


# --- what a beginner can actually do --------------------------------------


@pytest.mark.parametrize("node", [
    issue(title="Looking for co-maintainers"),           # spotatui #340
    issue(title="Seeking new maintainers for the Windows port"),
    issue(title="Tracking issue for the 2.0 migration"),
    issue(title="[META] Improve error messages"),
    issue(title="Epic: plugin system"),
    issue(title="Roadmap 2026"),
    issue(title="Co-maintainers wanted"),
    issue(labels=("good first issue", "meta")),
    issue(labels=("good first issue", "Type: Tracking")),
    issue(labels=("help wanted", "epic")),
])
def test_non_tasks_are_dropped(node):
    assert score(node) is None


@pytest.mark.parametrize("title,caution", [
    ("Pinyin IME drops characters on Windows 11", "Needs Windows"),
    ("Windows: paths with spaces break the installer", "Needs Windows"),
    ("Crash when launched from Xcode on macOS", "Needs a Mac"),
    ("S3 object tagging is ignored for backups", "Needs a cloud account"),
    ("CUDA out of memory with batch size 1", "Needs a GPU"),
    ("Bluetooth firmware update hangs", "Needs special hardware"),
    ("Sonos integration", "Needs special hardware"),
    ("Regression in ambient declaration emit", "Deep compiler work"),
    ("Pods restart in a kubernetes cluster with sidecars", "Needs a Kubernetes cluster"),
])
def test_special_setup_is_named_and_ranked_down(title, caution):
    plain = score(issue(title="Error message is unclear"))[0]
    points, result = score(issue(title=title))
    assert caution in result.why
    assert points < plain


def test_setup_the_whole_repository_is_about_is_not_special():
    # In a Kubernetes project every issue needs a cluster; that says nothing.
    _, result = score(issue(title="Pods restart in a kubernetes cluster",
                            repo="kubernetes/kubernetes"))
    assert "Needs a Kubernetes cluster" not in result.why


@pytest.mark.parametrize("title", ["Closing all windows leaves the tray icon",
                                   "Windows are not resizable after a restart"])
def test_a_windows_in_a_gui_is_not_the_os(title):
    _, result = score(issue(title=title))
    assert "Needs Windows" not in result.why


@pytest.mark.parametrize("title", ["Contributing guide needed for maintainers",
                                   "Update the roadmap link in the README"])
def test_tasks_that_mention_maintainers_or_a_roadmap_are_still_tasks(title):
    assert score(issue(title=title)) is not None


def test_labels_name_setup_too():
    _, result = score(issue(labels=("good first issue", "platform: windows")))
    assert "Needs Windows" in result.why


def test_harder_labels_cost_points():
    plain = score(issue())[0]
    points, result = score(issue(labels=("good first issue", "difficulty: hard")))
    assert points < plain
    assert "Marked as harder (“difficulty: hard”)" in result.why


@pytest.mark.parametrize("title,line", [
    ("Document the --verbose flag", "Docs work"),
    ("Add unit tests for the parser", "Tests work"),
])
def test_docs_and_tests_work_ranks_up(title, line):
    points, result = score(issue(title=title))
    assert line in result.why
    assert points > score(issue(title="Fix crash in the parser"))[0]


def test_a_freshly_opened_issue_ranks_up():
    points, result = score(issue(created=5, updated=5))
    assert "Opened 5 days ago" in result.why
    assert points > score(issue(created=200, updated=5))[0]


def test_the_cli_shows_who_is_on_each_issue():
    free = score(issue(1))[1]
    busy = score(issue(2, xref=("OPEN",)))[1]
    text = starter.render_repo("o/r", [free, busy])
    assert "  Nobody on it yet\n" in text and "  1 open pull request\n" in text
