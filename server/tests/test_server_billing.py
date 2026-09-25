"""Billing: plans, checkout, signatures, webhooks, subscription states, quota pools.

The real `Razorpay` class runs, so its signature code is what is tested. Only
its HTTP client is swapped for an in-process fake of the Razorpay API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from holt_server.billing.razorpay import Razorpay
from holt_server.db import (
    PAID_PRIORITY,
    USER_PRIORITY,
    Job,
    Payment,
    Subscription,
    User,
)
from holt_server.errors import ApiError
from sqlalchemy import select, update

KEY_ID, KEY_SECRET, WEBHOOK_SECRET = "rzp_test_key", "test-key-secret", "test-webhook-secret"
DAY = 86400


def hmac_hex(secret: str, message: str | bytes) -> str:
    data = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class FakeRazorpayApi:
    """Answers the handful of Razorpay endpoints the server calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.orders = 0
        self.subs = 0
        self.subscription_state: dict[str, dict] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        path = request.url.path.removeprefix("/v1")
        self.calls.append((request.method, path, body))
        assert request.headers["authorization"].startswith("Basic ")
        if path == "/orders":
            self.orders += 1
            return httpx.Response(200, json={"id": f"order_{self.orders}", "amount": body["amount"],
                                             "currency": body["currency"], "status": "created"})
        if path == "/subscriptions":
            self.subs += 1
            sid = f"sub_{self.subs}"
            self.subscription_state[sid] = {"id": sid, "status": "created",
                                            "short_url": f"https://rzp.io/i/{sid}"}
            return httpx.Response(200, json=self.subscription_state[sid])
        if path.startswith("/subscriptions/") and path.endswith("/cancel"):
            sid = path.split("/")[2]
            return httpx.Response(200, json={**self.subscription_state[sid], "status": "active"})
        if path.startswith("/subscriptions/"):
            return httpx.Response(200, json=self.subscription_state[path.split("/")[2]])
        return httpx.Response(404, json={"error": {"description": "no such path"}})


@pytest.fixture
def bh(make_harness):
    """A harness with Razorpay configured against the fake API."""
    h = make_harness(OPENROUTER_API_KEY="sk-or-server", RAZORPAY_KEY_ID=KEY_ID,
                     RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    api = FakeRazorpayApi()
    h.svc.payments = Razorpay(KEY_ID, KEY_SECRET, WEBHOOK_SECRET,
                              client=httpx.Client(transport=httpx.MockTransport(api)))
    h.api = api
    return h


def me(h, user):
    return h.get("/v1/me", user=user).json()


def rows(h, model):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model))).scalars().all()
    return h.client.portal.call(q)


def set_user(h, user_id, **values):
    async def q():
        async with h.svc.db.session() as s:
            await s.execute(update(User).where(User.id == user_id).values(**values))
            await s.commit()
    h.get("/v1/me", user=user_id)  # make sure the row exists
    h.client.portal.call(q)


def webhook(h, event: str, payload: dict, event_id: str | None = "evt_1",
            secret: str = WEBHOOK_SECRET, body: bytes | None = None, signature=None):
    raw = body if body is not None else json.dumps(
        {"entity": "event", "event": event, "payload": payload}).encode()
    headers = {"Content-Type": "application/json",
               "X-Razorpay-Signature": signature if signature is not None
               else hmac_hex(secret, raw)}
    if event_id:
        headers["X-Razorpay-Event-Id"] = event_id
    return h.client.post("/webhooks/razorpay", content=raw, headers=headers)


def payment_entity(pid, order_id=None, amount=4900, currency="INR", status="captured",
                   subscription_id=None):
    return {"payment": {"entity": {"id": pid, "order_id": order_id, "amount": amount,
                                   "currency": currency, "status": status,
                                   "subscription_id": subscription_id}}}


def sub_entity(sid, status="active", start=None, end=None):
    start = start if start is not None else int(time.time()) - 60
    end = end if end is not None else start + 30 * DAY
    return {"subscription": {"entity": {"id": sid, "status": status,
                                        "current_start": start, "current_end": end}}}


def buy_pack(h, user="buyer"):
    r = h.post("/v1/billing/checkout", {"pack": "pack10"}, user=user)
    assert r.status_code == 200, r.text
    return r.json()


