"""PR pre-flight (holt_server/preflight.py) against a fake paid-features service.

The service is an httpx.MockTransport: nothing touches the network.
"""

from __future__ import annotations

import asyncio
import copy
import json
import threading
import time

import httpx
import pytest
from holt_server import credits, preflight, pro
from holt_server.db import CreditEvent, Job, Preflight
from holt_server.errors import ApiError
from sqlalchemy import select

KEY = "pro-secret-key-value"
URL = "http://pro:8000"
PR = "https://github.com/pallets/flask/pull/3878"

PRO_PREFLIGHT = {
    "repo": "pallets/flask",
    "version": 1,
    "cached": False,
    "checked_at": "2026-09-28T07:00:00+00:00",
    "target": {
        "kind": "pull_request", "number": 3878, "url": PR,
        "title": "Add `CliRunner.echo_stdin_class`", "author": "someone", "outside": True,
        "state": "open", "draft": False, "head": "someone:echo", "base": "main",
        "head_sha": "5f0c1111", "additions": 54, "deletions": 1, "lines": 55, "files": 4,
        "files_listed": True,
    },
    "evidence": {"version": 1, "fetched_at": "2026-09-28T06:00:00+00:00",
                 "window": {"days": 365, "since": "2025-09-28"},
                 "sample": {"group": "everyone"}},
    "archived": False,
    "note": "Only 5 merged pull requests from people outside the project turned up.",
    "checks": [
        {"id": "ci", "title": "Checks", "verdict": "ok",
         "statement": "Every check passed.", "facts": ["checks-1"], "links": [], "quote": None,
         "data": {"failed": []}},
        {"id": "issue", "title": "Linked issue", "verdict": "worth_fixing",
         "statement": "This pull request does not link an issue. 32 of 50 merged pull "
                      "requests linked to an issue or mentioned one by number.",
         "facts": ["issue_first-10"], "links": ["https://github.com/pallets/flask/pull/3866"],
         "quote": {"text": "Open an issue first.", "path": "CONTRIBUTING.md",
                   "url": "https://github.com/pallets/flask/blob/HEAD/CONTRIBUTING.md#L3"},
         "data": {"linked_issues": [], "mentions_issue": False}},
        {"id": "cla", "title": "CLA", "verdict": "some_new_value",
         "statement": "No CLA check has run yet.", "facts": [], "links": [], "quote": None,
         "data": {}},
    ],
    "counts": {"ok": 1, "worth_fixing": 1, "unknown": 0},
    "similar": {
        "number": 3728, "url": "https://github.com/pallets/flask/pull/3728",
        "title": "Add a stdin option", "author": "other", "outside": True, "lines": 40,
        "files": 3, "touched_tests": True, "reviewers": ["davidism"], "shared_files": [],
        "shared_folders": ["src/flask/"], "file_overlap": 0.0,
        "why": "It changed files in the same folders: `src/flask/`.",
    },
    "summary": None,
}


def answer(**target) -> httpx.Response:
    body = copy.deepcopy(PRO_PREFLIGHT)
    body["target"].update(target)
    return httpx.Response(200, json=body)


class FakePro:
    """The service's POST /v1/preflight: answers with `answer`, records
    requests, and holds each request while `gate` is cleared."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: httpx.Response = answer()
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


def with_pro(h, fake):
    asyncio.run(h.svc.pro.aclose())
    h.svc.pro = pro.ProClient(URL, KEY, transport=httpx.MockTransport(fake), retry_delay=0)
    return h


@pytest.fixture
def hp(make_harness, fake):
    return with_pro(make_harness(HOLT_PRO_URL=URL, HOLT_PRO_KEY=KEY), fake)


def call(h, fn, *args, **kw):
    """Run `fn` on the app's event loop (Postgres connections belong to it)."""
    async def go():
        return await fn(*args, **kw)

    return h.client.portal.call(go)


def gift(h, user: str, n: int = 1) -> None:
    call(h, credits.grant, h.svc, user, n, pool="purchased", reason="test", actor="test")


def purchased(h, user: str) -> int:
    return h.get("/v1/me/credits", user=user).json()["purchased"]


