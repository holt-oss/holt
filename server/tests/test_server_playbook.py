"""The paid playbook (holt_server/playbook.py) against a fake paid-features service.

The service is an httpx.MockTransport: nothing touches the network.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import timedelta

import httpx
import pytest
from holt_server import credits, playbook, pro
from holt_server.db import CreditEvent, Job, Playbook, PlaybookUnlock, now
from sqlalchemy import select, update

KEY = "pro-secret-key-value"
URL = "http://pro:8000"

PRO_PLAYBOOK = {
    "repo": "pallets/flask",
    "version": 1,
    "cached": False,
    "model": "openai/gpt-5-mini",
    "generated_at": "2026-09-28T10:00:00+00:00",
    "archived": False,
    "note": "Only 5 merged pull requests from people outside the project turned up.",
    "evidence": {"version": 1, "fetched_at": "2026-09-28T09:59:00+00:00",
                 "window": {"days": 365, "since": "2025-09-28"},
                 "sample": {"group": "everyone", "merged": 50, "closed": 25}},
    "sections": {
        "must_do": [
            {"text": "Add or change tests with any code change: 34 of 44 merged pull "
                     "requests that changed code did.",
             "sources": [{"fact_id": "tests-8", "statement": "34 of 44 merged pull requests "
                          "that changed code also added or changed tests.",
                          "seen": 34, "of": 44,
                          "links": ["https://github.com/pallets/flask/pull/3876"]}]},
            {"text": "Pass `main` and `typing`.",
             "sources": [{"fact_id": "checks-1", "statement": "Every merge passed `main`.",
                          "seen": 44, "of": 44, "links": []}]},
            {"text": "   ", "sources": []},
        ],
        "size_and_scope": [],
        "reviewers": [],
        "closing_reasons": [
            {"reason": "Written with AI tools",
             "explanation": "The project closes pull requests written with AI tools.",
             "seen": 13, "of": 25,
             "examples": [{"number": 3874, "url": "https://github.com/pallets/flask/pull/3874",
                           "title": "Fix all the things", "who": "davidism",
                           "quote": "See our policy on AI tools."}]},
        ],
        "checklist": [{"text": "Add a changelog entry.",
                       "sources": [{"fact_id": "changelog-2", "statement": "30 of 44 merged "
                                    "pull requests added a changelog entry.",
                                    "seen": 30, "of": 44, "links": []}]}],
    },
}


class FakePro:
    """The service's POST /v1/playbook: answers with `answer`, records
    requests, and holds each request while `gate` is cleared."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: httpx.Response = httpx.Response(200, json=PRO_PLAYBOOK)
        self.gate = threading.Event()
        self.gate.set()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        return self.answer


@pytest.fixture
def fake() -> FakePro:
    return FakePro()


@pytest.fixture
def hp(make_harness, fake):
    h = make_harness(HOLT_PRO_URL=URL, HOLT_PRO_KEY=KEY)
    asyncio.run(h.svc.pro.aclose())
    h.svc.pro = pro.ProClient(URL, KEY, transport=httpx.MockTransport(fake), retry_delay=0)
    return h


def call(h, fn, *args, **kw):
    async def go():
        return await fn(*args, **kw)

    return h.client.portal.call(go)


def gift(h, user: str, n: int = 1) -> None:
    call(h, credits.grant, h.svc, user, n, pool="purchased", reason="test", actor="test")


def balance(h, user: str) -> dict:
    return h.get("/v1/me/credits", user=user).json()


def rows(h, model, *where):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model).where(*where))).scalars().all()

    return h.client.portal.call(q)


def state(h, repo: str = "pallets/flask", user: str | None = None) -> dict:
    r = h.get(f"/v1/playbook/{repo}", user=user)
    assert r.status_code == 200, r.text
    return r.json()


def unlock(h, user: str, repo: str = "pallets/flask"):
    return h.post(f"/v1/me/playbook/{repo}", user=user)


def wait(h, job_id: str) -> dict:
    return h.wait(job_id, kind="playbook-jobs")


def wait_for_requests(fake: FakePro, n: int) -> None:
    deadline = time.monotonic() + 10
    while len(fake.requests) < n and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(fake.requests) >= n


# --- off --------------------------------------------------------------------------------


def test_without_the_service_the_section_is_off(h):
    assert state(h, user="u") == {
        "repo": "pallets/flask", "available": False, "teaser": None, "playbook": None,
        "unlocked": False, "access": None, "on_sale": False, "job": None}
    r = unlock(h, "u")
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"


# --- before anyone paid -------------------------------------------------------------------


def test_anyone_can_ask_and_nothing_is_written_yet(hp):
    s = state(hp)
    assert s["available"] is True
    assert s["teaser"] is None and s["playbook"] is None and s["access"] is None
    assert s["on_sale"] is False  # no pass in the shipped catalogue unlocks it