def start_subscription(h, user="subber", plan="student"):
    r = h.post("/v1/billing/checkout", {"plan": plan}, user=user)
    assert r.status_code == 200, r.text
    return r.json()["subscription_id"]


# --- plans and checkout -----------------------------------------------------------------


def test_plans_are_public_via_the_bff(bh):
    assert bh.client.get("/v1/plans").status_code == 401  # internal key still needed
    body = bh.get("/v1/plans").json()
    assert [p["id"] for p in body["plans"]] == ["free", "student", "pro"]
    student = body["plans"][1]
    assert student["prices"] == [{"currency": "INR", "amount": 9900, "interval": "month"}]
    assert "razorpay_plan_id" not in json.dumps(body)
    assert body["packs"][0] == {"id": "pack10", "name": "10 AI reports", "reports": 10,
                                "prices": [{"currency": "INR", "amount": 4900}]}
    assert body["byok"] == {"price": 0, "unlimited": True}
    assert body["provider"] == "razorpay"
    assert body["tax_note"] == "" and body["tax_notes"] == {}


def test_shipped_plans_file_loads():
    from holt_server import plans

    catalog = plans.load(plans.DEFAULT_FILE)
    assert catalog.free.ai_reports_per_month == 3
    assert catalog.plans["student"].price("INR").amount == 9900
    assert catalog.plans["pro"].price("USD").amount == 500
    assert catalog.packs["pack10"].reports == 10


def test_razorpay_plan_id_from_env(tmp_path, monkeypatch):
    from holt_server import plans

    monkeypatch.setenv("RAZORPAY_PLAN_STUDENT_INR", "plan_from_env")
    assert plans.load(plans.DEFAULT_FILE).plans["student"].price("INR").razorpay_plan_id \
        == "plan_from_env"


def test_billing_off_without_keys(h):
    r = h.post("/v1/billing/checkout", {"pack": "pack10"}, user="u1")
    assert r.status_code == 501 and r.json()["error"]["code"] == "not_implemented"
    assert h.get("/v1/plans").json()["provider"] is None


def test_checkout_needs_sign_in_and_one_item(bh):
    assert bh.post("/v1/billing/checkout", {"pack": "pack10"}).status_code == 401
    assert bh.post("/v1/billing/checkout", {"pack": "pack10", "plan": "pro"},
                   user="u1").status_code == 400
    assert bh.post("/v1/billing/checkout", {}, user="u1").status_code == 400
    r = bh.post("/v1/billing/checkout", {"plan": "free"}, user="u1")
    assert r.json()["error"]["code"] == "invalid_request"
    r = bh.post("/v1/billing/checkout", {"pack": "pack10", "currency": "USD"}, user="u1")
    assert r.json()["error"]["code"] == "invalid_request"
    # Priced in USD but no Razorpay plan set up for it yet.
    r = bh.post("/v1/billing/checkout", {"plan": "pro", "currency": "USD"}, user="u1")
    assert r.status_code == 501


def test_pack_checkout_creates_an_order_and_grants_nothing(bh):
    body = buy_pack(bh)
    assert body == {"provider": "razorpay", "key_id": KEY_ID, "currency": "INR",
                    "kind": "order", "order_id": "order_1", "amount": 4900,
                    "name": "Holt", "description": "10 AI reports"}
    method, path, sent = bh.api.calls[-1]
    assert (method, path, sent["amount"], sent["currency"]) == ("POST", "/orders", 4900, "INR")
    assert sent["notes"] == {"user_id": "buyer", "pack": "pack10"}
    [payment] = rows(bh, Payment)
    assert (payment.status, payment.amount, payment.currency, payment.credited) == (
        "created", 4900, "INR", False)
    assert me(bh, "buyer")["pack_credits"] == 0


# --- signature verification -------------------------------------------------------------


def verify_order(h, order_id, pid, signature=None, user="buyer"):
    sig = signature if signature is not None else hmac_hex(KEY_SECRET, f"{order_id}|{pid}")
    return h.post("/v1/billing/verify", {"razorpay_order_id": order_id,
                                         "razorpay_payment_id": pid,
                                         "razorpay_signature": sig}, user=user)


def test_verify_valid_signature_credits_once(bh):
    order = buy_pack(bh)["order_id"]
    r = verify_order(bh, order, "pay_1")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"
    assert r.json()["me"]["pack_credits"] == 10
    # Replayed: same signed payload again. Nothing more.
    assert verify_order(bh, order, "pay_1").status_code == 200
    assert me(bh, "buyer")["pack_credits"] == 10
    [payment] = rows(bh, Payment)
    assert (payment.status, payment.provider_payment_id, payment.credited) == (
        "paid", "pay_1", True)