def rows(h, model, *where):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model).where(*where))).scalars().all()

    return h.client.portal.call(q)


def state(h, user: str | None = None, **q) -> dict:
    r = h.get("/v1/preflight", user=user, params=q)
    assert r.status_code == 200, r.text
    return r.json()


def start(h, user: str, **body):
    return h.post("/v1/me/preflight", json=body or {"pr_url": PR}, user=user)


def wait(h, job_id: str) -> dict:
    return h.wait(job_id, kind="preflight-jobs")


def wait_for_requests(fake: FakePro, n: int) -> None:
    deadline = time.monotonic() + 10
    while len(fake.requests) < n and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(fake.requests) >= n


# --- parsing ----------------------------------------------------------------------------


@pytest.mark.parametrize("raw, repo, number", [
    ("https://github.com/pallets/flask/pull/3878", "pallets/flask", 3878),
    ("github.com/pallets/flask/pull/3878/files?w=1", "pallets/flask", 3878),
    ("https://www.github.com/pallets/flask/pull/12#discussion_r1", "pallets/flask", 12),
    ("https://githolt.com/pallets/flask/pull/7", "pallets/flask", 7),
    ("pallets/flask#42", "pallets/flask", 42),
])
def test_pull_request_links_are_understood(raw, repo, number):
    t = preflight.parse(raw, None, None, None)
    assert (t.repo, t.number, t.key) == (repo, number, f"pr:{number}")
    assert t.body("pallets/flask") == {"pr": f"pallets/flask#{number}"}


@pytest.mark.parametrize("raw", [
    "https://github.com/pallets/flask", "https://github.com/pallets/flask/issues/3",
    "https://gitlab.com/pallets/flask/pull/3", "https://github.com/pallets/flask/pull/0",
    "not a link",
])
def test_other_links_are_refused_plainly(raw):
    with pytest.raises(ApiError) as e:
        preflight.parse(raw, None, None, None)
    assert e.value.code == "invalid_request" and "pull request link" in e.value.message


def test_branches_are_understood():
    t = preflight.parse(None, "https://github.com/tldr-pages/tldr", "someone:fix-wg", "main")
    assert (t.repo, t.key) == ("tldr-pages/tldr", "branch:someone:fix-wg...main")
    assert t.body("tldr-pages/tldr") == {"repo": "tldr-pages/tldr", "branch": "someone:fix-wg",
                                         "base": "main"}
    assert preflight.parse(None, "a/b", "feature/x", None).key == "branch:feature/x"


@pytest.mark.parametrize("pr, repo, branch, base", [
    (None, None, None, None), (PR, "a/b", "x", None), (None, "a/b", None, None),
    (None, "a/b", "../x", None), (None, "a/b", "-x", None), (None, "a/b", "x y", None),
    (None, "a/b", "x", "me:main"),
])
def test_bad_requests_are_refused(pr, repo, branch, base):
    with pytest.raises(ApiError) as e:
        preflight.parse(pr, repo, branch, base)
    assert e.value.code == "invalid_request"


# --- off ----------------------------------------------------------------------------------


def test_without_the_service_preflight_is_off(h):
    assert state(h, user="u") == {"available": False, "on_sale": False, "access": None,
                                  "target": None, "result": None, "job": None}
    r = start(h, "u")
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"


# --- before checking ------------------------------------------------------------------------


def test_anyone_can_see_it_is_on(hp):
    s = state(hp)
    assert s["available"] is True and s["access"] is None and s["result"] is None
    assert s["on_sale"] is False  # no pass in the shipped catalogue unlocks it


def test_signed_in_state_says_what_a_check_costs(hp):
    s = state(hp, user="u", pr=PR)
    assert s["target"] == {"repo": "pallets/flask", "number": 3878, "branch": None, "base": None}
    # Welcome credits are free ones, and pre-flight takes purchased credits only.
    assert (s["access"]["allowed"], s["access"]["cost"]) == (False, 1)
    gift(hp, "u")
    s = state(hp, user="u", pr=PR)
    assert (s["access"]["allowed"], s["access"]["via"]) == (True, "credits")


