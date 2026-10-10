"""Pro passes (payments.py): orders, the signed callback, the signed webhook,
and the switch that keeps it all off.

Razorpay is faked at the HTTP layer (`FakeRazorpay._call`), so the signature
checks are the real ones. Every test that pays ends on the invariant: one
`PlanEvent` per paid order, referencing its payment, and no credits.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from holt_server import entitlements, payments, pricing
from holt_server.db import CreditLot, Order, PlanEvent, now
from sqlalchemy import select

KEY_ID = "rzp_test_fake"
SECRET = "fake-key-secret"
HOOK_SECRET = "fake-webhook-secret"
PRICE = 9900

CATALOGUE = {
    "tbd": False,
    "features": {"ai_report": {"name": "AI-written report", "credits": 1, "free_credits": True},
                 "pr_watch": {"name": "PR watch", "credits": None},
                 "merge_plan": {"name": "Merge plan", "credits": None}},
    "plans": {"free": {"name": "Free", "features": {}},
              "pro": {"name": "Pro", "features": {"merge_plan": {"per_month": 30},
                                                  "pr_watch": {"unlimited": True}}}},
    "passes": {
        "pro_1m": {"name": "1 month", "days": 30, "on_sale": True,
                   "price": {"inr_paise": PRICE, "usd_cents": 700}},
        "pro_3m": {"name": "3 months", "days": 90, "on_sale": True,
                   "price": {"inr_paise": 24900}},
        "not_yet": {"name": "12 months", "days": 365, "on_sale": False,
                    "price": {"inr_paise": 79900}},
        "no_price": {"name": "2 months", "days": 60, "on_sale": True},
    },
}


class FakeRazorpay(payments.Razorpay):
    """Razorpay's orders and payments, in memory. Only `_call` is fake."""

    def __init__(self) -> None:
        super().__init__(KEY_ID, SECRET, HOOK_SECRET)
        self.orders: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail = False
        self.lock = threading.Lock()
        self._ids = itertools.count(1)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        with self.lock:
            self.calls.append((method, path))
            if self.fail:
                raise payments.ProviderError(f"razorpay {path}: HTTP 500")
            if path == "/orders":
                oid = f"order_T{next(self._ids)}"
                self.orders[oid] = {"id": oid, "amount": body["amount"],
                                    "currency": body["currency"], "notes": body["notes"]}
                return dict(self.orders[oid])
            pid = path.split("/")[2]
            if pid not in self.payments:
                raise payments.ProviderError(f"razorpay {path}: HTTP 400 no such payment")
            p = self.payments[pid]
            if path.endswith("/capture"):
                if p["status"] != "authorized":
                    raise payments.ProviderError(f"razorpay {path}: HTTP 400 already captured")
                p["status"] = "captured"
            return dict(p)

    def pay(self, order_id: str, *, status: str = "captured", amount: int | None = None,
            currency: str = "INR") -> dict:
        """What Checkout would hand the page after a payment on `order_id`."""
        pid = f"pay_T{next(self._ids)}"
        self.payments[pid] = {
            "id": pid, "entity": "payment", "order_id": order_id, "status": status,
            "amount": self.orders[order_id]["amount"] if amount is None else amount,
            "currency": currency,
        }
        return {"razorpay_order_id": order_id, "razorpay_payment_id": pid,
                "razorpay_signature": payments.sign(SECRET, f"{order_id}|{pid}")}


@pytest.fixture
def pricing_file(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(CATALOGUE), encoding="utf-8")
    return str(path)


@pytest.fixture
def make_hp(make_harness, pricing_file):
    def build(enabled: bool = True, keys: bool = True, **overrides):
        h = make_harness(HOLT_PRICING_FILE=pricing_file, HOLT_PAYMENTS_ENABLED=enabled,
                         **overrides)
        h.rz = FakeRazorpay() if keys else None
        h.svc.razorpay = h.rz
        return h
    return build


@pytest.fixture
def hp(make_hp):
    return make_hp()


def rows(h, model):
    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model))).scalars().all()
    return h.client.portal.call(q)


def pro_days(h, user: str) -> float:
    """Days of Pro left for `user` (0 when on free)."""
    me = h.get("/v1/me", user=user).json()
    if me["plan"] != "pro":
        return 0
    ends = datetime.fromisoformat(me["plan_expires_at"].replace("Z", "+00:00"))
    return round((ends - now()).total_seconds() / 86400, 1)