def test_signed_in_state_says_what_unlocking_would_cost(hp):
    s = state(hp, user="u")
    # Welcome credits are free ones, and playbooks take purchased credits only.
    assert s["access"]["allowed"] is False
    assert s["access"]["cost"] == 1 and s["access"]["code"] == "quota_exceeded"
    gift(hp, "u")
    s = state(hp, user="u")
    assert (s["access"]["allowed"], s["access"]["via"], s["access"]["cost"]) == (True, "credits", 1)


def test_signing_out_is_refused(hp):
    r = hp.post("/v1/me/playbook/pallets/flask")
    assert r.status_code == 401


def test_without_enough_credits_nothing_is_queued_or_asked(hp, fake):
    r = unlock(hp, "u")
    assert r.status_code == 402 and r.json()["error"]["code"] == "quota_exceeded"
    assert rows(hp, Job) == [] and rows(hp, PlaybookUnlock) == []
    assert fake.requests == []


def test_an_unknown_repository_costs_nothing(hp, fake):
    gift(hp, "u")
    r = unlock(hp, "u", "nobody/nothing")
    assert r.status_code == 404
    assert balance(hp, "u")["purchased"] == 1
    assert fake.requests == []


# --- unlocking ----------------------------------------------------------------------------


def test_unlocking_writes_the_playbook_and_charges_once(hp, fake):
    gift(hp, "u")
    r = unlock(hp, "u")
    assert r.status_code == 202
    body = wait(hp, r.json()["job_id"])
    assert body["status"] == "done", body
    pb = body["playbook"]
    assert pb["repo"] == "pallets/flask" and pb["window_days"] == 365
    assert "model" not in pb and pb["note"].startswith("Only 5")
    must = pb["sections"]["must_do"]
    # The blank item is dropped; internal fact ids never leave the server.
    assert [m["text"][:10] for m in must] == ["Add or cha", "Pass `main"]
    assert must[0]["sources"][0] == {
        "statement": "34 of 44 merged pull requests that changed code also added or changed tests.",
        "seen": 34, "of": 44, "links": ["https://github.com/pallets/flask/pull/3876"]}
    assert "fact_id" not in json.dumps(pb)
    reason = pb["sections"]["closing_reasons"][0]
    assert (reason["seen"], reason["of"], reason["examples"][0]["who"]) == (13, 25, "davidism")

    (req,) = fake.requests
    assert str(req.url) == f"{URL}/v1/playbook"
    assert json.loads(req.content) == {"repo": "pallets/flask", "days": 365, "refresh": False}
    assert req.headers["X-Holt-Pro-Key"] == KEY and req.headers["X-Holt-User"] == "u"
    assert req.headers["X-Request-Id"] == r.json()["job_id"]

    assert balance(hp, "u")["purchased"] == 0
    s = state(hp, user="u")
    assert s["unlocked"] is True and s["playbook"] == pb and s["job"] is None

    # Asking again is free and served from the cache.
    again = unlock(hp, "u")
    assert again.status_code == 200 and again.json() == {"status": "done", "playbook": pb}
    assert len(fake.requests) == 1
    spends = rows(hp, CreditEvent, CreditEvent.kind == "spend")
    assert [(e.feature, e.amount, e.source) for e in spends] == [("playbook", -1, "purchased")]


def test_others_see_the_teaser_and_pay_to_read_the_cached_one(hp, fake):
    gift(hp, "a")
    wait(hp, unlock(hp, "a").json()["job_id"])

    anon = state(hp)
    assert anon["playbook"] is None and anon["unlocked"] is False
    t = anon["teaser"]
    assert t["sections"] == [{"key": "must_do", "count": 2},
                             {"key": "closing_reasons", "count": 1},
                             {"key": "checklist", "count": 1}]
    assert t["first"]["text"].startswith("Add or change tests")
    assert t["generated_at"] == "2026-09-28T10:00:00+00:00"

    gift(hp, "b")
    r = unlock(hp, "b")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert len(fake.requests) == 1  # from the cache: no second call to the service
    assert balance(hp, "b")["purchased"] == 0
    assert state(hp, user="b")["playbook"] is not None


def test_a_stale_playbook_is_written_again_free_for_those_who_unlocked(hp, fake):
    gift(hp, "u")
    wait(hp, unlock(hp, "u").json()["job_id"])

    async def age():
        async with hp.svc.db.session() as s:
            await s.execute(update(Playbook).values(created_at=now() - timedelta(days=30)))
            await s.commit()

    hp.client.portal.call(age)
    r = unlock(hp, "u")
    assert r.status_code == 202
    assert wait(hp, r.json()["job_id"])["status"] == "done"
    assert len(fake.requests) == 2
    assert len(rows(hp, CreditEvent, CreditEvent.kind == "spend")) == 1


def test_people_unlocking_at_once_share_one_job(hp, fake):
    fake.gate.clear()
    gift(hp, "a")
    gift(hp, "b")
    first = unlock(hp, "a").json()["job_id"]
    wait_for_requests(fake, 1)
    second = unlock(hp, "b")
    assert second.status_code == 202 and second.json()["job_id"] == first
    # While it runs, the page can pick the job up again.
    job = state(hp, user="b")["job"]
    assert job["job_id"] == first and job["status"] == "running"
    fake.gate.set()
    assert wait(hp, first)["status"] == "done"
    assert len(fake.requests) == 1
    assert state(hp, user="a")["playbook"] and state(hp, user="b")["playbook"]
    assert balance(hp, "a")["purchased"] == balance(hp, "b")["purchased"] == 0


