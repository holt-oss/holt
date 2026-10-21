"""Discover and the repo boards: rules verdicts only, repos only, the
repository details the warm pass reads, and the trending threshold."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import STATS, canned_report
from holt_server import discover, github, warm
from holt_server.db import RepoMeta, Report, StarterCache, Usage, now
from holt_server.discover import standouts
from holt_server.errors import ApiError
from holt_server.schema import WELCOMING_LINE, Stats


def add(h, *items):
    async def go():
        async with h.svc.db.session() as s:
            s.add_all(items)
            await s.commit()
    h.client.portal.call(go)


def report(repo, verdict="viable", mode="rules", **stats):
    body = canned_report(repo, mode, 7, verdict)
    body["stats"] = {**STATS, **stats}
    return Report(repo=repo, repo_key=repo.lower(), mode=mode, days=7, report=body)


def meta(repo, language=None, stars=0, topics=(), **kw):
    return RepoMeta(repo_key=repo.lower(), repo=repo, language=language, stars=stars,
                    topics=list(topics), **kw)


def views(repo, people, day_offset=0):
    day = (now() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    return [Usage(day=day, kind="analysis", who=f"p{i}", repo_key=repo.lower())
            for i in range(people)]


def get(h, **params):
    r = h.get("/v1/discover", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def names(body):
    return [r["repo"] for r in body["repos"]]


def test_needs_the_internal_key(h):
    assert h.client.get("/v1/discover").status_code == 401


def test_welcoming_board_is_only_worth_your_time_best_odds_first(h):
    add(h,
        report("octo/great", outsider_merged=12, no_reply=1),        # good odds
        report("octo/good", outsider_merged=10, no_reply=2),         # good, fewer merged
        report("octo/fair", outsider_merged=2, no_reply=2),          # 10% merged: fair
        report("octo/closed", "not_viable", outsider_merged=0),
        report("octo/unsure", "insufficient_evidence"),
        meta("octo/great", "Python"), meta("octo/good", "Python"), meta("octo/fair", "Go"))
    body = get(h)
    assert body["sort"] == "welcoming"
    assert names(body) == ["octo/great", "octo/good", "octo/fair"]
    card = body["repos"][0]
    assert card["headline"] == "Worth your time" and card["tone"] == "good"
    assert card["reason"].startswith("Outside contributors get real replies here")
    assert card["stats"]["median_first_response_hours"] == 3.0
    assert card["checked_this_week"] is None


def test_personal_projects_are_never_listed_and_long_shots_are_not_welcoming(h):
    add(h, report("octo/great", outsider_merged=12, no_reply=1),
        report("octo/mine", "personal", outsider_attempts=0, outsider_merged=0),
        report("octo/far", "long_shot", outsider_merged=3, no_reply=12),
        meta("octo/great", "Python", stars=10), meta("octo/mine", "Python", stars=5),
        meta("octo/far", "Python", stars=1000))
    assert names(get(h)) == ["octo/great"]
    assert names(get(h, sort="stars")) == ["octo/far", "octo/great"]


def test_equal_odds_break_ties_by_reply_time_then_sample(h):
    add(h, report("octo/slow", median_first_response_hours=40.0),
        report("octo/quick", median_first_response_hours=2.0),
        report("octo/quick-more", median_first_response_hours=2.0, outsider_attempts=40,
               outsider_merged=16, no_reply=4))
    assert names(get(h)) == ["octo/quick-more", "octo/quick", "octo/slow"]


def test_a_small_lucky_sample_does_not_top_the_board(h):
    add(h, report("octo/lucky", outsider_attempts=8, outsider_merged=6, no_reply=0),
        report("octo/proven", outsider_attempts=105, outsider_merged=60, no_reply=20))
    assert names(get(h)) == ["octo/proven", "octo/lucky"]


def test_card_reason_does_not_point_at_starter_issues(h):
    add(h, report("octo/busy", outsider_attempts=100, outsider_merged=6, no_reply=55))
    reason = get(h)["repos"][0]["reason"]
    assert reason.startswith("Outside contributors do get merged here, but")
    assert "below" not in reason and reason.endswith("choose your first change carefully.")


def test_a_welcoming_card_leads_with_the_number_it_ranks_best_on(h):
    add(h,
        report("octo/quick", outsider_merged=8, median_first_response_hours=1.0),
        report("octo/second", outsider_merged=19, median_first_response_hours=30.0),
        report("octo/newcomers", outsider_merged=8, median_first_response_hours=40.0,
               first_time_merged_authors=9),
        report("octo/plain", outsider_merged=8, median_first_response_hours=50.0))
    lines = {c["repo"]: c["standout"] for c in get(h)["repos"]}
    assert lines == {
        "octo/quick": "A first reply typically comes within an hour.",
        # The share merged is the card's bar, never its line.
        "octo/second": "A first reply typically comes within 2 days.",
        "octo/newcomers": "9 people got their first pull request merged here.",
        # Last on every number: reply time, the first one, is what it says.
        "octo/plain": "A first reply typically comes within 3 days.",
    }


def test_merge_speed_and_the_last_merge_can_lead_a_card():
    def stats(**timing):
        return Stats.model_validate({**STATS, "timing": timing})
    cards = [(WELCOMING_LINE, s) for s in (
        stats(merge_typical_days=0.5, last_outside_merge="2026-09-01"),
        stats(merge_typical_days=9, last_outside_merge="2026-10-08"),
        stats(merge_typical_days=9, last_outside_merge="2026-09-01"))]
    assert standouts(cards) == [
        "Merges typically land within 12 hours.",
        "The last outside pull request was merged on 8 Oct 2026.",
        # Nothing of its own: every number is shared or the worst here.
        "A first reply typically comes within 3 hours.",
    ]


def test_a_reason_that_already_says_something_keeps_its_card(h):
    add(h, report("octo/silent", outsider_merged=10, no_reply=10),   # "…but about half get no reply…"
        report("octo/closed", "not_viable", outsider_merged=0))
    for sort in ("welcoming", "stars"):
        assert [c["standout"] for c in get(h, sort=sort)["repos"]] == [None] * (1 + (sort == "stars"))
    no_numbers = Stats.model_validate({**STATS, "median_first_response_hours": None,
                                       "outsider_attempts": 0, "outsider_merged": 0,
                                       "first_time_merged_authors": 0})
    assert standouts([(WELCOMING_LINE, no_numbers)]) == [None]


def issue(number, people=0):
    return {"number": number, "title": f"Fix {number}", "url": f"https://github.com/o/r/issues/{number}",
            "labels": ["good first issue"], "created_at": None, "comments": 0, "why": [],
            "people": people, "open_prs": 0}


def starters(repo, *issues, age_hours=0):
    return StarterCache(repo_key=repo.lower(), repo=repo, issues=list(issues),
                        created_at=now() - timedelta(hours=age_hours))


def test_cards_carry_cached_starter_issues_nobody_on_first(h):
    add(h, report("octo/one"), report("octo/stale"), report("octo/none"),
        starters("octo/one", issue(1, people=2), issue(2), issue(3)),
        starters("octo/stale", issue(9), age_hours=discover.STARTER_MAX_HOURS + 1))
    cards = {c["repo"]: c for c in get(h)["repos"]}
    assert [i["number"] for i in cards["octo/one"]["issues"]] == [2, 3, 1]
    assert cards["octo/one"]["issues"][0]["on_it"] == "Nobody on it yet"
    assert cards["octo/stale"]["issues"] == [] and cards["octo/none"]["issues"] == []


def test_a_card_carries_at_most_a_handful_of_issues(h):
    add(h, report("octo/many"),
        starters("octo/many", *(issue(n) for n in range(1, discover.CARD_ISSUES + 4))))
    assert len(get(h)["repos"][0]["issues"]) == discover.CARD_ISSUES


def test_only_rules_reports_and_the_newest_one_count(h):
    add(h, report("octo/ai-only", mode="ai"),
        report("octo/changed", "viable"))
    add(h, report("octo/changed", "not_viable"))  # newer: it stopped being welcoming
    assert names(get(h)) == []
    assert names(get(h, sort="stars")) == ["octo/changed"]
    assert get(h, sort="stars")["repos"][0]["verdict"] == "not_viable"


def test_stars_shows_every_verdict_and_repos_without_details_last(h):
    add(h, report("octo/big", "not_viable"), report("octo/small"), report("octo/unread"),
        meta("octo/big", "Rust", stars=90_000), meta("octo/small", "Rust", stars=40))
    body = get(h, sort="stars")
    assert names(body) == ["octo/big", "octo/small", "octo/unread"]
    unread = body["repos"][2]
    assert unread["stars"] is None and unread["language"] is None and unread["topics"] == []


def test_language_and_topic_filters_ignore_case(h):
    add(h, report("octo/py-cli"), report("octo/py-web"), report("octo/cpp"),
        meta("octo/py-cli", "Python", topics=["cli", "Hacktoberfest"]),
        meta("octo/py-web", "Python", topics=["web"]), meta("octo/cpp", "C++"))
    body = get(h, language="PYTHON")
    assert body["language"] == "Python"  # GitHub's spelling back
    assert sorted(names(body)) == ["octo/py-cli", "octo/py-web"]
    assert names(get(h, language="python", topic="hacktoberfest")) == ["octo/py-cli"]
    assert names(get(h, language="c++")) == ["octo/cpp"]
    assert names(get(h, language="haskell")) == []
    # The language chips don't depend on the filter in use.
    assert get(h, language="c++")["languages"] == [{"name": "Python", "repos": 2},
                                                   {"name": "C++", "repos": 1}]


def test_a_big_second_language_is_named_beside_the_primary_one():
    # microsoft/TypeScript: GitHub's primary language is Go since the compiler port.
    def node(primary, *sizes):
        return {"primaryLanguage": {"name": primary}, "languages": {
            "totalSize": sum(n for _, n in sizes),
            "edges": [{"size": n, "node": {"name": name}} for name, n in sizes]}}

    assert github.main_languages(node("Go", ("Go", 25_086_869), ("TypeScript", 3_606_966),
                                      ("JavaScript", 116_132))) == ["Go", "TypeScript"]
    assert github.main_languages(node("Python", ("Python", 95), ("HTML", 5))) == ["Python"]
    assert github.main_languages({"primaryLanguage": None}) == []
    assert github._details({"nameWithOwner": "a/b", **node("Go", ("Go", 8), ("C", 2))})[
        "languages"] == ["Go", "C"]


def test_cards_carry_the_main_languages(h):
    add(h, report("microsoft/TypeScript"),
        meta("microsoft/TypeScript", "Go", languages=["Go", "TypeScript"]))
    card = get(h)["repos"][0]
    assert (card["language"], card["languages"]) == ("Go", ["Go", "TypeScript"])


def test_trending_needs_enough_people_this_week(h, monkeypatch):
    monkeypatch.setattr(discover, "VIEWS_KEPT_S", 0)  # count on every request
    add(h, report("octo/hot"), report("octo/warm"), report("octo/quiet"),
        report("octo/last-month"),
        *views("octo/hot", 9), *views("octo/warm", 3), *views("octo/warm", 3, day_offset=2),
        *views("octo/quiet", discover.TRENDING_MIN - 1),
        *views("octo/last-month", 20, day_offset=10))
    body = get(h, sort="trending")
    assert body["trending_min"] == discover.TRENDING_MIN
    assert names(body) == ["octo/hot", "octo/warm"]
    assert [r["checked_this_week"] for r in body["repos"]] == [9, 6]
    # The same person on the same day counts once.
    add(h, *views("octo/quiet", 1))
    assert "octo/quiet" not in names(get(h, sort="trending"))
    # Below the threshold the count isn't shown on any board either.
    quiet = next(r for r in get(h, sort="stars")["repos"] if r["repo"] == "octo/quiet")
    assert quiet["checked_this_week"] is None


def test_trending_counts_people_asking_for_a_report(h):
    add(h, report("octo/one"))
    for i in range(discover.TRENDING_MIN):
        assert h.post("/v1/analyses", {"repo": "octo/one"}, ip=f"10.0.0.{i + 2}").status_code == 200
    assert names(get(h, sort="trending")) == ["octo/one"]


def test_limit_and_bad_sort(h):
    add(h, *(report(f"octo/r{i}") for i in range(5)))
    assert len(get(h, limit=2)["repos"]) == 2
    assert h.get("/v1/discover", params={"sort": "people"}).status_code == 400


# --- a board in parts -------------------------------------------------------------


def parts(h, limit, **params):
    """Every part of a board, following `next` to the end."""
    out, cursor = [], None
    while True:
        body = get(h, limit=limit, **params, **({"cursor": cursor} if cursor else {}))
        out.append(body)
        cursor = body["next"]
        if cursor is None:
            return out


def test_a_board_comes_in_parts_in_order_with_no_repeats_until_the_end(h):
    add(h, *(report(f"octo/r{i}") for i in range(7)),
        *(meta(f"octo/r{i}", "Python", stars=i) for i in range(7)))
    whole = names(get(h, sort="stars", limit=100))
    assert whole == [f"octo/r{i}" for i in range(6, -1, -1)]
    got = parts(h, 3, sort="stars")
    assert [len(b["repos"]) for b in got] == [3, 3, 1]
    assert [n for b in got for n in names(b)] == whole
    assert {b["total"] for b in got} == {7}
    assert got[-1]["next"] is None and all(b["next"] for b in got[:-1])
    # Each part carries what the first does: the filters and the language chips.
    assert {b["languages"][0]["repos"] for b in got} == {7}


def test_parts_keep_their_filter_and_a_board_that_fits_has_no_next(h):
    add(h, *(report(f"octo/py{i}") for i in range(3)), report("octo/go"),
        *(meta(f"octo/py{i}", "Python", stars=i) for i in range(3)), meta("octo/go", "Go", stars=9))
    got = parts(h, 2, sort="stars", language="python")
    assert [names(b) for b in got] == [["octo/py2", "octo/py1"], ["octo/py0"]]
    assert got[0]["total"] == 3
    exact = get(h, sort="stars", language="python", limit=3)
    assert exact["next"] is None and exact["total"] == 3
    empty = get(h, sort="stars", language="rust")
    assert (empty["repos"], empty["total"], empty["next"]) == ([], 0, None)


def test_the_next_part_follows_the_last_repo_when_the_board_changed(h):
    add(h, *(report(f"octo/r{i}") for i in range(4)),
        *(meta(f"octo/r{i}", stars=10 * (i + 1)) for i in range(4)))
    first = get(h, sort="stars", limit=2)
    assert names(first) == ["octo/r3", "octo/r2"]
    # A repo joins above what was read: the rest still starts after octo/r2.
    add(h, report("octo/new"), meta("octo/new", stars=99))
    second = get(h, sort="stars", limit=2, cursor=first["next"])
    assert names(second) == ["octo/r1", "octo/r0"]
    assert second["total"] == 5 and second["next"] is None


def test_a_cursor_whose_repo_left_the_board_carries_on_from_its_place(h):
    add(h, *(report(f"octo/r{i}") for i in range(4)),
        *(meta(f"octo/r{i}", stars=10 * (i + 1)) for i in range(4)))
    cursor = discover.cursor_for(2, "octo/gone")
    assert names(get(h, sort="stars", limit=2, cursor=cursor)) == ["octo/r1", "octo/r0"]
    past = discover.cursor_for(40, "octo/gone")
    assert get(h, sort="stars", cursor=past)["repos"] == []


@pytest.mark.parametrize("cursor", ["nope", "!!", "Og", "eDp5"])  # the last two: ":", "x:y"
def test_a_cursor_discover_did_not_give_out_is_refused(h, cursor):
    r = h.get("/v1/discover", params={"cursor": cursor})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_a_part_slices_the_kept_board_instead_of_ranking_again(h, monkeypatch):
    add(h, *(report(f"octo/r{i}") for i in range(5)))
    ranked = []
    rank = discover.rank
    monkeypatch.setattr(discover, "rank", lambda cards, sort: ranked.append(sort) or rank(cards, sort))
    assert len(parts(h, 2)) == 3
    assert ranked == ["welcoming"]
    kept = discover.boards(h.svc)
    assert (kept.misses, kept.hits, len(kept)) == (1, 2, 1)


# --- the Hacktoberfest filter -----------------------------------------------------


def hacktoberfest_repos(h):
    add(h,
        report("octo/hf-great", outsider_merged=12, no_reply=1),
        report("octo/hf-fair", outsider_merged=2, no_reply=2),
        report("octo/hf-closed", "not_viable", outsider_merged=0),
        report("octo/hf-unsure", "insufficient_evidence"),
        report("octo/hf-archived", outsider_merged=12, no_reply=1),
        report("octo/plain", outsider_merged=12, no_reply=1),
        report("octo/unread"),
        meta("octo/hf-great", "Python", stars=50, topics=["cli", "hacktoberfest"]),
        meta("octo/hf-fair", "Go", stars=900, topics=["HacktoberFest"]),
        meta("octo/hf-closed", "Python", stars=5000, topics=["hacktoberfest"]),
        meta("octo/hf-unsure", "Rust", stars=10, topics=["hacktoberfest"]),
        meta("octo/hf-archived", "Python", stars=1, topics=["hacktoberfest"], archived=True),
        meta("octo/plain", "Python", stars=70_000, topics=["cli"]))


def test_hacktoberfest_lists_repos_tagged_for_it_worth_your_time_best_first(h):
    hacktoberfest_repos(h)
    body = get(h, hacktoberfest="true")
    assert body["hacktoberfest"] is True
    # The welcoming board: only "Worth your time", best odds first. An
    # archived repo can't take pull requests, so it isn't listed.
    assert names(body) == ["octo/hf-great", "octo/hf-fair"]
    assert body["repos"][0]["headline"] == "Worth your time"
    # Every verdict when sorted by stars; untagged and unread repos never.
    assert names(get(h, hacktoberfest="1", sort="stars")) == [
        "octo/hf-closed", "octo/hf-fair", "octo/hf-great", "octo/hf-unsure"]
    # It is off unless asked for.
    assert get(h)["hacktoberfest"] is False
    assert "octo/plain" in names(get(h))


def test_hacktoberfest_combines_with_language_and_scopes_the_chips(h):
    hacktoberfest_repos(h)
    body = get(h, hacktoberfest="true", language="python", sort="stars")
    assert names(body) == ["octo/hf-closed", "octo/hf-great"]
    # The chips count Hacktoberfest repos only, so none leads to an empty list.
    assert body["languages"] == [{"name": "Python", "repos": 2}, {"name": "Go", "repos": 1},
                                 {"name": "Rust", "repos": 1}]


def test_hacktoberfest_when_none_are_tagged(h):
    add(h, report("octo/plain"), meta("octo/plain", "Python", topics=["cli"]))
    body = get(h, hacktoberfest="true")
    assert body["repos"] == [] and body["languages"] == [] and body["hacktoberfest"] is True


def test_hacktoberfest_reads_only_the_database(h):
    hacktoberfest_repos(h)

    def no_github(*a, **kw):
        raise AssertionError("Discover must not call GitHub")

    async def no_github_async(*a, **kw):
        no_github()

    h.svc.pool.transport = no_github
    h.svc.canonical = no_github_async
    h.svc.lookup.repo = no_github_async
    h.svc.lookup.details = no_github_async
    h.svc.provider_factory = no_github
    for sort in ("welcoming", "stars", "trending"):
        get(h, hacktoberfest="true", sort=sort)
    assert h.engine.calls == []


# --- repository details, filled by the warm pass ---------------------------------


def details(repo, **kw):
    return {"repo": repo, "description": "A thing", "language": "Python", "stars": 10,
            "topics": ["cli"], "pushed_at": "2026-09-20T10:00:00Z", "archived": False,
            "fork": False, **kw}


def test_warm_pass_reads_details_of_reported_repos_once_a_day(h):
    fake = h.svc.lookup.details
    fake.known = {"octo/one": details("octo/one", stars=321), "octo/two": details("Octo/Two")}
    add(h, report("octo/one"), report("octo/two"), report("octo/gone"))
    h.svc.lookup.remaining = _plenty
    result = _run(h, ["octo/three"], reports=False, starter=False, finds=False)
    assert result.meta_run == 2 and result.stopped is None
    assert len(fake.calls) == 1  # one query for all of them
    assert sorted(fake.calls[0]) == ["octo/gone", "octo/one", "octo/three", "octo/two"]
    body = get(h, sort="stars")
    assert names(body)[:2] == ["octo/one", "Octo/Two"]
    assert body["repos"][0]["stars"] == 321 and body["repos"][0]["topics"] == ["cli"]
    assert body["repos"][0]["pushed_at"] == "2026-09-20T10:00:00Z"

    again = _run(h, [], reports=False, starter=False, finds=False)
    assert again.meta_run == 0
    assert fake.calls[1:] == [["octo/gone"]]  # only the one GitHub didn't know


def test_details_are_read_ten_at_a_time():
    items = [f"o/r{i}" for i in range(25)]
    assert [len(b) for b in discover.batches(items)] == [10, 10, 5] == [
        github.DETAILS_BATCH, github.DETAILS_BATCH, 5]


def test_details_rate_limit_stops_the_pass(h):
    h.svc.lookup.details.error = ApiError("rate_limited", "slow down", retry_after=60)
    h.svc.lookup.remaining = _plenty
    add(h, report("octo/one"))
    result = _run(h, [], reports=False, starter=False, finds=True)
    assert result.stopped == "GitHub rate limit reached" and result.finds_run == 0


def test_dry_run_reads_no_details(h):
    add(h, report("octo/one"))
    lines = []
    _run(h, [], dry_run=True, say=lines.append, reports=False, starter=False, finds=False)
    assert h.svc.lookup.details.calls == []
    assert "would read details of 1 repos in 1 query" in lines


async def _plenty():
    return 5000


def _run(h, seeds, **kw):
    return h.client.portal.call(lambda: warm.warm_once(h.svc, seeds=seeds, **kw))


class FakeTransport:
    def __init__(self, answer):
        self.answer = answer
        self.sent: list[tuple[str, dict]] = []

    def query(self, document, timeout=None, **variables):
        self.sent.append((document, variables))
        return self.answer(variables)


def lookup_with(answer):
    pool = github.TokenPool(["tok"])
    transport = FakeTransport(answer)
    pool.transport = lambda http=None, index=None: transport
    return github.GitHubLookup(pool, http=None), transport


def test_details_query_is_one_request_with_one_alias_per_repo():
    node = {"nameWithOwner": "Pallets/Flask", "description": " :books: Web ", "stargazerCount": 7,
            "pushedAt": "2026-09-01T00:00:00Z", "isArchived": False, "isFork": False,
            "isPrivate": False, "primaryLanguage": {"name": "Python"},
            "repositoryTopics": {"nodes": [{"topic": {"name": "wsgi"}}, {"topic": None}]}}
    lookup, transport = lookup_with(lambda v: {"r0": node, "r1": None,
                                               "r2": {**node, "isPrivate": True}})
    out = lookup._details(["pallets/flask", "octo/gone", "octo/secret"])
    document, variables = transport.sent[0]
    assert len(transport.sent) == 1
    assert variables == {"o0": "pallets", "n0": "flask", "o1": "octo", "n1": "gone",
                         "o2": "octo", "n2": "secret"}
    assert "r2: repository(owner:$o2, name:$n2)" in document and "rateLimit" in document
    assert out["pallets/flask"] == {
        "repo": "Pallets/Flask", "description": "Web", "language": "Python",
        "languages": ["Python"], "stars": 7,
        "topics": ["wsgi"], "pushed_at": "2026-09-01T00:00:00Z", "archived": False,
        "fork": False, "forks": None, "open_issues": None, "pull_requests": None,
        "open_pull_requests": None, "contributors": None, "license": None,
        "homepage": None, "language_shares": [], "created_at": None, "default_branch": None,
        "fork_of": None, "readme_line": None, "links": [], "latest_release": None, "readme": None}
    assert out["octo/gone"] is None and out["octo/secret"] is None


def test_details_when_every_repo_is_gone_or_unanswered():
    from holt.evidence.errors import RepoNotFound, UpstreamError

    def gone(v):
        raise RepoNotFound("octo/gone")

    lookup, _ = lookup_with(gone)
    assert lookup._details(["octo/gone"]) == {"octo/gone": None}

    def broken(v):
        raise UpstreamError("HTTP 502")

    # One GitHub can't answer for, even alone, is left out: not missing, not read.
    lookup, transport = lookup_with(broken)
    assert lookup._details(["octo/one", "octo/two"]) == {}
    assert [v for _, v in transport.sent] == [
        {"o0": "octo", "n0": "one", "o1": "octo", "n1": "two"},
        {"o0": "octo", "n0": "one"}, {"o0": "octo", "n0": "two"}]
    with pytest.raises(ValueError):
        lookup._details([f"o/r{i}" for i in range(github.DETAILS_BATCH + 1)])


def test_every_topic_is_read_so_a_late_hacktoberfest_tag_counts(h):
    # GitHub allows 20 topics; the Hacktoberfest one is often added last.
    assert "repositoryTopics(first: 20)" in github.DETAILS_FIELDS
    topics = [f"t{i}" for i in range(19)] + ["hacktoberfest"]
    h.svc.lookup.details.known = {"octo/one": details("octo/one", topics=topics)}
    h.svc.lookup.remaining = _plenty
    add(h, report("octo/one"))
    _run(h, [], reports=False, starter=False, finds=False)
    assert names(get(h, hacktoberfest="true")) == ["octo/one"]
