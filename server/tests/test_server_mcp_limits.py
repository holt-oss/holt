"""The MCP connector's buckets (API.md, "MCP"): every chat arrives from a few
Anthropic or OpenAI addresses, so the web marks those requests with
`X-Holt-Client: mcp` and they share one bucket of each kind, apart from the
per-IP buckets the site's visitors draw on."""

from __future__ import annotations

import sys
import types

import pytest

MCP = {"X-Holt-Client": "mcp"}


def post(h, repo: str, ip: str = "3.3.3.3", mcp: bool = True, user: str | None = None):
    headers = h.headers(user, ip) | (MCP if mcp else {})
    return h.client.post("/v1/analyses", json={"repo": repo}, headers=headers)


def get(h, path: str, ip: str = "3.3.3.3", mcp: bool = True):
    return h.client.get(path, headers=h.headers(None, ip) | (MCP if mcp else {}))


def test_mcp_work_is_one_bucket_for_every_address(make_harness):
    h = make_harness(HOLT_MCP_WORK_PER_HOUR=2, HOLT_ANON_RATE_PER_HOUR=1)
    # Two chats from two of the provider's addresses: one bucket, and the
    # per-IP limit (1/h here) is not what stops them.
    assert post(h, "octo/one", ip="3.3.3.3").status_code == 202
    assert post(h, "octo/two", ip="4.4.4.4").status_code == 202
    r = post(h, "octo/three", ip="5.5.5.5")
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "rate_limited" and err["retry_after"] > 0


def test_mcp_work_never_touches_the_sites_buckets(make_harness):
    h = make_harness(HOLT_MCP_WORK_PER_HOUR=1, HOLT_ANON_RATE_PER_HOUR=1)
    # A person on the site first: the MCP bucket is still full after it.
    assert post(h, "octo/one", ip="3.3.3.3", mcp=False).status_code == 202
    assert post(h, "octo/two", ip="3.3.3.3").status_code == 202
    assert post(h, "octo/three", ip="3.3.3.3").status_code == 429
    # A person from another of the provider's addresses still has their check.
    assert post(h, "octo/three", ip="4.4.4.4", mcp=False).status_code == 202


def test_mcp_needs_no_client_address(make_harness):
    h = make_harness()
    assert post(h, "octo/one", ip=None).status_code == 202
    # Without the marker an anonymous request still has to say who it is for.
    assert post(h, "octo/two", ip=None, mcp=False).status_code == 400


def test_the_marker_is_ignored_for_a_signed_in_user(make_harness):
    h = make_harness(HOLT_MCP_WORK_PER_HOUR=1)
    assert post(h, "octo/one").status_code == 202
    # The user's own bucket, not the exhausted MCP one.
    assert post(h, "octo/two", user="u1").status_code == 202


def test_an_unknown_client_marker_is_an_ordinary_visitor(make_harness):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=1, HOLT_MCP_WORK_PER_HOUR=5)
    headers = h.headers(None, "7.7.7.7") | {"X-Holt-Client": "extension"}
    assert h.client.post("/v1/analyses", json={"repo": "octo/one"}, headers=headers).status_code == 202
    assert h.client.post("/v1/analyses", json={"repo": "octo/two"}, headers=headers).status_code == 429


def test_cached_reports_and_joining_cost_the_mcp_nothing(make_harness):
    h = make_harness(run_jobs=False, HOLT_MCP_WORK_PER_HOUR=1)
    job = post(h, "octo/one").json()["job_id"]
    # The same repo again while it runs: the same job, and no second hit.
    for _ in range(3):
        r = post(h, "octo/one")
        assert r.status_code == 202 and r.json()["job_id"] == job
    # The bucket is spent by the one new check, and only by it.
    assert post(h, "octo/two").status_code == 429


def test_joining_a_running_check_is_free_for_visitors_too(make_harness):
    # API.md, "Rate limits": joining a running job never counts.
    h = make_harness(run_jobs=False, HOLT_ANON_RATE_PER_HOUR=1)
    job = post(h, "octo/one", mcp=False).json()["job_id"]
    r = post(h, "octo/one", mcp=False)
    assert r.status_code == 202 and r.json()["job_id"] == job
    assert post(h, "octo/two", mcp=False).status_code == 429


def test_mcp_starts_nothing_when_github_points_run_low(make_harness):
    h = make_harness(HOLT_MCP_WORK_PER_HOUR=50)
    h.svc.pool.note_points(0, 600)
    h.svc.pool.note_points(1, 600)  # 1200, under the warm pass's 1500 floor
    r = post(h, "octo/one")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    # People on the site are not held back by it.
    assert post(h, "octo/one", mcp=False).status_code == 202


@pytest.fixture
def starter_calls(monkeypatch):
    calls: list[str] = []

    def starter_issues(repo, token, limit, as_of=None):
        calls.append(repo)
        return [{"number": i, "title": f"Issue {i}", "labels": [], "comments": 0,
                 "why": []} for i in range(1, 6)]

    mod = types.ModuleType("holt.starter")
    mod.starter_issues = starter_issues
    mod.RULES_VERSION = 1
    monkeypatch.setitem(sys.modules, "holt.starter", mod)
    return calls


def test_mcp_reads_share_their_own_bucket(make_harness, starter_calls):
    h = make_harness(HOLT_MCP_READ_PER_HOUR=1, HOLT_ANON_READ_RATE_PER_HOUR=1)
    assert get(h, "/v1/repos/octo/one/starter-issues", ip="3.3.3.3").status_code == 200
    r = get(h, "/v1/repos/octo/two/starter-issues", ip="4.4.4.4")
    assert r.status_code == 429
    # A cache hit costs nothing.
    assert get(h, "/v1/repos/octo/one/starter-issues", ip="4.4.4.4").status_code == 200
    # The site's per-IP read bucket is untouched.
    assert get(h, "/v1/repos/octo/two/starter-issues", ip="3.3.3.3", mcp=False).status_code == 200