def assert_one_grant_per_payment(h, user: str) -> None:
    paid = [o for o in rows(h, Order) if o.user_id == user and o.status == "paid"]
    events = [e for e in rows(h, PlanEvent) if e.user_id == user]
    assert sorted(e.reference for e in events) == sorted(o.provider_payment_id for o in paid)
    assert all(e.plan == "pro" and e.actor == "payment" for e in events)
    assert rows(h, CreditLot) == []


def checkout(h, user: str = "buyer", pass_: str = "pro_1m") -> dict:
    r = h.post("/v1/me/orders", {"pass": pass_}, user=user)
    assert r.status_code == 200, r.text
    return r.json()


def confirm(h, cb: dict, user: str = "buyer"):
    return h.post("/v1/me/orders/confirm", cb, user=user)


def hook_body(event: str, payment: dict) -> bytes:
    return json.dumps({"entity": "event", "event": event, "contains": ["payment"],
                       "payload": {"payment": {"entity": payment}}}).encode()


def webhook(h, body: bytes, signature: str | None = "auto"):
    sig = payments.sign(HOOK_SECRET, body) if signature == "auto" else signature
    headers = {**h.headers(), "Content-Type": "application/json"}
    if sig is not None:
        headers["X-Razorpay-Signature"] = sig
    return h.client.post("/v1/payments/razorpay/webhook", content=body, headers=headers)


# --- what is on sale ---------------------------------------------------------------


OFF = {"on_sale": False, "passes": [], "features": []}


def test_passes_on_sale_come_from_the_pricing_file(hp):
    body = hp.get("/v1/passes").json()
    assert body["on_sale"] is True
    assert body["passes"] == [
        {"id": "pro_1m", "name": "1 month", "days": 30, "amount": PRICE, "currency": "INR"},
        {"id": "pro_3m", "name": "3 months", "days": 90, "amount": 24900, "currency": "INR"},
    ]
    assert body["features"] == [
        {"id": "merge_plan", "name": "Merge plan", "per_month": 30, "unlimited": False},
        {"id": "pr_watch", "name": "PR watch", "per_month": None, "unlimited": True},
    ]


def test_the_packaged_pricing_file_sells_nothing_until_payments_are_switched_on(make_harness):
    """Production as it is deployed without HOLT_PROD_PAYMENTS: every pass is
    marked on sale in the packaged file, and none is offered or can be ordered."""
    for overrides in ({}, {"HOLT_PAYMENTS_ENABLED": True},
                      {"RAZORPAY_KEY_ID": "rzp_live_fake", "RAZORPAY_KEY_SECRET": SECRET,
                       "RAZORPAY_WEBHOOK_SECRET": HOOK_SECRET}):
        h = make_harness(HOLT_ENV="production", **overrides)
        if h.svc.razorpay is not None:
            h.svc.razorpay = FakeRazorpay()
        assert all(p.on_sale for p in entitlements.catalogue(h.svc).passes.values())
        assert h.get("/v1/passes").json() == OFF
        for pid in ("pro_1m", "pro_3m", "pro_12m"):
            r = h.post("/v1/me/orders", {"pass": pid}, user="u")
            assert r.status_code == 403 and r.json()["error"]["code"] == "payments_off"
        assert rows(h, Order) == []
        if h.svc.razorpay is not None:
            assert h.svc.razorpay.calls == []
        assert payments.startup_line(h.svc)[1].startswith("passes: off")


def test_the_packaged_pricing_file_sells_its_three_passes_with_payments_on(make_harness):
    h = make_harness(HOLT_ENV="production", HOLT_PAYMENTS_ENABLED=True)
    h.svc.razorpay = FakeRazorpay()
    body = h.get("/v1/passes").json()
    assert body["on_sale"] is True and body["passes"] == PACKAGED


@pytest.mark.parametrize("enabled,keys", [(False, True), (True, False), (False, False)])
def test_switched_off_offers_nothing_and_refuses_orders(make_hp, enabled, keys):
    h = make_hp(enabled=enabled, keys=keys)
    assert h.get("/v1/passes").json() == OFF
    r = h.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer")
    assert r.status_code == 403 and r.json()["error"]["code"] == "payments_off"
    assert rows(h, Order) == []
    if h.rz is not None:
        assert h.rz.calls == []