def test_verify_invalid_signature_changes_nothing(bh):
    order = buy_pack(bh)["order_id"]
    for sig in ("0" * 64, "", hmac_hex("wrong-secret", f"{order}|pay_1"),
                hmac_hex(KEY_SECRET, f"{order}|pay_OTHER")):
        r = verify_order(bh, order, "pay_1", signature=sig)
        assert r.status_code == 400
        assert r.json()["error"]["code"] in ("invalid_signature", "invalid_request")
    assert me(bh, "buyer")["pack_credits"] == 0
    assert rows(bh, Payment)[0].status == "created"


def test_verify_someone_elses_order_is_not_found(bh):
    order = buy_pack(bh, user="buyer")["order_id"]
    r = verify_order(bh, order, "pay_1", user="thief")
    assert r.status_code == 404
    assert me(bh, "thief")["pack_credits"] == 0
    assert me(bh, "buyer")["pack_credits"] == 0


def test_one_payment_id_cannot_credit_two_orders(bh):
    first = buy_pack(bh)["order_id"]
    second = buy_pack(bh)["order_id"]
    assert verify_order(bh, first, "pay_1").status_code == 200
    # A correctly signed pair for the second order but a reused payment id.
    assert verify_order(bh, second, "pay_1").status_code == 400
    assert me(bh, "buyer")["pack_credits"] == 10


# --- webhooks ------------------------------------------------------------------------------


def test_webhook_rejects_bad_signatures(bh):
    order = buy_pack(bh)["order_id"]
    payload = payment_entity("pay_1", order)
    assert webhook(bh, "payment.captured", payload, secret="nope").status_code == 400
    assert webhook(bh, "payment.captured", payload, signature="").status_code == 400
    raw = json.dumps({"event": "payment.captured", "payload": payload}).encode()
    tampered = raw.replace(b"4900", b"9900")
    r = webhook(bh, "", {}, body=tampered, signature=hmac_hex(WEBHOOK_SECRET, raw))
    assert r.status_code == 400
    assert me(bh, "buyer")["pack_credits"] == 0


def test_webhook_needs_no_internal_key_but_does_need_billing(h):
    r = h.client.post("/webhooks/razorpay", content=b"{}")
    assert r.status_code == 404  # billing not configured on this server


def test_webhook_credits_pack_once_across_events_and_replays(bh):
    order = buy_pack(bh)["order_id"]
    payload = payment_entity("pay_1", order)
    r = webhook(bh, "payment.captured", payload, event_id="evt_a")
    assert r.json() == {"ok": True, "result": "credited"}
    # The same delivery again (Razorpay retries, or someone replays it).
    assert webhook(bh, "payment.captured", payload, event_id="evt_a").json() == {
        "ok": True, "duplicate": True}
    # A different event about the same payment (order.paid follows payment.captured).
    assert webhook(bh, "order.paid", payload, event_id="evt_b").json()["result"] == "already"
    # And the browser's verify call arriving last.
    assert verify_order(bh, order, "pay_1").status_code == 200
    assert me(bh, "buyer")["pack_credits"] == 10


def test_webhook_without_event_id_dedupes_on_content(bh):
    order = buy_pack(bh)["order_id"]
    payload = payment_entity("pay_1", order)
    assert webhook(bh, "payment.captured", payload, event_id=None).json()["result"] == "credited"
    assert webhook(bh, "payment.captured", payload, event_id=None).json()["duplicate"]


def test_webhook_payment_id_reused_on_another_order_is_recorded_not_retried(bh):
    first = buy_pack(bh)["order_id"]
    second = buy_pack(bh)["order_id"]
    assert verify_order(bh, first, "pay_1").status_code == 200
    r = webhook(bh, "payment.captured", payment_entity("pay_1", second), event_id="evt_x")
    assert r.status_code == 200 and r.json()["result"] == "conflict"
    assert webhook(bh, "payment.captured", payment_entity("pay_1", second),
                   event_id="evt_x").json()["duplicate"]
    assert me(bh, "buyer")["pack_credits"] == 10


