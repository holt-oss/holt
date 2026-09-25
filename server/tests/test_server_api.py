"""Endpoints from API.md, with the engine and GitHub faked."""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest
from holt_server.db import Job, User
from holt_server.errors import ApiError
from sqlalchemy import select


def db_rows(h, model):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model))).scalars().all()
    return h.client.portal.call(q)


# --- basics -------------------------------------------------------------------


def test_health_needs_no_key(h):
    r = h.client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["version"]


def test_internal_key_required(h):
    r = h.client.post("/v1/analyses", json={"repo": "pallets/flask"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    r = h.client.post("/v1/analyses", json={"repo": "pallets/flask"},
                      headers={"X-Holt-Internal-Key": "wrong"})
    assert r.status_code == 401


def test_invalid_repo(h):
    r = h.post("/v1/analyses", {"repo": "not a repo"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_repo"
    assert r.json()["error"]["message"]


def test_missing_repo_is_not_found(h):
    r = h.post("/v1/analyses", {"repo": "nobody/nothing"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_bad_body_is_a_plain_error(h):
    r = h.post("/v1/analyses", {"repo": "pallets/flask", "mode": "turbo"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"


def test_unknown_path_uses_error_envelope(h):
    r = h.get("/v1/nothing-here")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# --- analyses and the cache -----------------------------------------------------


def test_rules_analysis_queues_then_caches(h):
    r = h.post("/v1/analyses", {"repo": "https://github.com/PALLETS/flask/tree/main"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    done = h.wait(body["job_id"])
    assert done["status"] == "done"
    assert done["progress"] == 1.0
    assert done["report"]["repo"] == "pallets/flask"  # canonical casing
    assert done["error"] is None

    again = h.post("/v1/analyses", {"repo": "Pallets/Flask"})
    assert again.status_code == 200
    assert again.json() == {"status": "done", "report": done["report"]}
    assert len(h.engine.calls) == 1

    # A different day budget is a different question.
    other = h.post("/v1/analyses", {"repo": "pallets/flask", "days": 30})
    assert other.status_code == 202

    fresh = h.post("/v1/analyses", {"repo": "pallets/flask", "refresh": True})
    assert fresh.status_code == 202


def test_report_endpoint(h):
    assert h.get("/v1/reports/pallets/flask").status_code == 404
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    h.wait(job)
    r = h.get("/v1/reports/PALLETS/FLASK?mode=rules&days=7")
    assert r.status_code == 200
    assert r.json()["repo"] == "pallets/flask"
    assert h.get("/v1/reports/pallets/flask?mode=ai").status_code == 404


def test_identical_running_job_is_shared(h):
    h.engine.gate.clear()
    try:
        a = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
        b = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
        assert a == b
    finally:
        h.engine.gate.set()
    h.wait(a)
    assert len(h.engine.calls) == 1


def test_engine_error_reaches_the_job(h):
    h.engine.error = ApiError("upstream", "GitHub didn't answer properly just now.")
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    body = h.wait(job)
    assert body["status"] == "error"
    assert body["error"]["code"] == "upstream"
    assert body["report"] is None


def test_crash_becomes_internal_error(h):
    h.engine.error = ZeroDivisionError("boom")
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    body = h.wait(job)
    assert body["error"]["code"] == "internal"
    assert "boom" not in body["error"]["message"]


def test_unknown_job(h):
    r = h.get("/v1/analyses/doesnotexist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# --- server-sent events ---------------------------------------------------------


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [x for x in block.splitlines() if not x.startswith(":")]
        if not lines:
            continue
        event = next(x[7:] for x in lines if x.startswith("event: "))
        data = json.loads(next(x[6:] for x in lines if x.startswith("data: ")))
        events.append((event, data))
    return events


def test_events_stream_stages_then_done(h):
    h.engine.gate.clear()
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    h.client.portal.call(asyncio.sleep, 0.1)
    h.engine.gate.set()
    with h.client.stream("GET", f"/v1/analyses/{job}/events", headers=h.headers()) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.read().decode())
    kinds = [e for e, _ in events]
    assert kinds[-1] == "done"
    assert kinds.count("done") == 1 and "error" not in kinds
    assert all(e == "stage" for e in kinds[:-1])
    assert events[-1][1]["report"]["repo"] == "pallets/flask"
    progress = [d["progress"] for e, d in events if e == "stage"]
    assert progress == sorted(progress)


def test_events_after_finish_replay_the_result(h):
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    h.wait(job)
    with h.client.stream("GET", f"/v1/analyses/{job}/events", headers=h.headers()) as r:
        events = parse_sse(r.read().decode())
    assert [e for e, _ in events] == ["done"]


def test_events_error(h):
    h.engine.error = ApiError("rate_limited", "slow down", retry_after=60)
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}).json()["job_id"]
    with h.client.stream("GET", f"/v1/analyses/{job}/events", headers=h.headers()) as r:
        events = parse_sse(r.read().decode())
    assert events[-1] == ("error", {"error": {"code": "rate_limited", "message": "slow down",
                                               "retry_after": 60}})


# --- rate limits ------------------------------------------------------------------


def test_anonymous_rate_limit_per_ip(make_harness):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=2)
    for repo in ("octo/one", "octo/two"):
        assert h.post("/v1/analyses", {"repo": repo}, ip="1.1.1.1").status_code == 202
    r = h.post("/v1/analyses", {"repo": "octo/three"}, ip="1.1.1.1")
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "rate_limited" and err["retry_after"] > 0
    assert r.headers["Retry-After"] == str(err["retry_after"])
    # Another address is unaffected, and so is a signed-in user.
    assert h.post("/v1/analyses", {"repo": "octo/three"}, ip="2.2.2.2").status_code == 202
    assert h.post("/v1/analyses", {"repo": "octo/four"}, ip="1.1.1.1",
                  user="u1").status_code == 202


def test_cache_hits_do_not_count(make_harness):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=1)
    job = h.post("/v1/analyses", {"repo": "octo/one"}, ip="9.9.9.9").json()["job_id"]
    h.wait(job)
    for _ in range(3):
        assert h.post("/v1/analyses", {"repo": "octo/one"}, ip="9.9.9.9").status_code == 200


# --- AI mode, quota and BYOK --------------------------------------------------------


def test_ai_needs_sign_in(h):
    r = h.post("/v1/analyses", {"repo": "pallets/flask", "mode": "ai"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "needs_key"


def test_ai_without_server_key_or_byok_needs_key(h):
    r = h.post("/v1/analyses", {"repo": "pallets/flask", "mode": "ai"}, user="u1")
    assert r.json()["error"]["code"] == "needs_key"


def test_ai_quota(make_harness):
    h = make_harness(OPENROUTER_API_KEY="sk-or-server", HOLT_FREE_AI_LIMIT=2,
                     OPENROUTER_MODEL="some/model")
    for repo in ("octo/one", "octo/two"):
        job = h.post("/v1/analyses", {"repo": repo, "mode": "ai"}, user="u1").json()["job_id"]
        assert h.wait(job)["status"] == "done"
    assert h.model_specs[0].api_key == "sk-or-server"
    assert h.model_specs[0].model == "some/model"
    assert h.model_specs[0].provider == "openrouter"

    me = h.get("/v1/me", user="u1").json()
    assert me["quota"]["ai_used"] == 2 and me["quota"]["ai_limit"] == 2
    assert me["plan"] == "free" and me["byok"] is None

    r = h.post("/v1/analyses", {"repo": "octo/three", "mode": "ai"}, user="u1")
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "quota_exceeded"
    # Someone else still has theirs, and cached AI reports cost nothing.
    assert h.post("/v1/analyses", {"repo": "octo/one", "mode": "ai"},
                  user="u1").status_code == 200


def test_failed_ai_job_is_refunded(make_harness):
    h = make_harness(OPENROUTER_API_KEY="sk-or-server")
    h.engine.error = ApiError("upstream", "model down")
    job = h.post("/v1/analyses", {"repo": "octo/one", "mode": "ai"}, user="u1").json()["job_id"]
    assert h.wait(job)["status"] == "error"
    assert h.get("/v1/me", user="u1").json()["quota"]["ai_used"] == 0


def test_byok_roundtrip_and_use(make_harness):
    h = make_harness(OPENROUTER_API_KEY="sk-or-server")
    assert h.get("/v1/me").status_code == 401

    r = h.put("/v1/me/byok", {"provider": "anthropic", "api_key": "sk-ant-secret-123"},
              user="u2")
    assert r.status_code == 200
    assert r.json()["byok"] == {"provider": "anthropic", "model": "claude-haiku-4-5",
                                "set": True}
    assert "sk-ant-secret-123" not in r.text
    assert "sk-ant-secret-123" not in h.get("/v1/me", user="u2").text

    user = [u for u in db_rows(h, User) if u.id == "u2"][0]
    assert user.byok_cipher and "sk-ant-secret-123" not in user.byok_cipher

    job = h.post("/v1/analyses", {"repo": "octo/one", "mode": "ai"}, user="u2").json()["job_id"]
    assert h.wait(job)["status"] == "done"
    spec = h.model_specs[-1]
    assert (spec.provider, spec.api_key, spec.byok) == ("anthropic", "sk-ant-secret-123", True)
    assert h.get("/v1/me", user="u2").json()["quota"]["ai_used"] == 0

    r = h.delete("/v1/me/byok", user="u2")
    assert r.status_code == 200 and r.json()["byok"] is None


def test_byok_rejects_unknown_provider(h):
    r = h.put("/v1/me/byok", {"provider": "acme", "api_key": "sk-123456789"}, user="u1")
    assert r.status_code == 400


def test_history(h):
    job = h.post("/v1/analyses", {"repo": "pallets/flask"}, user="u3").json()["job_id"]
    h.wait(job)
    items = h.get("/v1/me/history", user="u3").json()["items"]
    assert [i["job_id"] for i in items] == [job]
    assert items[0]["headline"] == "Worth your time"
    assert h.get("/v1/me/history", user="someone-else").json()["items"] == []


def test_secrets_never_stored_on_jobs(make_harness):
    h = make_harness(OPENROUTER_API_KEY="sk-or-server")
    h.put("/v1/me/byok", {"provider": "openai", "api_key": "sk-openai-xyz-999"}, user="u4")
    job = h.post("/v1/analyses", {"repo": "octo/one", "mode": "ai"}, user="u4").json()["job_id"]
    h.wait(job)
    for row in db_rows(h, Job):
        dumped = json.dumps({"p": row.params, "r": row.result, "e": row.error})
        assert "sk-openai-xyz-999" not in dumped and "sk-or-server" not in dumped


# --- badge --------------------------------------------------------------------------


def test_badge(h):
    r = h.client.get("/badge/pallets/flask.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=86400" in r.headers["cache-control"]
    assert "not checked yet" in r.text
    # The unchecked badge queued a rules check behind itself.
    jobs = db_rows(h, Job)
    assert len(jobs) == 1 and jobs[0].mode == "rules"
    h.wait(jobs[0].id)
    r = h.client.get("/badge/Pallets/Flask.svg")
    assert "newcomer-friendly" in r.text and "not newcomer" not in r.text
    assert "https://holt.dev/pallets/flask\"" in r.text


# --- starter issues and find ---------------------------------------------------------


def test_starter_endpoints_501_until_module_exists(h, monkeypatch):
    monkeypatch.setitem(sys.modules, "holt.starter", None)
    r = h.get("/v1/repos/pallets/flask/starter-issues")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"
    r = h.post("/v1/find", {"languages": ["python"]})
    assert r.status_code == 501


@pytest.fixture
def fake_starter(monkeypatch):
    from datetime import UTC, datetime

    mod = types.ModuleType("holt.starter")
    seen = {}

    def starter_issues(repo, token, limit, as_of=None):
        seen["issues"] = (repo, token, limit)
        return [{"number": 7, "title": "Fix typo", "labels": ["good first issue"],
                 "created_at": datetime(2026, 9, 1, tzinfo=UTC), "comments": 1,
                 "why": ["Labelled good first issue"]}]

    def find(languages, topics, hacktoberfest, token, limit, screen=None, progress=None):
        seen["find"] = (languages, topics, hacktoberfest, limit)
        if progress:
            progress("Screening repositories", 0.5)
        return [
            {"repo": "octo/one", "verdict": "viable", "stats": {"outsider_merged": 4, "x": 1},
             "issues": [{"number": 1, "title": "t", "url": "https://github.com/octo/one/issues/1"}]},
            {"repo": "octo/two", "verdict": "not_viable", "stats": {}, "issues": []},
        ]

    mod.starter_issues = starter_issues
    mod.find = find
    monkeypatch.setitem(sys.modules, "holt.starter", mod)
    return seen


def test_starter_issues(h, fake_starter):
    r = h.get("/v1/repos/PALLETS/flask/starter-issues?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["repo"] == "pallets/flask"
    assert body["issues"] == [{
        "number": 7, "title": "Fix typo", "url": "https://github.com/pallets/flask/issues/7",
        "labels": ["good first issue"], "created_at": "2026-09-01T00:00:00Z", "comments": 1,
        "why": ["Labelled good first issue"],
    }]
    assert fake_starter["issues"][0] == "pallets/flask"
    assert fake_starter["issues"][2] == 5


def test_find(h, fake_starter):
    r = h.post("/v1/find", {"languages": ["python"], "hacktoberfest": True, "limit": 5})
    assert r.status_code == 202
    body = h.wait(r.json()["job_id"], kind="find")
    assert body["status"] == "done"
    assert [x["repo"] for x in body["results"]] == ["octo/one"]
    assert body["results"][0]["headline"] == "Worth your time"
    assert body["results"][0]["stats"] == {"outsider_merged": 4}
    assert fake_starter["find"] == (["python"], [], True, 5)
    # find jobs are not analyses
    assert h.get(f"/v1/analyses/{r.json()['job_id']}").status_code == 404
