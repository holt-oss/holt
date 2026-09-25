"""/v1/find answers from a 6h cache per normalised profile; hits are free."""

from __future__ import annotations

import sys
import threading
import types
from datetime import timedelta

import pytest
from holt_server.db import FindCache, now
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


def test_limit_beyond_what_was_computed_is_a_miss(h, finder):
    h.wait(find(h, languages=["go"]).json()["job_id"], kind="find")  # 3 results < 20
    # The search ran dry below its limit, so a bigger page would find nothing new.
    r = find(h, languages=["go"], limit=50)
    assert r.status_code == 200 and len(r.json()["results"]) == 3
    assert len(find(h, languages=["go"], limit=2).json()["results"]) == 2
    assert finder.calls[0][2] == 20  # computed for at least the default page
