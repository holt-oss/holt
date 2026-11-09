"""The MCP connector's buckets (API.md, "MCP"): every chat arrives from a few
Anthropic or OpenAI addresses, so the web marks those requests with
`X-Holt-Client: mcp` and they share one bucket of each kind, apart from the
per-IP buckets the site's visitors draw on."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

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


# --- one caller can't take the whole shared bucket ---------------------------------


@pytest.fixture
def harness(make_harness):
    """No jobs run, and GitHub knows every repo name: these tests start many."""

    def build(**overrides):
        h = make_harness(run_jobs=False, **overrides)

        async def canonical(repo: str) -> str:
            return repo

        h.svc.canonical = canonical
        return h

    return build


def test_one_address_cant_take_the_whole_mcp_bucket(harness):
    h = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=2, HOLT_MCP_WORK_PER_HOUR=10)
    assert post(h, "octo/one", ip="3.3.3.3").status_code == 202
    assert post(h, "octo/two", ip="3.3.3.3").status_code == 202
    r = post(h, "octo/three", ip="3.3.3.3")
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "rate_limited" and err["retry_after"] > 0
    # Everyone else still has the rest of the bucket.
    assert post(h, "octo/three", ip="4.4.4.4").status_code == 202


def test_the_defaults_fit_one_persons_30_repo_compare(harness):
    h = harness()
    assert h.svc.settings.mcp_work_per_ip_per_hour == 30
    assert h.svc.settings.mcp_work_per_hour == 60
    for i in range(30):
        assert post(h, f"octo/r{i}", ip="3.3.3.3").status_code == 202, i
    assert post(h, "octo/r30", ip="3.3.3.3").status_code == 429
    # And half the shared bucket is left for everyone else.
    assert post(h, "octo/r30", ip="4.4.4.4").status_code == 202


def test_refused_by_one_limit_spends_nothing_on_the_other(harness):
    # Over the shared bucket: the address's own count doesn't move.
    h = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=2, HOLT_MCP_WORK_PER_HOUR=1)
    assert post(h, "octo/one", ip="3.3.3.3").status_code == 202
    for _ in range(3):
        assert post(h, "octo/two", ip="4.4.4.4").status_code == 429
    assert h.svc.limiter.count("mcp-ip:4.4.4.4") == 0
    # Over the address's own limit: the shared bucket doesn't move.
    h2 = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=1, HOLT_MCP_WORK_PER_HOUR=5)
    assert post(h2, "octo/a", ip="3.3.3.3").status_code == 202
    for _ in range(3):
        assert post(h2, "octo/b", ip="3.3.3.3").status_code == 429
    assert h2.svc.limiter.count("mcp") == 1


def test_no_address_neither_bypasses_the_ceiling_nor_crashes(harness):
    h = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=2, HOLT_MCP_WORK_PER_HOUR=10)
    assert post(h, "octo/one", ip=None).status_code == 202
    assert post(h, "octo/two", ip=None).status_code == 202
    # Requests with no address share one count, at the same ceiling.
    assert post(h, "octo/three", ip=None).status_code == 429
    assert post(h, "octo/three", ip="4.4.4.4").status_code == 202


def test_an_ipv6_caller_cant_rotate_around_the_ceiling(harness):
    # One network gets a whole /64 to pick addresses from: it counts as one.
    h = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=2, HOLT_MCP_WORK_PER_HOUR=10)
    assert post(h, "octo/one", ip="2001:db8:1:2::1").status_code == 202
    assert post(h, "octo/two", ip="2001:db8:1:2:aaaa::9").status_code == 202
    assert post(h, "octo/three", ip="2001:db8:1:2:bbbb::7").status_code == 429
    assert post(h, "octo/three", ip="2001:db8:1:3::1").status_code == 202
    # The same IPv4 address in its IPv6 form is the same caller.
    h2 = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=1, HOLT_MCP_WORK_PER_HOUR=10)
    assert post(h2, "octo/x", ip="3.3.3.3").status_code == 202
    assert post(h2, "octo/y", ip="::ffff:3.3.3.3").status_code == 429
    # Something that isn't an address is still counted, and doesn't crash.
    assert post(h2, "octo/z", ip="not-an-address").status_code == 202
    assert post(h2, "octo/w", ip="not-an-address").status_code == 429


def test_the_ceiling_is_mcp_only_and_zero_turns_it_off(harness):
    h = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=1, HOLT_ANON_RATE_PER_HOUR=5)
    assert post(h, "octo/one", ip="3.3.3.3").status_code == 202
    # A person on the site from that address draws on their own bucket.
    assert post(h, "octo/two", ip="3.3.3.3", mcp=False).status_code == 202
    off = harness(HOLT_MCP_WORK_PER_IP_PER_HOUR=0, HOLT_MCP_WORK_PER_HOUR=3)
    for i in range(3):
        assert post(off, f"octo/x{i}", ip="3.3.3.3").status_code == 202


# --- GitHub's points after their reset ---------------------------------------------


def hour_ago() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def in_an_hour() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def test_a_count_past_its_reset_doesnt_hold_the_mcp_back(make_harness):
    h = make_harness()
    h.svc.pool.note_points(0, 600, hour_ago())
    h.svc.pool.note_points(1, 600, hour_ago())
    assert h.svc.pool.points_left() is None  # as states() reads it: out of date
    assert [t.remaining for t in h.svc.pool.states()] == [None, None]
    assert post(h, "octo/one").status_code == 202


def test_a_count_still_inside_its_hour_holds_the_mcp_back(make_harness):
    h = make_harness()
    h.svc.pool.note_points(0, 600, in_an_hour())
    h.svc.pool.note_points(1, 600, in_an_hour())
    assert h.svc.pool.points_left() == 1200
    assert post(h, "octo/one").status_code == 429


def test_one_count_past_its_reset_makes_the_total_unknown(make_harness):
    h = make_harness()
    h.svc.pool.note_points(0, 600, hour_ago())
    h.svc.pool.note_points(1, 600, in_an_hour())
    assert h.svc.pool.points_left() is None
    assert post(h, "octo/one").status_code == 202


def test_points_left_changes_nothing_it_reads(make_harness):
    # Like states(): a reading, so the count stays until GitHub reports a new one.
    h = make_harness()
    h.svc.pool.note_points(0, 600, hour_ago())
    h.svc.pool.points_left()
    assert h.svc.pool._state[0].remaining == 600