# --- failures give everything back -----------------------------------------------------------


@pytest.mark.parametrize("status, code, words", [
    (502, "upstream", "GitHub or the writing model"),
    (503, "unavailable", "unavailable right now"),
    (401, "unauthorized", "unavailable right now"),
    (500, "internal", "unavailable right now"),
])
def test_a_failed_playbook_is_refunded_to_everyone_waiting(hp, fake, status, code, words):
    fake.gate.clear()
    fake.answer = httpx.Response(status, json={"error": {"code": code, "message": "dev"}})
    gift(hp, "a")
    gift(hp, "b")
    job_id = unlock(hp, "a").json()["job_id"]
    wait_for_requests(fake, 1)
    assert unlock(hp, "b").json()["job_id"] == job_id
    fake.gate.set()
    body = wait(hp, job_id)
    assert body["status"] == "error"
    assert body["error"]["code"] == "upstream"
    assert words in body["error"]["message"] and "weren't charged" in body["error"]["message"]
    assert "dev" not in body["error"]["message"]
    assert balance(hp, "a")["purchased"] == balance(hp, "b")["purchased"] == 1
    assert rows(hp, PlaybookUnlock) == [] and rows(hp, Playbook) == []
    refunds = rows(hp, CreditEvent, CreditEvent.kind == "refund")
    assert sorted(e.user_id for e in refunds) == ["a", "b"]
    assert state(hp, user="a")["unlocked"] is False


def test_a_repository_the_service_cant_find_is_not_found(hp, fake):
    fake.answer = httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})
    gift(hp, "u")
    body = wait(hp, unlock(hp, "u").json()["job_id"])
    assert body["error"]["code"] == "not_found"
    assert "pallets/flask" in body["error"]["message"]
    assert balance(hp, "u")["purchased"] == 1


def test_an_answer_that_isnt_a_playbook_is_refunded(hp, fake):
    fake.answer = httpx.Response(200, json={"repo": "pallets/flask", "sections": {
        "closing_reasons": [{"reason": "x", "seen": "many", "of": 3}]}})
    gift(hp, "u")
    body = wait(hp, unlock(hp, "u").json()["job_id"])
    assert body["status"] == "error" and body["error"]["code"] == "upstream"
    assert balance(hp, "u")["purchased"] == 1


def test_a_playbook_that_takes_too_long_is_stopped_and_refunded(make_harness, fake):
    h = make_harness(HOLT_PRO_URL=URL, HOLT_PRO_KEY=KEY, HOLT_JOB_TIMEOUT_AI=0.3)
    asyncio.run(h.svc.pro.aclose())
    h.svc.pro = pro.ProClient(URL, KEY, transport=httpx.MockTransport(fake), retry_delay=0)
    fake.gate.clear()
    gift(h, "u")
    body = wait(h, unlock(h, "u").json()["job_id"])
    fake.gate.set()
    assert body["status"] == "error" and "took too long" in body["error"]["message"]
    assert balance(h, "u")["purchased"] == 1


def test_refunding_twice_gives_back_once(hp, fake):
    fake.gate.clear()
    gift(hp, "u")
    job_id = unlock(hp, "u").json()["job_id"]
    wait_for_requests(fake, 1)

    async def refund_twice():
        async with hp.svc.db.session() as s:
            first = await playbook.refund_unlocks(s, job_id)
            second = await playbook.refund_unlocks(s, job_id)
            await s.commit()
            return first, second

    assert hp.client.portal.call(refund_twice) == (1, 0)
    fake.gate.set()
    wait(hp, job_id)
    assert balance(hp, "u")["purchased"] == 1


# --- the events stream ---------------------------------------------------------------------


def test_events_end_with_the_playbook(hp):
    gift(hp, "u")
    job_id = unlock(hp, "u").json()["job_id"]
    wait(hp, job_id)
    r = hp.get(f"/v1/playbook-jobs/{job_id}/events")
    assert r.status_code == 200
    assert "event: done" in r.text and '"playbook"' in r.text
    assert hp.get(f"/v1/analyses/{job_id}").status_code == 404


@pytest.mark.parametrize("status, code, held", [
    (503, "unavailable", 0), (404, "not_found", 0), (502, "upstream", 50_000)])
def test_the_ai_budget_hold_comes_back_only_before_a_model_call(hp, fake, status, code, held):
    from holt_server.db import AiBudget

    fake.answer = httpx.Response(status, json={"error": {"code": code, "message": "m"}})
    gift(hp, "u")
    assert wait(hp, unlock(hp, "u").json()["job_id"])["status"] == "error"
    assert rows(hp, AiBudget)[0].committed_micros == held
