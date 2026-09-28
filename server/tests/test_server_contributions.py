"""My Contributions: the fetched pull requests, their verdicts, "found via
Holt", the refresh cooldown, disconnect, and the metric. GitHub is faked."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from holt.evidence.github_graphql import GitHubGraphQL
from holt_server import contributions
from holt_server.db import Contribution, ContributionSync, RepoView, Report, now
from sqlalchemy import select, update

from conftest import canned_report


def pr(repo, number, state="OPEN", created=None, merged=None, closed=None, private=False,
       title=None):
    created = created or now() - timedelta(days=3)
    return {"number": number, "title": title or f"Fix {number}",
            "url": f"https://github.com/{repo}/pull/{number}", "state": state,
            "isDraft": False, "createdAt": created.isoformat(),
            "closedAt": closed.isoformat() if closed else None,
            "mergedAt": merged.isoformat() if merged else None,
            "repository": {"nameWithOwner": repo, "isPrivate": private,
                           "owner": {"login": repo.split("/")[0]}}}


class FakeGitHub:
    def __init__(self) -> None:
        self.users = {583231: "octocat", 42: "someone"}
        self.prs: dict[str, list[dict]] = {"octocat": [], "someone": []}
        self.searches: list[dict] = []
        self.fail: httpx.Response | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/user/"):
            uid = int(req.url.path.rsplit("/", 1)[1])
            if uid in self.users:
                return httpx.Response(200, json={"id": uid, "login": self.users[uid]})
            return httpx.Response(404, json={})
        assert req.url.path == "/graphql"
        if self.fail is not None:
            return self.fail
        body = json.loads(req.content)
        v = body["variables"]
        self.searches.append(v)
        login = v["q"].split("author:", 1)[1].split()[0]
        nodes = self.prs.get(login, [])
        start = int(v.get("cursor") or 0)
        end = start + v["n"]
        return httpx.Response(200, json={"data": {
            "rateLimit": {"remaining": 4000, "resetAt": "2026-09-27T12:00:00Z"},
            "search": {"issueCount": len(nodes),
                       "pageInfo": {"hasNextPage": end < len(nodes), "endCursor": str(end)},
                       "nodes": nodes[start:end]}}})


@pytest.fixture
def gh(h, monkeypatch):
    # GitHub trouble is retried with real backoff sleeps; the retries still
    # happen here, without the minute of waiting between them.
    monkeypatch.setattr(GitHubGraphQL, "_backoff", lambda self, attempt: None)
    fake = FakeGitHub()
    h.svc.http.close()
    h.svc.http = httpx.Client(transport=httpx.MockTransport(fake))
    h.fake = fake
    contributions._refresh_limiter._hits.clear()
    return h


def call(h, fn):
    async def go():
        async with h.svc.db.session() as s:
            out = await fn(s)
            await s.commit()
            return out
    return h.client.portal.call(go)


def connect(h, user="u1", github_id=583231):
    r = h.post("/v1/me/github", {"github_id": github_id, "adult_confirmed": True}, user=user)
    assert r.status_code == 200, r.text
    wait_for_background(h)
    return r


def wait_for_background(h):
    async def go():
        import asyncio
        while contributions._background:
            await asyncio.sleep(0.01)
    h.client.portal.call(go)


def mine(h, user="u1"):
    return h.get("/v1/me/contributions", user=user)


def refresh(h, user="u1"):
    return h.post("/v1/me/contributions/refresh", user=user)


def add_report(h, repo, verdict, created=None):
    async def go(s):
        s.add(Report(repo=repo, repo_key=repo.lower(), mode="rules", days=7,
                     report=canned_report(repo, verdict=verdict),
                     created_at=created or now()))
    call(h, go)


def viewed(h, repo, first, last=None, user="u1"):
    async def go(s):
        s.add(RepoView(user_id=user, repo_key=repo.lower(), repo=repo,
                       first_viewed_at=first, last_viewed_at=last or first))
    call(h, go)


def age_sync(h, minutes, user="u1"):
    async def go(s):
        await s.execute(update(ContributionSync).where(ContributionSync.user_id == user)
                        .values(fetched_at=now() - timedelta(minutes=minutes)))
    call(h, go)


def rows(h):
    return call(h, lambda s: _all(s, Contribution))


async def _all(s, model):
    return (await s.execute(select(model))).scalars().all()


def test_signed_in_and_connected_only(gh):
    r = gh.get("/v1/me/contributions")
    assert r.status_code == 401
    r = mine(gh)
    assert r.status_code == 404
    assert "Connect your GitHub" in r.json()["error"]["message"]
    assert refresh(gh).status_code == 404


def test_connect_fetches_public_prs_with_a_pool_token(gh):
    d = now() - timedelta(days=10)
    gh.fake.prs["octocat"] = [
        pr("pallets/flask", 1, "MERGED", created=d, merged=d + timedelta(days=1),
           closed=d + timedelta(days=1)),
        pr("octo/one", 2, "CLOSED", created=d - timedelta(days=1), closed=d),
        pr("octo/two", 3),
        pr("secret/repo", 4, private=True),  # never kept, even if a token sees it
        pr("octocat/dotfiles", 5),  # their own repository
    ]
    connect(gh)
    [search] = gh.fake.searches
    q = search["q"]
    assert "is:pr" in q and "is:public" in q and "author:octocat" in q
    assert "-user:octocat" in q and "created:>=" in q
    assert search["n"] == 100
    assert sorted((c.repo, c.number, c.state) for c in rows(gh)) == [
        ("octo/one", 2, "closed"), ("octo/two", 3, "open"), ("pallets/flask", 1, "merged")]

    body = mine(gh).json()
    assert len(gh.fake.searches) == 1  # the page reads what was stored
    assert body["login"] == "octocat" and body["window_days"] == 365
    assert body["truncated"] is False
    assert body["summary"] == {"opened": 3, "merged": 1, "waiting": 1, "closed": 1,
                               "landed_share": 0.5, "found_via_holt": 0}
    assert [p["number"] for p in body["pull_requests"]] == [3, 1, 2]  # newest first
    first = body["pull_requests"][1]
    assert first["url"] == "https://github.com/pallets/flask/pull/1"
    assert first["merged_at"].endswith("Z") and first["verdict"] is None


def test_first_page_view_fetches_when_connect_did_not(gh):
    gh.fake.fail = httpx.Response(502)
    connect(gh)
    assert call(gh, lambda s: _all(s, ContributionSync)) == []
    gh.fake.fail = None
    gh.fake.prs["octocat"] = [pr("octo/one", 7)]
    body = mine(gh).json()
    assert [p["number"] for p in body["pull_requests"]] == [7]
    assert body["summary"]["landed_share"] is None  # nothing decided yet


def test_github_trouble_on_the_page_is_a_plain_error(gh):
    gh.fake.fail = httpx.Response(403, headers={"x-ratelimit-remaining": "0",
                                                "x-ratelimit-reset": "0"})
    connect(gh)
    r = mine(gh)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


def test_at_most_200_prs_in_two_searches(gh):
    gh.fake.prs["octocat"] = [pr(f"org/r{i}", i + 1) for i in range(250)]
    connect(gh)
    assert [s["n"] for s in gh.fake.searches] == [100, 100]
    body = mine(gh).json()
    assert body["summary"]["opened"] == 200 and body["truncated"] is True


def test_each_pr_carries_the_latest_cached_rules_verdict(gh):
    gh.fake.prs["octocat"] = [pr("pallets/flask", 1), pr("octo/one", 2), pr("octo/two", 3)]
    add_report(gh, "pallets/flask", "not_viable", created=now() - timedelta(days=5))
    add_report(gh, "pallets/flask", "viable")
    add_report(gh, "octo/one", "insufficient_evidence")
    connect(gh)
    got = {p["repo"]: p["verdict"] for p in mine(gh).json()["pull_requests"]}
    assert got["pallets/flask"]["verdict"] == "viable"
    assert got["pallets/flask"]["headline"] == "Worth your time"
    assert got["pallets/flask"]["tone"] == "good"
    assert got["octo/one"]["headline"] == "Not enough evidence"
    assert got["octo/two"] is None
    assert gh.engine.calls == []  # no analyses started for them


def test_found_via_holt_within_30_days_after_a_view(gh):
    t = now() - timedelta(days=100)
    gh.fake.prs["octocat"] = [
        pr("octo/one", 1, created=t + timedelta(days=5)),     # 5 days after first view
        pr("octo/two", 2, created=t + timedelta(days=45)),    # 45 days: too late
        pr("octo/three", 3, created=t - timedelta(days=1)),   # before viewing
        pr("octo/four", 4, created=t + timedelta(days=62)),   # 2 days after last view
        pr("pallets/flask", 5, "MERGED", created=t + timedelta(days=1),
           merged=t + timedelta(days=2)),
        pr("NixOS/nixpkgs", 6, created=t + timedelta(days=1)),  # never viewed
    ]
    connect(gh)
    for repo in ("octo/one", "octo/two", "octo/three", "pallets/flask"):
        viewed(gh, repo, t)
    viewed(gh, "octo/four", t, last=t + timedelta(days=60))
    body = mine(gh).json()
    flags = {p["number"]: p["found_via_holt"] for p in body["pull_requests"]}
    assert flags == {1: True, 2: False, 3: False, 4: True, 5: True, 6: False}
    assert body["summary"]["found_via_holt"] == 3


def test_after_holt_window_edges():
    t = datetime(2026, 9, 1, tzinfo=UTC)
    assert contributions.after_holt(t, t, None)
    assert contributions.after_holt(t + timedelta(days=30), t, t)
    assert not contributions.after_holt(t + timedelta(days=30, seconds=1), t, t)
    assert not contributions.after_holt(t - timedelta(seconds=1), t, t)
    # SQLite hands timestamps back naive.
    assert contributions.after_holt(t.replace(tzinfo=None), t.replace(tzinfo=None), None)


def test_refresh_is_cached_for_15_minutes(gh):
    gh.fake.prs["octocat"] = [pr("octo/one", 1)]
    connect(gh)
    assert len(gh.fake.searches) == 1
    body = refresh(gh).json()
    assert len(gh.fake.searches) == 1  # cached answer, no GitHub call
    assert body["next_refresh_at"] is not None
    gh.fake.prs["octocat"].append(pr("octo/two", 2))
    age_sync(gh, 16)
    body = refresh(gh).json()
    assert len(gh.fake.searches) == 2
    assert body["summary"]["opened"] == 2
    assert body["next_refresh_at"] > body["fetched_at"]
    age_sync(gh, 16)
    assert mine(gh).json()["next_refresh_at"] is None
    assert len(gh.fake.searches) == 2  # viewing never reads GitHub again


def test_refresh_retries_after_github_trouble_are_limited(gh):
    connect(gh)
    age_sync(gh, 20)
    gh.fake.fail = httpx.Response(502)
    codes = [refresh(gh).json()["error"]["code"] for _ in range(contributions.REFRESH_PER_HOUR)]
    assert set(codes) == {"upstream"}
    r = refresh(gh)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_a_fetch_replaces_the_old_rows(gh):
    gh.fake.prs["octocat"] = [pr("octo/one", 1), pr("octo/two", 2)]
    connect(gh)
    gh.fake.prs["octocat"] = [pr("octo/two", 2, "MERGED", merged=now())]
    age_sync(gh, 20)
    refresh(gh)
    assert [(c.number, c.state) for c in rows(gh)] == [(2, "merged")]


def test_disconnect_deletes_the_fetched_prs(gh):
    gh.fake.prs["octocat"] = [pr("octo/one", 1)]
    gh.fake.prs["someone"] = [pr("octo/two", 2)]
    connect(gh)
    connect(gh, user="u2", github_id=42)
    assert gh.delete("/v1/me/github", user="u1").status_code == 200
    assert [c.user_id for c in rows(gh)] == ["u2"]
    assert [s.user_id for s in call(gh, lambda s: _all(s, ContributionSync))] == ["u2"]
    assert mine(gh).status_code == 404


def test_a_fetch_finishing_after_disconnect_stores_nothing(gh):
    gh.fake.prs["octocat"] = [pr("octo/one", 1)]
    connect(gh)
    gh.delete("/v1/me/github", user="u1")

    async def late():
        return await contributions._fetch_and_store(gh.svc, "u1", "octocat")
    assert gh.client.portal.call(late) is False
    assert rows(gh) == []


def test_background_refresh_takes_stale_users(gh):
    gh.fake.prs["octocat"] = [pr("octo/one", 1)]
    gh.fake.prs["someone"] = [pr("octo/two", 2)]
    connect(gh)
    connect(gh, user="u2", github_id=42)
    assert len(gh.fake.searches) == 2
    age_sync(gh, 60 * 30, user="u2")

    async def remaining():
        return 5000
    gh.svc.lookup.remaining = remaining

    async def run():
        return await contributions.refresh_once(gh.svc, timedelta(hours=20))
    assert gh.client.portal.call(run) == 1
    assert len(gh.fake.searches) == 3
    assert "author:someone" in gh.fake.searches[-1]["q"]

    async def low():
        return 10
    gh.svc.lookup.remaining = low
    age_sync(gh, 60 * 30, user="u1")
    assert gh.client.portal.call(run) == 0
    assert len(gh.fake.searches) == 3


def test_metric_counts_without_people(gh):
    t = now() - timedelta(days=10)
    gh.fake.prs["octocat"] = [pr("octo/one", 1, "MERGED", created=t + timedelta(days=1),
                                 merged=t + timedelta(days=2)),
                              pr("octo/two", 2, created=t + timedelta(days=2)),
                              pr("octo/three", 3, created=t + timedelta(days=2))]
    gh.fake.prs["someone"] = [pr("octo/one", 9, created=t + timedelta(days=1))]
    connect(gh)
    connect(gh, user="u2", github_id=42)
    for repo in ("octo/one", "octo/two"):
        viewed(gh, repo, t)
    viewed(gh, "octo/one", t, user="u2")

    r = gh.get("/v1/metrics/contributions")
    assert r.status_code == 200
    assert r.json() == {"since": "", "window_days": 30, "connected_users": 2,
                        "users_with_pull_requests": 2, "users_with_pr_after_holt": 2,
                        "prs_after_holt": 3, "prs_after_holt_merged": 1}

    # "Don't include me in statistics" leaves u2 out.
    gh.client.patch("/v1/me/github", json={"stats_opt_out": True}, headers=gh.headers("u2"))
    got = gh.get("/v1/metrics/contributions").json()
    assert (got["connected_users"], got["users_with_pr_after_holt"],
            got["prs_after_holt"]) == (1, 1, 2)

    since = (now() + timedelta(days=1)).date().isoformat()
    got = gh.get(f"/v1/metrics/contributions?since={since}").json()
    assert got["since"] == since and got["prs_after_holt"] == 0
    assert gh.get("/v1/metrics/contributions?since=soon").status_code == 400


def test_metric_needs_the_internal_key(gh):
    assert gh.client.get("/v1/metrics/contributions").status_code == 401