def test_payments_are_off_by_default(tmp_path):
    from conftest import make_settings

    s = make_settings(tmp_path)
    assert s.payments_enabled is False
    assert payments.build(s) is None


# --- HOLT_PASSES_ON_SALE: every pass on sale, outside production -----------------------


PACKAGED = [
    {"id": "pro_1m", "name": "1 month", "days": 30, "amount": 9900, "currency": "INR"},
    {"id": "pro_3m", "name": "3 months", "days": 90, "amount": 24900, "currency": "INR"},
    {"id": "pro_12m", "name": "12 months", "days": 365, "amount": 79900, "currency": "INR"},
]


@pytest.fixture
def make_staging(make_harness, tmp_path):
    """The packaged pricing file with no pass on sale in it, on staging's settings."""
    raw = json.loads(pricing.DEFAULT_FILE.read_text(encoding="utf-8"))
    for p in raw["passes"].values():
        p["on_sale"] = False
    nothing_on_sale = tmp_path / "nothing-on-sale.json"
    nothing_on_sale.write_text(json.dumps(raw), encoding="utf-8")

    def build(env: str = "staging", **overrides):
        values = {"HOLT_ENV": env, "HOLT_PAYMENTS_ENABLED": True, "HOLT_PASSES_ON_SALE": True,
                  "HOLT_PR_WATCH": True, "HOLT_PRICING_FILE": str(nothing_on_sale), **overrides}
        h = make_harness(**values)
        h.rz = h.svc.razorpay = FakeRazorpay()
        return h
    return build


def test_the_switch_puts_every_packaged_pass_on_sale(make_staging):
    h = make_staging()
    body = h.get("/v1/passes").json()
    assert body["on_sale"] is True and body["passes"] == PACKAGED
    assert {f["id"]: (f["per_month"], f["unlimited"]) for f in body["features"]} == {
        "merge_plan": (30, False), "pr_watch": (None, True),
        "repo_watch": (None, True), "issue_watch": (None, True)}
    level, line = payments.startup_line(h.svc)
    assert level == logging.INFO and "pro_1m, pro_3m, pro_12m" in line and "test keys" in line


@pytest.mark.parametrize("how", ["callback", "webhook"])
def test_a_pass_bought_on_the_switch_gives_pro(make_staging, how):
    h = make_staging()
    before = h.get("/v1/me/entitlements", user="buyer").json()
    assert before["plan"] == "free"
    assert h.get("/v1/me/alerts/settings", user="buyer").json()["access"]["state"] == "off"

    out = checkout(h, pass_="pro_3m")
    assert (out["amount"], out["currency"], out["days"]) == (24900, "INR", 90)
    assert out["key_id"] == KEY_ID
    cb = h.rz.pay(out["provider_order_id"])
    if how == "callback":
        r = confirm(h, cb)
        assert r.status_code == 200 and r.json()["plan"] == "pro", r.text
    else:
        payment = h.rz.payments[cb["razorpay_payment_id"]]
        assert webhook(h, hook_body("payment.captured", payment)).json()["result"] == "paid"

    assert pro_days(h, "buyer") == 90
    after = h.get("/v1/me/entitlements", user="buyer").json()
    access = {a["feature"]: a for a in after["features"]}
    assert after["plan"] == "pro"
    assert access["merge_plan"]["via"] == "plan" and access["merge_plan"]["left_this_month"] == 30
    assert access["pr_watch"]["allowed"] is True and access["pr_watch"]["via"] == "plan"
    assert h.get("/v1/me/alerts/settings", user="buyer").json()["access"]["state"] == "pro"
    assert_one_grant_per_payment(h, "buyer")


@pytest.mark.parametrize("overrides", [
    {"HOLT_PAYMENTS_ENABLED": False},
    {"HOLT_PASSES_ON_SALE": False},
])
def test_the_switch_needs_payments_on_too_and_payments_need_the_switch(make_staging, overrides):
    h = make_staging(**overrides)
    assert h.get("/v1/passes").json() == OFF
    assert h.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer").status_code in (400, 403)
    assert rows(h, Order) == [] and h.rz.calls == []


def test_the_switch_without_razorpay_keys_sells_nothing(make_staging):
    h = make_staging()
    h.svc.razorpay = None
    assert h.get("/v1/passes").json() == OFF
    r = h.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer")
    assert r.status_code == 403 and r.json()["error"]["code"] == "payments_off"


