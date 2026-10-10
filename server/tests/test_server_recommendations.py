"""Recommendations for you: rules only, "Worth your time" repos with maintainers
still answering, matched to the profile and to merged pull requests, never a
repo the user is already in, with reasons, and free for everyone. A new
account, with nothing to match on, gets the popular languages."""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import STATS, canned_report
from holt.starter import RULES_VERSION
from holt_server import recommendations
from holt_server.db import (
    ENGINE_VERSION,
    Contribution,
    FindCache,
    GitHubConnection,
    Profile,
    RepoMeta,
    Report,
    StarterCache,
    now,
)

URL = "/v1/me/recommendations"


@pytest.fixture
def h(make_harness):
    return make_harness()


def add(h, *items):
    async def go():
        async with h.svc.db.session() as s:
            s.add_all(items)
            await s.commit()
    h.client.portal.call(go)


def report(repo, verdict="viable", age_days=0, **stats):
    body = canned_report(repo, "rules", 7, verdict)
    body["stats"] = {**STATS, **stats}
    return Report(repo=repo, repo_key=repo.lower(), mode="rules", days=7, report=body,
                  created_at=now() - timedelta(days=age_days))


def meta(repo, language=None, topics=(), **kw):
    return RepoMeta(repo_key=repo.lower(), repo=repo, language=language, stars=kw.pop("stars", 10),
                    topics=list(topics), **kw)


def profile(user="u1", languages=("python",), topics=(), level="newcomer", contributions=()):
    return Profile(user_id=user, languages=list(languages), topics=list(topics), days=7,
                   level=level, contributions=list(contributions))


def connection(user="u1", login="octocat"):
    return GitHubConnection(user_id=user, github_id=583231, login=login,
                            adult_confirmed_at=now())


def pr(repo, number=1, state="merged", user="u1"):
    return Contribution(user_id=user, repo_key=repo.lower(), number=number, repo=repo,
                        title="t", url=f"https://github.com/{repo}/pull/{number}",
                        state=state, created_at=now())


def issue(number, labels=("good first issue",), title="Fix a thing", people=0):
    return {"number": number, "title": title, "url": f"https://github.com/o/r/issues/{number}",
            "labels": list(labels), "created_at": None, "comments": 0, "why": [],
            "people": people, "open_prs": 0}


def starters(repo, *issues, age_hours=0):
    return StarterCache(repo_key=repo.lower(), repo=repo, issues=list(issues),
                        created_at=now() - timedelta(hours=age_hours))