def test_webhook_amount_mismatch_is_not_credited(bh):
    order = buy_pack(bh)["order_id"]
    r = webhook(bh, "payment.captured", payment_entity("pay_1", order, amount=100))
    assert r.json()["result"] == "already"  # i.e. not credited
    assert me(bh, "buyer")["pack_credits"] == 0


def test_webhook_payment_failed(bh):
    order = buy_pack(bh)["order_id"]
    webhook(bh, "payment.failed", payment_entity("pay_1", order, status="failed"))
    assert rows(bh, Payment)[0].status == "failed"
    assert me(bh, "buyer")["pack_credits"] == 0


def test_webhook_for_unknown_order_is_ignored(bh):
    r = webhook(bh, "payment.captured", payment_entity("pay_x", "order_not_ours"))
    assert r.json()["result"] == "ignored"


# --- subscriptions ------------------------------------------------------------------------


def test_subscription_checkout(bh):
    sid = start_subscription(bh)
    method, path, sent = bh.api.calls[-1]
    assert (path, sent["plan_id"], sent["total_count"]) == ("/subscriptions",
                                                            "plan_student_inr", 120)
    [sub] = rows(bh, Subscription)
    assert (sub.provider_subscription_id, sub.plan, sub.amount, sub.status) == (
        sid, "student", 9900, "created")
    assert me(bh, "subber")["plan"] == "free"  # nothing granted until paid