def test_production_ignores_the_switch(make_staging):
    """Everything staging sets, on production: still nothing on sale."""
    h = make_staging(env="production")
    assert h.svc.settings.sell_every_pass is False
    assert h.get("/v1/passes").json() == OFF
    for pid in ("pro_1m", "pro_3m", "pro_12m"):
        r = h.post("/v1/me/orders", {"pass": pid}, user="buyer")
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert rows(h, Order) == [] and h.rz.calls == []
    assert not any(p.on_sale for p in entitlements.catalogue(h.svc).passes.values())
    level, line = payments.startup_line(h.svc)
    assert level == logging.ERROR and "ignored" in line


def test_the_switch_is_off_and_the_environment_is_production_by_default(monkeypatch):
    from holt_server.settings import Settings

    for name in ("HOLT_ENV", "HOLT_PASSES_ON_SALE", "HOLT_PAYMENTS_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.env, s.passes_on_sale, s.payments_enabled, s.sell_every_pass) == (
        "production", False, False, False)
    # Production's own settings: the pricing file marks the passes on sale,
    # and HOLT_PAYMENTS_ENABLED (deploy/prod: HOLT_PROD_PAYMENTS) stays off.
    prod = Settings(_env_file=None, HOLT_ENV="production")
    cat = pricing.cached(prod.pricing_file, prod.sell_every_pass)
    assert [pid for pid, p in cat.passes.items() if p.on_sale] == ["pro_1m", "pro_3m", "pro_12m"]
    assert prod.payments_enabled is False and payments.build(prod) is None


def test_productions_scripts_never_set_the_staging_switch():
    """HOLT_PASSES_ON_SALE is staging's. What production may set is checked
    in tests/test_prod_payments.py."""
    prod = Path(__file__).resolve().parents[2] / "deploy" / "prod"
    if not prod.is_dir():
        pytest.skip("no deploy/ next to the server (an installed package)")
    for path in sorted(prod.iterdir()):
        if path.is_file() and path.suffix in (".sh", ".yml"):
            assert "HOLT_PASSES_ON_SALE=" not in path.read_text(encoding="utf-8"), path.name
            assert "HOLT_PASSES_ON_SALE:" not in path.read_text(encoding="utf-8"), path.name


def test_passes_need_the_internal_key(hp):
    assert hp.client.get("/v1/passes").status_code == 401


# --- creating an order -----------------------------------------------------------------


def test_an_order_takes_its_price_from_the_server(hp):
    out = checkout(hp)
    assert out["provider"] == "razorpay" and out["key_id"] == KEY_ID
    assert out["amount"] == PRICE and out["currency"] == "INR"
    assert (out["item"], out["days"], out["description"]) == ("pro_1m", 30, "Pro, 1 month")
    rz_order = hp.rz.orders[out["provider_order_id"]]
    assert rz_order["amount"] == PRICE and rz_order["notes"]["holt_order"] == out["order_id"]
    (order,) = rows(hp, Order)
    assert (order.user_id, order.status, order.amount, order.credits, order.pack_id,
            order.expires_days) == ("buyer", "created", PRICE, 0, "pro_1m", 30)


def test_the_client_cannot_set_the_amount(hp):
    r = hp.post("/v1/me/orders", {"pass": "pro_1m", "amount": 100, "days": 999},
                user="buyer")
    assert r.status_code == 200
    assert r.json()["amount"] == PRICE and r.json()["days"] == 30
    assert rows(hp, Order)[0].amount == PRICE


@pytest.mark.parametrize("pid", ["not_yet", "no_price", "nope"])
def test_passes_not_on_sale_cannot_be_ordered(hp, pid):
    r = hp.post("/v1/me/orders", {"pass": pid}, user="buyer")
    assert r.status_code == 400 and "isn't on sale" in r.json()["error"]["message"]
    assert hp.rz.calls == []


def test_ordering_needs_a_signed_in_user(hp):
    assert hp.post("/v1/me/orders", {"pass": "pro_1m"}).status_code == 401


def test_razorpay_failing_creates_no_order(hp):
    hp.rz.fail = True
    r = hp.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer")
    assert r.status_code == 502 and "Razorpay" in r.json()["error"]["message"]
    assert rows(hp, Order) == []


# --- the client callback ------------------------------------------------------------------