def get(h, user="u1", **params):
    r = h.get(URL, user=user, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def names(body):
    return [p["repo"] for p in body["picks"]]


def test_signed_in_only(h):
    assert h.get(URL).status_code == 401
    assert h.client.get(URL, headers={"X-Holt-User": "u1"}).status_code == 401


def test_a_new_account_gets_popular_languages_spread_out(h):
    add(h, report("octo/py1", outsider_merged=20), meta("octo/py1", "Python"),
        report("octo/py2", outsider_merged=15), meta("octo/py2", "Python"),
        report("octo/go", outsider_merged=10), meta("octo/go", "Go"),
        report("octo/nix"), meta("octo/nix", "Nix"),
        report("octo/none"), meta("octo/none"),
        report("octo/dead", "not_viable"), meta("octo/dead", "Python"))
    body = get(h)
    # The best of each language first; nothing outside the popular ones.
    assert names(body) == ["octo/py1", "octo/go", "octo/py2"]
    b = body["basis"]
    assert b["has_profile"] is False and b["connected"] is False
    assert b["languages"] == b["topics"] == b["history_languages"] == []
    # No reason claims to know the user.
    assert not any("you" in line.lower() for p in body["picks"] for line in p["why"])
    assert "locked" not in body and "full" not in body


def test_a_new_account_is_a_newcomer(h):
    add(h, report("octo/first"), meta("octo/first", "Python"),
        starters("octo/first", issue(1), issue(2, labels=("bug",))),
        report("octo/hard"), meta("octo/hard", "Python"),
        starters("octo/hard", issue(3, labels=("bug",))))
    body = get(h)
    assert names(body) == ["octo/first"]
    assert [i["number"] for i in body["picks"][0]["issues"]] == [1]


def test_a_profile_with_nothing_matching_stays_empty(h):
    add(h, profile(languages=("haskell",)), report("octo/py"), meta("octo/py", "Python"))
    assert get(h)["picks"] == []


def test_only_worth_your_time_with_maintainers_answering(h):
    add(h, profile(),
        report("octo/good"), meta("octo/good", "Python"),
        report("octo/no", "not_viable"), meta("octo/no", "Python"),
        report("octo/unsure", "insufficient_evidence"), meta("octo/unsure", "Python"),
        report("octo/slow", median_first_response_hours=200.0), meta("octo/slow", "Python"),
        report("octo/silent", no_reply=11), meta("octo/silent", "Python"),
        report("octo/mute", median_first_response_hours=None), meta("octo/mute", "Python"),
        report("octo/stale", age_days=20), meta("octo/stale", "Python"),
        report("octo/archived"), meta("octo/archived", "Python", archived=True),
        report("octo/fork"), meta("octo/fork", "Python", fork=True),
        report("octo/go"), meta("octo/go", "Go"))
    body = get(h)
    assert names(body) == ["octo/good"]
    p = body["picks"][0]
    assert p["headline"] == "Worth your time" and p["tone"] == "good"
    assert p["odds"]["level"] == "good"
    assert p["why"][0] == "Written in Python, one of your languages."
    assert "Maintainers usually reply within 3 hours." in p["why"]
    assert "6 people had their first pull request merged here recently." in p["why"]
    assert p["reason"].startswith("Outside contributors get real replies here")
    assert p["numbers_line"].startswith("Of 20 pull requests from outside contributors")


def test_the_newest_report_decides(h):
    add(h, profile(), report("octo/changed"), meta("octo/changed", "Python"))
    add(h, report("octo/changed", "not_viable"))
    assert names(get(h)) == []


def test_merged_pull_requests_add_languages_and_already_in_repos_are_left_out(h):
    add(h, profile(languages=()), connection(),
        pr("rust-lang/done"), pr("rust-lang/done", 2), pr("octo/tried", state="closed"),
        meta("rust-lang/done", "Rust"), meta("octo/tried", "Rust"),
        report("rust-lang/done"), report("octo/tried"),
        report("octo/rusty"), meta("octo/rusty", "Rust"),
        report("octocat/mine"), meta("octocat/mine", "Rust"),
        report("octo/py"), meta("octo/py", "Python"))
    body = get(h)
    assert names(body) == ["octo/rusty"]
    assert body["picks"][0]["why"][0] == ("Written in Rust, where you've had pull "
                                          "requests merged before.")
    assert body["basis"]["history_languages"] == ["Rust"]
    assert body["basis"]["already_contributing"] == 2 and body["basis"]["connected"]


def test_rank_is_by_points_then_the_discover_order(h):
    add(h, profile(languages=("python",), topics=("cli",)), connection(),
        pr("octo/old"), meta("octo/old", "Python"),
        report("octo/both"), meta("octo/both", "Python", topics=["cli"]),
        report("octo/lang"), meta("octo/lang", "Python"),
        report("octo/topic"), meta("octo/topic", "Go", topics=["cli"]),
        report("octo/lang-more", outsider_attempts=40, outsider_merged=20, no_reply=4),
        meta("octo/lang-more", "Python"))
    # both: stated + merged-in + topic; lang-more beats lang on merged share.
    assert names(get(h)) == ["octo/both", "octo/lang-more", "octo/lang", "octo/topic"]
    why = get(h)["picks"][0]["why"]
    assert why[:2] == ["Written in Python, one of your languages, and you've had pull "
                       "requests merged in it.", "About cli, a topic you picked."]


def test_a_pick_says_what_it_does_best_among_the_picks(h):
    add(h, profile(languages=("python",)),
        report("octo/quick", median_first_response_hours=1.0), meta("octo/quick", "Python"),
        report("octo/merges", outsider_merged=19), meta("octo/merges", "Python"))
    assert {p["repo"]: p["standout"] for p in get(h)["picks"]} == {
        "octo/quick": "A first reply typically comes within an hour.",
        "octo/merges": "95% of outside pull requests were merged."}


def test_newcomers_see_beginner_issues_and_skip_long_odds(h):
    add(h, profile(level="newcomer", contributions=("docs",)),
        report("octo/long", outsider_merged=0), meta("octo/long", "Python"),
        report("octo/none"), meta("octo/none", "Python"),
        starters("octo/none", issue(1, labels=["help wanted"])),
        report("octo/issues"), meta("octo/issues", "Python"),
        starters("octo/issues", issue(1), issue(2, labels=["help wanted"]),
                 issue(3, labels=["good first issue", "documentation"]), issue(4), issue(5)),
        report("octo/unknown"), meta("octo/unknown", "Python"))
    body = get(h)
    # long odds and known issues with none for first-timers are dropped;
    # unknown issues keep the repo, known fitting ones rank it higher.
    assert names(body) == ["octo/issues", "octo/unknown"]
    p = body["picks"][0]
    assert [i["number"] for i in p["issues"]] == [3, 1, 4]  # docs first, beginners only
    assert all(i["beginner"] for i in p["issues"])
    assert "Has an open docs issue, the kind of work you want to do." in p["why"]
    assert body["picks"][1]["issues"] == []


def test_experienced_users_see_every_issue_and_long_odds(h):
    add(h, profile(level="experienced"),
        report("octo/long", outsider_merged=0), meta("octo/long", "Python"),
        report("octo/help"), meta("octo/help", "Python"),
        starters("octo/help", issue(1, labels=["help wanted"])))
    body = get(h)
    assert names(body) == ["octo/help", "octo/long"]
    assert body["picks"][0]["issues"][0]["number"] == 1
    assert not any("first pull request" in w for w in body["picks"][0]["why"])


def test_old_starter_issues_are_not_shown(h):
    add(h, profile(), report("octo/a"), meta("octo/a", "Python"),
        starters("octo/a", issue(1), age_hours=100))
    assert get(h)["picks"][0]["issues"] == []


def test_issues_nobody_is_on_come_first_then_fitting_ones(h):
    add(h, profile(level="experienced", contributions=("docs",)),
        report("octo/a"), meta("octo/a", "Python"),
        starters("octo/a", issue(1, title="Fix the docs", people=2), issue(2),
                 issue(3, title="Fix the docs")))
    assert [i["number"] for i in get(h)["picks"][0]["issues"]] == [3, 2, 1]


def test_issues_cached_before_they_said_who_is_on_them_are_not_shown(h):
    old = {k: v for k, v in issue(1).items() if k not in ("people", "open_prs")}
    add(h, profile(), report("octo/a"), meta("octo/a", "Python"), starters("octo/a", old))
    assert get(h)["picks"][0]["issues"] == []


def test_find_results_fill_in_repos_without_a_report(h):
    found = {"repo": "octo/found", "verdict": "viable", "language": "Python",
             "description": "d", "stars": 5, "stats": dict(STATS), "issues": [issue(9)]}
    partial = {"repo": "octo/partial", "verdict": "viable", "language": "Python",
               "stats": {"outsider_attempts": 3}, "issues": []}
    add(h, profile(), FindCache(key="k", params={"engine_version": ENGINE_VERSION,
                                                 "starter_rules": RULES_VERSION},
                                results=[found, partial]))
    body = get(h)
    assert names(body) == ["octo/found"]
    assert body["picks"][0]["issues"][0]["number"] == 9


def test_every_pick_is_free(h):
    add(h, profile(), *[x for i in range(5) for x in (report(f"octo/r{i}"),
                                                      meta(f"octo/r{i}", "Python"))])
    body = get(h)
    assert len(body["picks"]) == 5
    assert "locked" not in body and "full" not in body
    assert len(get(h, limit=1)["picks"]) == 1


def many(n, language="Python"):
    """`n` repos that all fit, better ones first: octo/r00 is merged most."""
    return [x for i in range(n) for x in (
        report(f"octo/r{i:02}", outsider_attempts=200, outsider_merged=150 - i),
        meta(f"octo/r{i:02}", language))]


def test_parts_keep_one_order_with_no_repeats_and_an_end(h):
    add(h, profile(), *many(25))
    whole = get(h, limit=30)
    assert whole["total"] == 25 and whole["next"] is None
    assert names(whole) == [f"octo/r{i:02}" for i in range(25)]

    seen, offset = [], 0
    while offset is not None:
        part = get(h, limit=10, offset=offset)
        assert part["total"] == 25
        seen += names(part)
        offset = part["next"]
    assert seen == names(whole) and len(set(seen)) == 25
    # The parts were 10, 10 and 5; asking again gives the same part.
    assert get(h, limit=10, offset=20)["next"] is None
    assert names(get(h, limit=10, offset=10)) == names(whole)[10:20]
    # Past the end: nothing, and no part after it.
    past = get(h, offset=40)
    assert past["picks"] == [] and past["next"] is None and past["total"] == 25


def test_a_part_that_ends_on_the_last_pick_is_the_end(h):
    add(h, profile(), *many(10))
    assert get(h, limit=10)["next"] is None
    assert get(h, limit=9)["next"] == 9


def test_at_most_sixty_picks_are_ranked_for_one_person(h):
    add(h, profile(), *many(recommendations.MAX_PICKS + 5))
    first = get(h, limit=30)
    assert first["total"] == recommendations.MAX_PICKS == 60 and first["next"] == 30
    last = get(h, limit=30, offset=30)
    assert last["next"] is None and names(last)[-1] == "octo/r59"
    assert get(h, offset=60)["picks"] == []


def test_a_new_accounts_spread_is_the_same_across_parts(h):
    add(h, *many(6), *[x for i in range(3) for x in (
        report(f"octo/go{i}", outsider_attempts=200, outsider_merged=100 - i),
        meta(f"octo/go{i}", "Go"))])
    whole = names(get(h, limit=30))
    assert whole[:6] == ["octo/r00", "octo/go0", "octo/r01", "octo/go1", "octo/r02", "octo/go2"]
    parts = [n for offset in (0, 4, 8) for n in names(get(h, limit=4, offset=offset))]
    assert parts == whole


def test_limit_and_offset_are_checked(h):
    for params in ({"limit": 0}, {"limit": 31}, {"offset": -1}):
        assert h.get(URL, user="u1", params=params).status_code == 400, params


def test_no_github_call_and_no_charge(h):
    add(h, profile(), report("octo/a"), meta("octo/a", "Python"))
    calls = len(h.svc.lookup.details.calls)
    get(h)
    get(h)
    assert len(h.svc.lookup.details.calls) == calls
    assert h.engine.calls == []