def test_subscription_lifecycle(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    end1 = now + 30 * DAY

    webhook(bh, "subscription.authenticated", sub_entity(sid, "authenticated"), "e1")
    assert me(bh, "subber")["plan"] == "free"

    webhook(bh, "subscription.activated", sub_entity(sid, "active", now - 60, end1), "e2")
    m = me(bh, "subber")
    assert m["plan"] == "student" and m["quota"]["ai_limit"] == 3
    assert m["renews_at"] == datetime.fromtimestamp(end1, UTC).isoformat().replace("+00:00", "Z")
    assert m["ends_at"] is None

    # Renewal: a new cycle and its payment.
    end2 = end1 + 30 * DAY
    payload = {**sub_entity(sid, "active", end1, end2),
               **payment_entity("pay_s1", amount=9900, subscription_id=sid)}
    webhook(bh, "subscription.charged", payload, "e3")
    assert me(bh, "subber")["renews_at"].startswith(
        datetime.fromtimestamp(end2, UTC).strftime("%Y-%m-%d"))
    paid = [p for p in rows(bh, Payment) if p.kind == "subscription"]
    assert [(p.provider_payment_id, p.amount, p.status) for p in paid] == [("pay_s1", 9900, "paid")]
    # Replayed renewal under a new event id: state, not increments.
    webhook(bh, "subscription.charged", payload, "e3-again")
    assert len([p for p in rows(bh, Payment) if p.kind == "subscription"]) == 1

    # A failed renewal being retried: access continues.
    webhook(bh, "subscription.pending", sub_entity(sid, "pending", end1, end2), "e4")
    assert me(bh, "subber")["plan"] == "student"

    # Retries exhausted: access stops now.
    webhook(bh, "subscription.halted", sub_entity(sid, "halted", end1, end2), "e5")
    assert me(bh, "subber")["plan"] == "free"

    # A stale event for the same period (delivered late) must not revive it.
    webhook(bh, "subscription.activated", sub_entity(sid, "active", end1, end2), "e5b")
    webhook(bh, "subscription.charged", sub_entity(sid, "active", end1 - DAY, end1), "e5c")
    assert me(bh, "subber")["plan"] == "free"
    assert rows(bh, Subscription)[0].status == "halted"

    # They pay after all: a charge for a new period brings it back.
    end3 = end2 + 30 * DAY
    webhook(bh, "subscription.charged", {**sub_entity(sid, "active", end2, end3),
                                         **payment_entity("pay_s2", amount=9900,
                                                          subscription_id=sid)}, "e6")
    assert me(bh, "subber")["plan"] == "student"
    end2 = end3

    # Cancelled: keeps what was paid for, then stops renewing.
    webhook(bh, "subscription.cancelled", sub_entity(sid, "cancelled", end1, end2), "e7")
    m = me(bh, "subber")
    assert m["plan"] == "student" and m["renews_at"] is None and m["ends_at"]
    # A late "activated" cannot revive a cancelled subscription.
    webhook(bh, "subscription.activated", sub_entity(sid, "active", end1, end2 + 99), "e8")
    assert rows(bh, Subscription)[0].status == "cancelled"
    assert me(bh, "subber")["renews_at"] is None

    webhook(bh, "subscription.completed", sub_entity(sid, "completed", end1, end2), "e9")
    assert me(bh, "subber")["plan"] == "free"


def test_cancelled_after_period_end_revokes_at_once(bh):
    sid = start_subscription(bh)
    past = int(time.time()) - 5 * DAY
    webhook(bh, "subscription.activated", sub_entity(sid, "active", past - 30 * DAY, past), "a")
    webhook(bh, "subscription.cancelled", sub_entity(sid, "cancelled", past - 30 * DAY, past), "b")
    assert me(bh, "subber")["plan"] == "free"


def test_paid_access_lapses_after_grace_without_renewal(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    # Period ended two hours ago: still inside the 24h grace.
    webhook(bh, "subscription.activated", sub_entity(sid, "active", now - 30 * DAY,
                                                     now - 2 * 3600), "a")
    assert me(bh, "subber")["plan"] == "student"
    set_user(bh, "subber", plan_until=datetime.now(UTC) - timedelta(hours=30))
    assert me(bh, "subber")["plan"] == "free"


def test_webhook_for_unknown_subscription_is_ignored(bh):
    r = webhook(bh, "subscription.activated", sub_entity("sub_not_ours"))
    assert r.json()["result"] == "ignored"


def test_subscription_verify(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    bh.api.subscription_state[sid].update(status="active", current_start=now - 60,
                                          current_end=now + 30 * DAY)
    good = hmac_hex(KEY_SECRET, f"pay_s1|{sid}")
    body = {"razorpay_subscription_id": sid, "razorpay_payment_id": "pay_s1",
            "razorpay_signature": "f" * 64}
    assert bh.post("/v1/billing/verify", body, user="subber").status_code == 400
    assert me(bh, "subber")["plan"] == "free"
    # The order the parts are signed in matters (payment|subscription).
    body["razorpay_signature"] = hmac_hex(KEY_SECRET, f"{sid}|pay_s1")
    assert bh.post("/v1/billing/verify", body, user="subber").status_code == 400
    body["razorpay_signature"] = good
    assert bh.post("/v1/billing/verify", body, user="intruder").status_code == 404
    r = bh.post("/v1/billing/verify", body, user="subber")
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert r.json()["me"]["plan"] == "student"


def test_subscription_verify_before_first_charge_grants_nothing(bh):
    sid = start_subscription(bh)
    bh.api.subscription_state[sid].update(status="authenticated")
    r = bh.post("/v1/billing/verify", {"razorpay_subscription_id": sid,
                                       "razorpay_payment_id": "pay_s1",
                                       "razorpay_signature": hmac_hex(KEY_SECRET,
                                                                      f"pay_s1|{sid}")},
                user="subber")
    assert r.json()["status"] == "authenticated" and r.json()["me"]["plan"] == "free"


def test_already_subscribed_then_cancel(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    webhook(bh, "subscription.activated", sub_entity(sid, "active", now, now + 30 * DAY))
    r = bh.post("/v1/billing/checkout", {"plan": "pro"}, user="subber")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_subscribed"

    r = bh.post("/v1/billing/cancel", user="subber")
    assert r.status_code == 200
    assert r.json()["plan"] == "student" and r.json()["renews_at"] is None
    assert r.json()["ends_at"]
    method, path, sent = bh.api.calls[-1]
    assert (path, sent) == (f"/subscriptions/{sid}/cancel", {"cancel_at_cycle_end": 1})
    assert bh.post("/v1/billing/cancel", user="subber").status_code == 404
    # Once cancelled they may pick another plan.
    assert bh.post("/v1/billing/checkout", {"plan": "pro"}, user="subber").status_code == 200


def test_new_cycle_resets_the_allowance(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    webhook(bh, "subscription.activated", sub_entity(sid, "active", now - 60, now + DAY), "a")
    job = bh.post("/v1/analyses", {"repo": "octo/one", "mode": "ai"}, user="subber").json()
    bh.wait(job["job_id"])
    assert me(bh, "subber")["quota"]["ai_used"] == 1
    webhook(bh, "subscription.charged", sub_entity(sid, "active", now + DAY, now + 31 * DAY),
            "b")
    assert me(bh, "subber")["quota"]["ai_used"] == 0


# --- quota pools and priority -----------------------------------------------------------


def ai(h, repo, user):
    return h.post("/v1/analyses", {"repo": repo, "mode": "ai"}, user=user)


def job_row(h, job_id):
    return next(j for j in rows(h, Job) if j.id == job_id)


def test_allowance_first_then_pack_then_exceeded(make_harness):
    h = make_harness(run_jobs=False, OPENROUTER_API_KEY="sk-or-server")
    set_user(h, "p1", pack_credits=1)
    pools = []
    for repo in ("octo/one", "octo/two", "octo/three"):
        r = ai(h, repo, "p1")
        assert r.status_code == 202, r.text
        pools.append(job_row(h, r.json()["job_id"]).quota_pool)
    assert pools == ["plan", "plan", "pack"]
    m = me(h, "p1")
    assert m["quota"]["ai_used"] == 2 and m["pack_credits"] == 0
    r = ai(h, "octo/four", "p1")
    assert r.status_code == 402 and r.json()["error"]["code"] == "quota_exceeded"
    assert "pack" in r.json()["error"]["message"]


def test_refunds_go_back_to_the_pool_that_paid(make_harness):
    h = make_harness(run_jobs=False, OPENROUTER_API_KEY="sk-or-server")
    set_user(h, "p2", pack_credits=1)
    ids = [ai(h, r, "p2").json()["job_id"] for r in ("octo/one", "octo/two", "octo/three")]
    runner = h.svc.runner
    claimed = {}
    for _ in ids:
        job = h.client.portal.call(runner._claim)
        claimed[job.id] = job
    h.client.portal.call(runner._fail, claimed[ids[2]], ApiError("upstream", "x"))  # pack
    assert me(h, "p2")["pack_credits"] == 1 and me(h, "p2")["quota"]["ai_used"] == 2
    h.client.portal.call(runner._fail, claimed[ids[0]], ApiError("upstream", "x"))  # plan
    assert me(h, "p2")["pack_credits"] == 1 and me(h, "p2")["quota"]["ai_used"] == 1


def test_byok_is_free_and_unlimited(make_harness):
    h = make_harness(run_jobs=False, OPENROUTER_API_KEY="sk-or-server")
    h.put("/v1/me/byok", {"provider": "openai", "api_key": "sk-openai-123456"}, user="b1")
    for repo in ("octo/one", "octo/two", "octo/three", "octo/four"):
        assert ai(h, repo, "b1").status_code == 202
    assert me(h, "b1")["quota"]["ai_used"] == 0


def test_paid_users_jump_the_queue(bh):
    sid = start_subscription(bh, user="vip")
    now = int(time.time())
    webhook(bh, "subscription.activated", sub_entity(sid, "active", now, now + 30 * DAY))
    bh.engine.gate.clear()
    try:
        free_job = ai(bh, "octo/one", "someone").json()["job_id"]
        paid_job = ai(bh, "octo/two", "vip").json()["job_id"]
        assert job_row(bh, free_job).priority == USER_PRIORITY
        assert job_row(bh, paid_job).priority == PAID_PRIORITY
        # A paid user asking the same question promotes the waiting job.
        rules = bh.post("/v1/analyses", {"repo": "octo/three"}).json()["job_id"]
        assert bh.post("/v1/analyses", {"repo": "octo/three"}, user="vip").json()["job_id"] \
            == rules
        assert job_row(bh, rules).priority == PAID_PRIORITY
    finally:
        bh.engine.gate.set()


def test_manual_plan_grant_does_not_lapse(make_harness):
    h = make_harness(run_jobs=False)
    set_user(h, "staff", plan="pro")
    m = me(h, "staff")
    assert m["plan"] == "pro" and m["quota"]["ai_limit"] == 5
    assert m["renews_at"] is None and m["ends_at"] is None


# --- review fixes -------------------------------------------------------------------------


def refund_body(refund_id, payment_id, amount, created_at=1):
    return {"refund": {"entity": {"id": refund_id, "payment_id": payment_id,
                                  "amount": amount, "currency": "INR",
                                  "created_at": created_at}}}


def dispute_body(dispute_id, payment_id, amount=4900):
    return {"dispute": {"entity": {"id": dispute_id, "payment_id": payment_id,
                                   "amount": amount, "currency": "INR"}}}


def paid_pack(h, user="buyer", pid="pay_1"):
    order = buy_pack(h, user=user)["order_id"]
    assert verify_order(h, order, pid, user=user).status_code == 200
    return order


def test_old_subscription_cannot_touch_a_newer_one(bh):
    now = int(time.time())
    old = start_subscription(bh, user="switcher", plan="student")
    webhook(bh, "subscription.activated", sub_entity(old, "active", now - DAY, now + 10 * DAY))
    assert bh.post("/v1/billing/cancel", user="switcher").status_code == 200
    new = start_subscription(bh, user="switcher", plan="pro")
    assert new != old
    webhook(bh, "subscription.activated", sub_entity(new, "active", now, now + 30 * DAY))
    m = me(bh, "switcher")
    assert m["plan"] == "pro"
    until = m["renews_at"]

    # The old subscription's endings, and a late charge from it, change nothing.
    webhook(bh, "subscription.charged", sub_entity(old, "active", now + 10 * DAY,
                                                   now + 40 * DAY))
    for kind in ("halted", "cancelled", "completed"):
        webhook(bh, f"subscription.{kind}", sub_entity(old, kind, now - DAY, now + 10 * DAY))
        m = me(bh, "switcher")
        assert (m["plan"], m["renews_at"]) == ("pro", until), kind

    # The granting subscription's own end still ends it.
    webhook(bh, "subscription.halted", sub_entity(new, "halted", now, now + 30 * DAY))
    assert me(bh, "switcher")["plan"] == "free"


def test_event_id_header_is_not_trusted_for_dedupe(bh):
    order = buy_pack(bh)["order_id"]
    payload = payment_entity("pay_1", order)
    assert webhook(bh, "payment.captured", payload, event_id="a").json()["result"] == "credited"
    # Same signed body, different (unsigned) header id: still a duplicate.
    assert webhook(bh, "payment.captured", payload, event_id="b").json()["duplicate"]


def test_oversized_webhook_bodies_are_refused_unread(bh):
    big = b"{" + b" " * (1024 * 1024 + 10) + b"}"
    r = bh.client.post("/webhooks/razorpay", content=big,
                       headers={"X-Razorpay-Signature": hmac_hex(WEBHOOK_SECRET, big)})
    assert r.status_code == 413

    def chunks():  # no Content-Length: sent chunked
        for _ in range(20):
            yield b" " * 65536

    r = bh.client.post("/webhooks/razorpay", content=chunks(),
                       headers={"X-Razorpay-Signature": "0" * 64})
    assert r.status_code == 413


def test_full_pack_refund_takes_back_unspent_credits(bh):
    paid_pack(bh)
    set_user(bh, "buyer", pack_credits=3)  # seven already used
    r = webhook(bh, "refund.processed", {**refund_body("rfnd_1", "pay_1", 4900),
                                         **payment_entity("pay_1")})
    assert r.json()["result"] == "refunded"
    assert me(bh, "buyer")["pack_credits"] == 0
    payment = rows(bh, Payment)[0]
    assert (payment.status, payment.refunded_amount) == ("refunded", 4900)


def test_partial_refunds_add_up_and_apply_once(bh):
    paid_pack(bh)
    webhook(bh, "refund.processed", refund_body("rfnd_1", "pay_1", 490))
    assert me(bh, "buyer")["pack_credits"] == 9
    # Same refund again in a different delivery (different body): once only.
    r = webhook(bh, "refund.processed", refund_body("rfnd_1", "pay_1", 490, created_at=2))
    assert r.json()["result"] == "already"
    assert me(bh, "buyer")["pack_credits"] == 9
    webhook(bh, "refund.processed", refund_body("rfnd_2", "pay_1", 1000))
    assert me(bh, "buyer")["pack_credits"] == 6  # ceil(10 * 1000 / 4900) = 3
    payment = rows(bh, Payment)[0]
    assert (payment.status, payment.refunded_amount) == ("partially_refunded", 1490)


def test_refund_of_subscription_payment(bh):
    sid = start_subscription(bh)
    now = int(time.time())
    webhook(bh, "subscription.charged", {**sub_entity(sid, "active", now, now + 30 * DAY),
                                         **payment_entity("pay_s1", amount=9900,
                                                          subscription_id=sid)})
    webhook(bh, "refund.processed", refund_body("rfnd_s1", "pay_s1", 5000))
    assert me(bh, "subber")["plan"] == "student"  # partial: plan stays
    webhook(bh, "refund.processed", refund_body("rfnd_s2", "pay_s1", 4900))
    assert me(bh, "subber")["plan"] == "free"  # now fully refunded


def test_refund_for_unknown_payment_is_ignored(bh):
    r = webhook(bh, "refund.processed", refund_body("rfnd_x", "pay_unknown", 100))
    assert r.json()["result"] == "ignored"


def test_dispute_freezes_pack_credits_until_resolved(make_harness):
    h = make_harness(OPENROUTER_API_KEY="sk-or-server", RAZORPAY_KEY_ID=KEY_ID,
                     RAZORPAY_KEY_SECRET=KEY_SECRET, RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
    h.svc.payments = Razorpay(KEY_ID, KEY_SECRET, WEBHOOK_SECRET, client=httpx.Client(
        transport=httpx.MockTransport(FakeRazorpayApi())))
    paid_pack(h, user="d1")
    set_user(h, "d1", ai_used=2, ai_period=datetime.now(UTC).strftime("%Y-%m"))  # allowance spent
    r = webhook(h, "payment.dispute.created", dispute_body("disp_1", "pay_1"))
    assert r.json()["result"] == "disputed"
    assert rows(h, Payment)[0].disputed is True
    r = ai(h, "octo/one", "d1")
    assert r.json()["error"]["code"] == "quota_exceeded"  # credits frozen
    assert me(h, "d1")["pack_credits"] == 10

    webhook(h, "payment.dispute.won", dispute_body("disp_1", "pay_1"))
    assert ai(h, "octo/one", "d1").status_code == 202  # spendable again


def test_lost_dispute_is_a_refund(bh):
    paid_pack(bh)
    webhook(bh, "payment.dispute.created", dispute_body("disp_1", "pay_1"))
    webhook(bh, "payment.dispute.lost", dispute_body("disp_1", "pay_1"))
    assert me(bh, "buyer")["pack_credits"] == 0
    user = [u for u in rows(bh, User) if u.id == "buyer"][0]
    assert user.packs_frozen is False
    assert rows(bh, Payment)[0].status == "refunded"


def test_repeat_checkout_reuses_the_open_subscription(bh):
    first = start_subscription(bh)
    assert start_subscription(bh) == first
    assert [c[1] for c in bh.api.calls].count("/subscriptions") == 1


def test_switching_plan_mid_checkout_cancels_the_old_one(bh):
    first = start_subscription(bh, plan="student")
    second = start_subscription(bh, plan="pro")
    assert second != first
    cancels = [c for c in bh.api.calls if c[1] == f"/subscriptions/{first}/cancel"]
    assert cancels and cancels[0][2] == {"cancel_at_cycle_end": 0}
    status = {s.provider_subscription_id: s.status for s in rows(bh, Subscription)}
    assert status == {first: "cancelled", second: "created"}


def test_one_live_subscription_per_user_is_enforced(bh, monkeypatch):
    from holt_server.billing import routes

    start_subscription(bh)

    async def none(svc, user_id):  # as if a concurrent checkout had not been seen
        return None

    monkeypatch.setattr(routes, "_live_subscription", none)
    r = bh.post("/v1/billing/checkout", {"plan": "pro"}, user="subber")
    assert r.status_code == 409
    # The duplicate created at the provider was cancelled straight away.
    assert bh.api.calls[-1][1] == "/subscriptions/sub_2/cancel"
    assert [s.provider_subscription_id for s in rows(bh, Subscription)] == ["sub_1"]


def test_tax_notes_from_config(tmp_path):
    from holt_server import plans

    path = tmp_path / "p.toml"
    path.write_text('tax_note = "Taxes added at checkout."\n'
                    '[tax_notes]\nINR = "Includes 18% GST."\nUSD = ""\n'
                    '[plans.free]\nai_reports_per_month = 1\n', encoding="utf-8")
    body = plans.load(path).public()
    assert body["tax_note"] == "Taxes added at checkout."
    assert body["tax_notes"] == {"INR": "Includes 18% GST."}


def test_empty_internal_key_header_is_rejected(bh):
    for value in ("", " "):
        r = bh.client.get("/v1/plans", headers={"X-Holt-Internal-Key": value})
        assert r.status_code == 401, repr(value)