def test_a_signed_callback_gives_the_pass_once(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    r = confirm(hp, cb)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["status"] == "paid" and body["order"]["name"] == "Pro, 1 month"
    assert body["order"]["days"] == 30 and body["plan"] == "pro"
    assert body["plan_expires_at"]
    # Replayed: same answer, nothing more.
    assert confirm(hp, cb).json()["order"]["status"] == "paid"
    assert pro_days(hp, "buyer") == 30
    (event,) = rows(hp, PlanEvent)
    assert (event.reference, event.reason) == (cb["razorpay_payment_id"], "pass pro_1m")
    # Free credits are untouched by a pass.
    assert hp.get("/v1/me/credits", user="buyer").json()["free"] == 3
    assert_one_grant_per_payment(hp, "buyer")


def test_a_second_pass_adds_its_days_to_the_first(hp):
    confirm(hp, hp.rz.pay(checkout(hp)["provider_order_id"]))
    confirm(hp, hp.rz.pay(checkout(hp, pass_="pro_3m")["provider_order_id"]))
    assert pro_days(hp, "buyer") == 120
    assert_one_grant_per_payment(hp, "buyer")


def test_a_pass_after_pro_lapsed_starts_from_now(hp):
    async def lapsed():
        await entitlements.set_plan(hp.svc, "buyer", "pro", expires_at=now() - timedelta(days=5),
                                    reason="test", actor="test")
    hp.client.portal.call(lapsed)
    confirm(hp, hp.rz.pay(checkout(hp)["provider_order_id"]))
    assert pro_days(hp, "buyer") == 30


def test_a_pass_never_shortens_pro_without_an_end(hp):
    async def forever():
        await entitlements.set_plan(hp.svc, "buyer", "pro", expires_at=None,
                                    reason="test", actor="test")
    hp.client.portal.call(forever)
    body = confirm(hp, hp.rz.pay(checkout(hp)["provider_order_id"])).json()
    assert body["order"]["status"] == "paid"
    assert (body["plan"], body["plan_expires_at"]) == ("pro", None)


def test_a_credit_pack_order_from_before_passes_still_settles_as_credits(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])

    async def make_it_a_pack():
        async with hp.svc.db.session() as s:
            order = await s.get(Order, out["order_id"])
            order.pack_id, order.credits, order.expires_days = "credits_10", 10, None
            await s.commit()
    hp.client.portal.call(make_it_a_pack)
    body = confirm(hp, cb).json()
    assert body["order"]["status"] == "paid" and body["order"]["name"] == "10 credits"
    assert body["order"]["days"] is None and body["plan"] == "free"
    assert hp.get("/v1/me/credits", user="buyer").json()["purchased"] == 10
    (lot,) = rows(hp, CreditLot)
    assert lot.reference == cb["razorpay_payment_id"]


@pytest.mark.parametrize("change", ["signature", "payment", "order"])
def test_a_bad_signature_gives_nothing(hp, change):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    other = hp.rz.pay(checkout(hp)["provider_order_id"])
    if change == "signature":
        cb["razorpay_signature"] = payments.sign("not-the-secret", "x")
    elif change == "payment":  # someone else's payment id under this order's signature
        cb["razorpay_payment_id"] = other["razorpay_payment_id"]
    else:
        cb["razorpay_order_id"] = other["razorpay_order_id"]
    r = confirm(hp, cb)
    assert r.status_code == 400 and r.json()["error"]["code"] == "payment_unconfirmed"
    assert pro_days(hp, "buyer") == 0 and rows(hp, PlanEvent) == []


def test_malformed_ids_are_refused_before_any_call(hp):
    checkout(hp)
    before = list(hp.rz.calls)
    cb = {"razorpay_order_id": "order_T1", "razorpay_payment_id": "pay_../../orders",
          "razorpay_signature": payments.sign(SECRET, "order_T1|pay_../../orders")}
    assert confirm(hp, cb).status_code == 400
    assert hp.rz.calls == before


def test_someone_elses_order_is_not_found(hp):
    out = checkout(hp, user="buyer")
    r = confirm(hp, hp.rz.pay(out["provider_order_id"]), user="thief")
    assert r.status_code == 404
    assert rows(hp, PlanEvent) == []


def test_a_tampered_amount_is_held_not_given(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], amount=100)
    r = confirm(hp, cb)
    assert r.status_code == 200 and r.json()["order"]["status"] == "held"
    assert pro_days(hp, "buyer") == 0 and rows(hp, PlanEvent) == []
    assert "was 100 INR" in rows(hp, Order)[0].note