def test_a_bad_link_in_the_state_is_refused(hp):
    r = hp.get("/v1/preflight", user="u", params={"pr": "nope"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_signed_out_is_refused(hp):
    assert hp.post("/v1/me/preflight", json={"pr_url": PR}).status_code == 401


def test_unknown_fields_are_refused(hp):
    r = start(hp, "u", pr_url=PR, refresh=True)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_without_enough_credits_nothing_is_queued_or_asked(hp, fake):
    r = start(hp, "u")
    assert r.status_code == 402 and r.json()["error"]["code"] == "quota_exceeded"
    assert rows(hp, Job) == [] and fake.requests == []


def test_an_unknown_repository_costs_nothing(hp, fake):
    gift(hp, "u")
    r = start(hp, "u", pr_url="https://github.com/nobody/nothing/pull/1")
    assert r.status_code == 404
    assert purchased(hp, "u") == 1 and fake.requests == []


# --- checking ---------------------------------------------------------------------------------


def test_a_check_runs_charges_once_and_is_kept(hp, fake):
    gift(hp, "u")
    r = start(hp, "u")
    assert r.status_code == 202
    body = wait(hp, r.json()["job_id"])
    assert body["status"] == "done", body
    p = body["preflight"]
    assert p["repo"] == "pallets/flask" and p["window_days"] == 365
    assert p["target"]["number"] == 3878 and p["target"]["head_sha"] == "5f0c1111"
    assert [c["id"] for c in p["checks"]] == ["ci", "issue", "cla"]
    # A verdict this server doesn't know reads as "can't tell"; counts follow the checks.
    assert p["checks"][2]["verdict"] == "unknown"
    assert p["counts"] == {"ok": 1, "worth_fixing": 1, "unknown": 1}
    assert p["checks"][1]["quote"]["path"] == "CONTRIBUTING.md"
    assert p["similar"]["number"] == 3728 and p["similar"]["why"].startswith("It changed")
    assert p["free_recheck"] is False
    # Internal fields never leave the server.
    text = json.dumps(p)
    assert "issue_first-10" not in text and "mentions_issue" not in text
    assert "file_overlap" not in text

    (req,) = fake.requests
    assert str(req.url) == f"{URL}/v1/preflight"
    assert json.loads(req.content) == {"pr": "pallets/flask#3878", "days": 365,
                                       "summary": False, "refresh": False}
    assert req.headers["X-Holt-Pro-Key"] == KEY and req.headers["X-Holt-User"] == "u"
    assert req.headers["X-Request-Id"] == r.json()["job_id"]

    assert purchased(hp, "u") == 0
    s = state(hp, user="u", pr=PR)
    assert s["result"] == p and s["job"] is None
    # Someone else's check is theirs alone.
    assert state(hp, user="v", pr=PR)["result"] is None
    spends = rows(hp, CreditEvent, CreditEvent.kind == "spend")
    assert [(e.feature, e.amount) for e in spends] == [("preflight", -1)]


def test_a_branch_is_sent_as_a_branch(hp, fake):
    fake.answer = answer(kind="branch", number=None, state=None, outside=None,
                         url="https://github.com/pallets/flask/compare/main...me:x")
    gift(hp, "u")
    r = start(hp, "u", repo="pallets/flask", branch="me:x", summary=True)
    p = wait(hp, r.json()["job_id"])["preflight"]
    assert p["target"]["kind"] == "branch" and p["target"]["number"] is None
    assert json.loads(fake.requests[0].content) == {
        "repo": "pallets/flask", "branch": "me:x", "days": 365, "summary": True,
        "refresh": False}
    assert state(hp, user="u", repo="pallets/flask", branch="me:x")["result"] == p


def test_the_same_commit_again_is_free_and_a_new_one_is_charged(hp, fake):
    gift(hp, "u", 2)
    wait(hp, start(hp, "u").json()["job_id"])
    assert purchased(hp, "u") == 1

    again = wait(hp, start(hp, "u").json()["job_id"])["preflight"]
    assert again["free_recheck"] is True
    assert purchased(hp, "u") == 1
    assert len(rows(hp, Preflight)) == 1  # replaced, not added

    fake.answer = answer(head_sha="beefcafe")
    new = wait(hp, start(hp, "u").json()["job_id"])["preflight"]
    assert new["free_recheck"] is False and purchased(hp, "u") == 0
    assert state(hp, user="u", pr=PR)["result"]["target"]["head_sha"] == "beefcafe"
    assert len(rows(hp, Preflight)) == 2


def test_a_second_click_while_checking_joins_the_first(hp, fake):
    fake.gate.clear()
    gift(hp, "u", 2)
    first = start(hp, "u").json()["job_id"]
    wait_for_requests(fake, 1)
    second = start(hp, "u")
    assert second.status_code == 202 and second.json()["job_id"] == first
    job = state(hp, user="u", pr=PR)["job"]
    assert job["job_id"] == first and job["status"] == "running"
    fake.gate.set()
    assert wait(hp, first)["status"] == "done"
    assert len(fake.requests) == 1 and purchased(hp, "u") == 1


# --- failures give the credit back -------------------------------------------------------------


@pytest.mark.parametrize("status, code, out, words", [
    (502, "upstream", "upstream", "GitHub didn't answer"),
    (503, "unavailable", "upstream", "unavailable right now"),
    (401, "unauthorized", "upstream", "unavailable right now"),
    (500, "internal", "upstream", "unavailable right now"),
    (400, "invalid_request", "upstream", "Check the link"),
    (404, "not_found", "not_found", "couldn't find that pull request"),
])
def test_a_failed_check_is_refunded(hp, fake, status, code, out, words):
    fake.answer = httpx.Response(status, json={"error": {"code": code, "message": "dev"}})
    gift(hp, "u")
    body = wait(hp, start(hp, "u").json()["job_id"])
    assert body["status"] == "error" and body["error"]["code"] == out
    msg = body["error"]["message"]
    assert words in msg and "weren't charged" in msg and "dev" not in msg
    assert purchased(hp, "u") == 1 and rows(hp, Preflight) == []
    assert [e.user_id for e in rows(hp, CreditEvent, CreditEvent.kind == "refund")] == ["u"]


def test_an_answer_that_isnt_a_preflight_is_refunded(hp, fake):
    fake.answer = httpx.Response(200, json={"repo": "pallets/flask", "target": {"lines": "many"}})
    gift(hp, "u")
    body = wait(hp, start(hp, "u").json()["job_id"])
    assert body["status"] == "error" and body["error"]["code"] == "upstream"
    assert purchased(hp, "u") == 1


def test_a_check_that_takes_too_long_is_stopped_and_refunded(make_harness, fake):
    h = with_pro(make_harness(HOLT_PRO_URL=URL, HOLT_PRO_KEY=KEY, HOLT_JOB_TIMEOUT_AI=0.3), fake)
    fake.gate.clear()
    gift(h, "u")
    body = wait(h, start(h, "u").json()["job_id"])
    fake.gate.set()
    assert body["status"] == "error" and "took too long" in body["error"]["message"]
    assert purchased(h, "u") == 1


# --- the events stream -----------------------------------------------------------------------


def test_events_end_with_the_checks(hp):
    gift(hp, "u")
    job_id = start(hp, "u").json()["job_id"]
    wait(hp, job_id)
    r = hp.get(f"/v1/preflight-jobs/{job_id}/events")
    assert r.status_code == 200
    assert "event: done" in r.text and '"preflight"' in r.text
    assert hp.get(f"/v1/analyses/{job_id}").status_code == 404


@pytest.mark.parametrize("status, code, held", [
    (503, "unavailable", 0), (400, "invalid_request", 0), (500, "internal", 50_000)])
def test_a_summarys_budget_hold_comes_back_only_before_a_model_call(hp, fake, status, code, held):
    from holt_server.db import AiBudget

    fake.answer = httpx.Response(status, json={"error": {"code": code, "message": "m"}})
    gift(hp, "u")
    r = start(hp, "u", pr_url=PR, summary=True)
    assert r.status_code == 202, r.text
    assert wait(hp, r.json()["job_id"])["status"] == "error"
    assert rows(hp, AiBudget)[0].committed_micros == held