def test_a_wrong_currency_is_held(hp):
    out = checkout(hp)
    r = confirm(hp, hp.rz.pay(out["provider_order_id"], currency="USD"))
    assert r.json()["order"]["status"] == "held"
    assert rows(hp, PlanEvent) == []


def test_an_authorized_payment_is_captured_then_credited(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], status="authorized")
    assert confirm(hp, cb).json()["order"]["status"] == "paid"
    assert hp.rz.payments[cb["razorpay_payment_id"]]["status"] == "captured"
    assert ("POST", f"/payments/{cb['razorpay_payment_id']}/capture") in hp.rz.calls
    assert pro_days(hp, "buyer") == 30


def test_a_payment_still_processing_leaves_the_order_open(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], status="created")
    assert confirm(hp, cb).json()["order"]["status"] == "created"
    assert pro_days(hp, "buyer") == 0


def test_razorpay_down_during_confirm_credits_nothing_yet(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    hp.rz.fail = True
    assert confirm(hp, cb).status_code == 502
    hp.rz.fail = False
    assert confirm(hp, cb).json()["order"]["status"] == "paid"
    assert pro_days(hp, "buyer") == 30


# --- the webhook ---------------------------------------------------------------------------


def test_a_signed_webhook_credits_and_a_replay_does_not(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    body = hook_body("payment.captured", hp.rz.payments[cb["razorpay_payment_id"]])
    r = webhook(hp, body)
    assert r.status_code == 200 and r.json()["result"] == "paid"
    assert webhook(hp, body).json()["result"] == "already_paid"
    # order.paid for the same payment, and the late client callback: nothing more.
    assert webhook(hp, hook_body("order.paid", hp.rz.payments[cb["razorpay_payment_id"]])
                   ).json()["result"] == "already_paid"
    assert confirm(hp, cb).json()["order"]["status"] == "paid"
    assert pro_days(hp, "buyer") == 30
    assert len(rows(hp, PlanEvent)) == 1
    assert_one_grant_per_payment(hp, "buyer")


@pytest.mark.parametrize("signature", [None, "", "deadbeef",
                                       payments.sign(SECRET, b"x")])
def test_an_unsigned_or_badly_signed_webhook_is_refused(hp, signature):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    body = hook_body("payment.captured", hp.rz.payments[cb["razorpay_payment_id"]])
    r = webhook(hp, body, signature=signature)
    assert r.status_code == 400
    assert rows(hp, PlanEvent) == [] and rows(hp, Order)[0].status == "created"


def test_a_webhook_body_changed_after_signing_is_refused(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], amount=100)
    real = hook_body("payment.captured", hp.rz.payments[cb["razorpay_payment_id"]])
    forged = real.replace(b'"amount": 100', f'"amount": {PRICE}'.encode())
    assert forged != real
    r = webhook(hp, forged, signature=payments.sign(HOOK_SECRET, real))
    assert r.status_code == 400
    assert rows(hp, PlanEvent) == []


def test_a_signed_webhook_with_the_wrong_amount_is_held(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], amount=PRICE - 1)
    body = hook_body("payment.captured", hp.rz.payments[cb["razorpay_payment_id"]])
    assert webhook(hp, body).json()["result"] == "held"
    assert rows(hp, PlanEvent) == [] and rows(hp, Order)[0].status == "held"


def test_webhooks_are_refused_without_a_webhook_secret(make_hp):
    h = make_hp()
    h.rz._webhook_secret = ""
    body = hook_body("payment.captured", {"id": "pay_X", "order_id": "order_X"})
    assert webhook(h, body).status_code == 400


def test_webhooks_need_the_internal_key(hp):
    body = hook_body("payment.captured", {})
    r = hp.client.post("/v1/payments/razorpay/webhook", content=body,
                       headers={"X-Razorpay-Signature": payments.sign(HOOK_SECRET, body)})
    assert r.status_code == 401


def test_unknown_orders_and_other_events_are_acknowledged_and_ignored(hp):
    body = hook_body("payment.captured", {"id": "pay_Z", "order_id": "order_Z",
                                          "amount": PRICE, "currency": "INR",
                                          "status": "captured"})
    assert webhook(hp, body).json() == {"ok": True, "result": "unknown_order"}
    refund = json.dumps({"event": "refund.processed", "payload": {}}).encode()
    assert webhook(hp, refund).json() == {"ok": True, "result": "ignored"}
    assert rows(hp, PlanEvent) == []


def test_a_failed_attempt_then_a_good_one_gives_once(hp):
    out = checkout(hp)
    oid = out["provider_order_id"]
    bad = hp.rz.pay(oid, status="failed")
    failed = hook_body("payment.failed", hp.rz.payments[bad["razorpay_payment_id"]])
    assert webhook(hp, failed).json()["result"] == "failed"
    assert rows(hp, Order)[0].status == "failed"
    good = hp.rz.pay(oid)
    assert confirm(hp, good).json()["order"]["status"] == "paid"
    # A late replay of the failure doesn't undo the payment.
    assert webhook(hp, failed).json()["result"] == "already_paid"
    assert rows(hp, Order)[0].status == "paid"
    assert pro_days(hp, "buyer") == 30


def test_an_authorized_webhook_captures(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"], status="authorized")
    body = hook_body("payment.authorized", hp.rz.payments[cb["razorpay_payment_id"]])
    assert webhook(hp, body).json()["result"] == "paid"
    assert pro_days(hp, "buyer") == 30


def test_one_payment_cannot_pay_two_orders(hp):
    a, b = checkout(hp), checkout(hp)
    cb = hp.rz.pay(a["provider_order_id"])
    confirm(hp, cb)
    # A (signed) event claiming the same payment paid order b.
    p = {**hp.rz.payments[cb["razorpay_payment_id"]], "order_id": b["provider_order_id"]}
    assert webhook(hp, hook_body("payment.captured", p)).json()["result"] == "already_paid"
    assert pro_days(hp, "buyer") == 30
    assert {o.status for o in rows(hp, Order)} == {"paid", "created"}
    assert_one_grant_per_payment(hp, "buyer")


def test_switching_payments_off_still_settles_orders_already_paid(make_hp, pricing_file):
    h = make_hp()
    out = checkout(h)
    cb = h.rz.pay(out["provider_order_id"])
    h.svc.settings.payments_enabled = False
    assert h.get("/v1/passes").json()["on_sale"] is False
    assert h.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer").status_code == 403
    assert confirm(h, cb).json()["order"]["status"] == "paid"
    assert pro_days(h, "buyer") == 30


# --- concurrency -------------------------------------------------------------------------


def test_callback_and_webhooks_racing_give_once(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    body = hook_body("payment.captured", hp.rz.payments[cb["razorpay_payment_id"]])
    jobs = [lambda: confirm(hp, cb)] * 4 + [lambda: webhook(hp, body)] * 4
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda f: f(), jobs))
    assert {r.status_code for r in results} == {200}
    assert pro_days(hp, "buyer") == 30
    assert len(rows(hp, PlanEvent)) == 1
    assert_one_grant_per_payment(hp, "buyer")


def test_concurrent_credit_calls_give_the_pass_once(hp):
    out = checkout(hp)
    cb = hp.rz.pay(out["provider_order_id"])
    order_id, pid = out["order_id"], cb["razorpay_payment_id"]

    async def race():
        return await asyncio.gather(*(payments.credit(hp.svc, order_id, pid)
                                      for _ in range(8)))

    assert sorted(hp.client.portal.call(race)) == [False] * 7 + [True]
    assert pro_days(hp, "buyer") == 30
    assert_one_grant_per_payment(hp, "buyer")


# --- purchase history ---------------------------------------------------------------------


def test_purchase_history_lists_finished_orders_newest_first(hp):
    first = checkout(hp)
    confirm(hp, hp.rz.pay(first["provider_order_id"]))
    checkout(hp)  # opened, never paid: not a purchase
    third = checkout(hp, pass_="pro_3m")
    confirm(hp, hp.rz.pay(third["provider_order_id"], amount=1))
    checkout(hp, user="someone-else")
    orders = hp.get("/v1/me/orders", user="buyer").json()["orders"]
    assert [(o["id"], o["status"]) for o in orders] == [
        (third["order_id"], "held"), (first["order_id"], "paid")]
    assert orders[1]["paid_at"] and orders[1]["name"] == "Pro, 1 month"
    assert (orders[0]["item"], orders[0]["days"]) == ("pro_3m", 90)
    assert hp.get("/v1/me/orders").status_code == 401
