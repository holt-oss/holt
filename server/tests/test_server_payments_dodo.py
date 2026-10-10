"""USD passes through Dodo Payments (payments.py, payments_dodo.py): the
hosted checkout, the buyer's return, the signed webhook, refunds and
disputes, and the settings that keep it off.

Dodo is faked at the HTTP layer (`FakeDodo._call`), so the signature check,
the product check and the payment checks are the real ones. Every test that
pays ends on the same invariant as Razorpay's: one `PlanEvent` per paid
order, referencing its payment.
"""

from __future__ import annotations

import base64
import copy
import itertools
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from holt_server import payments, payments_dodo
from holt_server.db import Order, PlanEvent
from test_server_payments import (
    FakeRazorpay,
    assert_one_grant_per_payment,
    pro_days,
    rows,
)
from test_server_payments import checkout as inr_checkout
from test_server_payments import confirm as inr_confirm

API_KEY = "dodo-fake-key"
HOOK_KEY = b"a fake webhook signing key"
HOOK_SECRET = "whsec_" + base64.b64encode(HOOK_KEY).decode()
PRODUCTS = {"pro_1m": "pdt_1m", "pro_3m": "pdt_3m", "not_yet": "pdt_12m"}
USD = 700

CATALOGUE = {
    "tbd": False,
    "features": {"pr_watch": {"name": "PR watch", "credits": None},
                 "merge_plan": {"name": "Merge plan", "credits": None}},
    "plans": {"free": {"name": "Free", "features": {}},
              "pro": {"name": "Pro", "features": {"merge_plan": {"per_month": 30},
                                                  "pr_watch": {"unlimited": True}}}},
    "passes": {
        "pro_1m": {"name": "1 month", "days": 30, "on_sale": True,
                   "price": {"inr_paise": 9900, "usd_cents": USD}},
        "pro_3m": {"name": "3 months", "days": 90, "on_sale": True,
                   "price": {"inr_paise": 24900, "usd_cents": 1500}},
        "not_yet": {"name": "12 months", "days": 365, "on_sale": False,
                    "price": {"inr_paise": 79900, "usd_cents": 3900}},
        "inr_only": {"name": "2 months", "days": 60, "on_sale": True,
                     "price": {"inr_paise": 17900}},
        "no_product": {"name": "6 months", "days": 180, "on_sale": True,
                       "price": {"usd_cents": 2500}},
    },
}


def product(price: int, **changes: Any) -> dict:
    return {"product_id": "pdt", "is_recurring": False, "pricing_mode": None,
            "price": {"type": "one_time_price", "price": price, "currency": "USD",
                      "discount": 0, "pay_what_you_want": False,
                      "purchasing_power_parity": False, "tax_inclusive": False, **changes}}


class FakeDodo(payments_dodo.Dodo):
    """Dodo's products, checkout sessions and payments, in memory. Only
    `_call` is fake."""

    def __init__(self, products: dict[str, str] | None = None,
                 secret: str = HOOK_SECRET, env: str = "test") -> None:
        super().__init__(API_KEY, env, secret, PRODUCTS if products is None else products)
        self.catalog = {"pdt_1m": product(USD), "pdt_3m": product(1500),
                        "pdt_12m": product(3900)}
        self.sessions: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail = False
        self.lock = threading.Lock()
        self._ids = itertools.count(1)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        with self.lock:
            self.calls.append((method, path))
            if self.fail:
                raise payments_dodo.DodoError(f"dodo {path}: HTTP 500", status=500)
            if path == "/checkouts":
                sid = f"cks_T{next(self._ids)}"
                self.sessions[sid] = {"id": sid, "created_at": "2026-10-10T00:00:00Z",
                                      "payment_id": None, "payment_status": None,
                                      "request": body}
                return {"session_id": sid,
                        "checkout_url": f"https://test.checkout.dodopayments.com/session/{sid}"}
            kind, _, key = path.strip("/").partition("/")
            store = {"checkouts": self.sessions, "payments": self.payments,
                     "products": self.catalog}[kind]
            if key not in store:
                raise payments_dodo.DodoError(f"dodo {path}: HTTP 404", status=404)
            found = copy.deepcopy(store[key])
            found.pop("request", None)
            return found

    def asked(self, prefix: str) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[1].startswith(prefix)]

    def pay(self, session_id: str, *, status: str = "succeeded", total: Any = ...,
            tax: int | None = 0, currency: str = "USD", cart: Any = ...,
            metadata: dict | None = None) -> dict:
        """What Dodo records when the buyer pays in `session_id` (`...`: what
        a real payment for the session would say)."""
        asked = self.sessions[session_id]["request"]
        price = self.catalog[asked["product_cart"][0]["product_id"]]["price"]["price"]
        pid = f"pay_D{next(self._ids)}"  # FakeRazorpay's are pay_T…
        self.payments[pid] = {
            "payment_id": pid, "status": status, "currency": currency, "tax": tax,
            "total_amount": price + (tax or 0) if total is ... else total,
            "product_cart": asked["product_cart"] if cart is ... else cart,
            "checkout_session_id": session_id,
            "metadata": asked["metadata"] if metadata is None else metadata,
            "error_message": "Your card was declined." if status == "failed" else None,
            "refunds": [], "disputes": [],
        }
        self.sessions[session_id].update(payment_id=pid, payment_status=status)
        return self.payments[pid]


@pytest.fixture
def pricing_file(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(CATALOGUE), encoding="utf-8")
    return str(path)


@pytest.fixture
def make_hd(make_harness, pricing_file):
    def build(enabled: bool = True, razorpay: bool = True, dodo: FakeDodo | None | str = "new",
              **overrides):
        h = make_harness(HOLT_PRICING_FILE=pricing_file, HOLT_PAYMENTS_ENABLED=enabled,
                         HOLT_WEB_URL="https://holt.example", **overrides)
        h.rz = h.svc.razorpay = FakeRazorpay() if razorpay else None
        h.dodo = h.svc.dodo = FakeDodo() if dodo == "new" else dodo
        return h
    return build


@pytest.fixture
def hd(make_hd):
    return make_hd()


def checkout(h, user: str = "buyer", pass_: str = "pro_1m") -> dict:
    r = h.post("/v1/me/orders", {"pass": pass_, "currency": "USD"}, user=user)
    assert r.status_code == 200, r.text
    return r.json()


def check(h, order_id: str, user: str = "buyer"):
    return h.post(f"/v1/me/orders/{order_id}/check", user=user)


def paid(h, out: dict, **kw) -> dict:
    """The buyer pays in the checkout `out` opened."""
    return h.dodo.pay(out["provider_order_id"], **kw)


def hook_body(event: str, data: dict) -> bytes:
    return json.dumps({"business_id": "bus_T", "type": event,
                       "timestamp": "2026-10-10T10:00:00Z", "data": data}).encode()


def signed(body: bytes, *, key: bytes = HOOK_KEY, msg_id: str = "msg_1",
           at: float | None = None) -> dict[str, str]:
    ts = int(time.time() if at is None else at)
    return {"webhook-id": msg_id, "webhook-timestamp": str(ts),
            "webhook-signature": f"v1,{payments_dodo.signature(key, msg_id, ts, body)}"}


def webhook(h, body: bytes, headers: dict[str, str] | None = None):
    sent = {**h.headers(), "Content-Type": "application/json",
            **(signed(body) if headers is None else headers)}
    return h.client.post("/v1/payments/dodo/webhook", content=body, headers=sent)


def order_row(h, order_id: str) -> Order:
    return next(o for o in rows(h, Order) if o.id == order_id)


# --- what is on sale ---------------------------------------------------------------


def test_passes_list_every_currency_they_can_be_bought_in(hd):
    body = hd.get("/v1/passes").json()
    assert body["on_sale"] is True
    assert [(p["id"], p["amount"], p["currency"], p["prices"]) for p in body["passes"]] == [
        ("pro_1m", 9900, "INR", [{"currency": "INR", "amount": 9900},
                                 {"currency": "USD", "amount": USD}]),
        ("pro_3m", 24900, "INR", [{"currency": "INR", "amount": 24900},
                                  {"currency": "USD", "amount": 1500}]),
        ("inr_only", 17900, "INR", [{"currency": "INR", "amount": 17900}]),
    ]
    level, line = payments.startup_line(hd.svc)
    assert level == logging.INFO
    assert "Razorpay test keys" in line and "pro_1m, pro_3m in USD; Dodo test mode" in line


def test_dodo_alone_sells_in_usd_and_razorpay_alone_in_inr(make_hd):
    h = make_hd(razorpay=False)
    assert [(p["id"], p["amount"], p["currency"], p["prices"])
            for p in h.get("/v1/passes").json()["passes"]] == [
        ("pro_1m", USD, "USD", [{"currency": "USD", "amount": USD}]),
        ("pro_3m", 1500, "USD", [{"currency": "USD", "amount": 1500}]),
    ]
    r = h.post("/v1/me/orders", {"pass": "pro_1m"}, user="buyer")  # INR, the default
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    out = checkout(h)
    paid(h, out)
    assert check(h, out["order_id"]).json()["plan"] == "pro"

    h = make_hd(dodo=None)
    assert all(p["prices"] == [{"currency": "INR", "amount": p["amount"]}]
               for p in h.get("/v1/passes").json()["passes"])
    r = h.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    cb = h.rz.pay(inr_checkout(h)["provider_order_id"])
    assert inr_confirm(h, cb).json()["plan"] == "pro"


def test_dodo_failing_leaves_razorpay_working_and_the_reverse(hd):
    hd.dodo.fail = True
    cb = hd.rz.pay(inr_checkout(hd)["provider_order_id"])
    assert inr_confirm(hd, cb).json()["plan"] == "pro"
    assert hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"},
                   user="other").status_code == 502
    hd.dodo.fail, hd.rz.fail = False, True
    out = checkout(hd, user="other")
    paid(hd, out)
    assert check(hd, out["order_id"], user="other").json()["plan"] == "pro"
    assert hd.post("/v1/me/orders", {"pass": "pro_1m"}, user="other").status_code == 502


@pytest.mark.parametrize("pid", ["not_yet", "inr_only", "no_product", "nope"])
def test_usd_needs_a_pass_on_sale_with_a_usd_price_and_a_product(hd, pid):
    r = hd.post("/v1/me/orders", {"pass": pid, "currency": "USD"}, user="buyer")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert rows(hd, Order) == [] and hd.dodo.calls == []


def test_payments_off_offers_nothing_in_usd(make_hd):
    h = make_hd(enabled=False)
    assert h.get("/v1/passes").json() == {"on_sale": False, "passes": [], "features": []}
    r = h.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 403 and r.json()["error"]["code"] == "payments_off"
    assert rows(h, Order) == [] and h.dodo.calls == []


@pytest.mark.parametrize("secret", ["", "whsec_", "whsec_not base64!", "not base64!"])
def test_usd_is_not_offered_without_a_webhook_secret(make_hd, secret):
    h = make_hd(dodo=FakeDodo(secret=secret))
    assert all(p["currency"] == "INR" and len(p["prices"]) == 1
               for p in h.get("/v1/passes").json()["passes"])
    r = h.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 400
    assert h.dodo.calls == []
    level, line = payments.startup_line(h.svc)
    assert level == logging.WARNING and "DODO_WEBHOOK_SECRET" in line


def test_usd_is_not_offered_without_product_ids(make_hd):
    h = make_hd(dodo=FakeDodo(products={}))
    assert all(len(p["prices"]) == 1 for p in h.get("/v1/passes").json()["passes"])
    assert "DODO_PRODUCT_PRO_" in payments.startup_line(h.svc)[1]


def test_an_unknown_currency_is_refused(hd):
    r = hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "EUR"}, user="buyer")
    assert r.status_code in (400, 422)
    assert rows(hd, Order) == [] and hd.dodo.calls == [] and hd.rz.calls == []


# --- settings ------------------------------------------------------------------------


def settings(tmp_path, **overrides):
    from conftest import make_settings

    return make_settings(tmp_path, **overrides)


def test_dodo_is_off_by_default_and_reads_these_names(tmp_path, monkeypatch):
    for name in ("DODO_API_KEY", "DODO_ENV", "DODO_WEBHOOK_SECRET", "DODO_PRODUCT_PRO_1M",
                 "DODO_PRODUCT_PRO_3M", "DODO_PRODUCT_PRO_12M"):
        monkeypatch.delenv(name, raising=False)
    assert payments_dodo.build(settings(tmp_path)) is None

    s = settings(tmp_path, DODO_API_KEY=API_KEY, DODO_ENV="test",
                 DODO_WEBHOOK_SECRET=HOOK_SECRET, DODO_PRODUCT_PRO_1M="pdt_a",
                 DODO_PRODUCT_PRO_3M=" pdt_b ", DODO_PRODUCT_PRO_12M="")
    dodo = payments_dodo.build(s)
    assert dodo.env == "test" and dodo._base == "https://test.dodopayments.com"
    assert dodo.webhooks_on and dodo.products == {"pro_1m": "pdt_a", "pro_3m": "pdt_b"}
    assert API_KEY not in repr(s) and HOOK_SECRET not in repr(s)

    live = payments_dodo.build(settings(tmp_path, DODO_API_KEY=API_KEY, DODO_ENV="LIVE"))
    assert live._base == "https://live.dodopayments.com" and not live.webhooks_on


def test_an_environment_dodo_does_not_have_leaves_it_off(make_harness):
    h = make_harness(HOLT_PAYMENTS_ENABLED=True, DODO_API_KEY=API_KEY, DODO_ENV="prod",
                     DODO_WEBHOOK_SECRET=HOOK_SECRET, DODO_PRODUCT_PRO_1M="pdt_a")
    assert h.svc.dodo is None
    level, line = payments.startup_line(h.svc)
    assert level == logging.WARNING and "DODO_ENV must be test or live" in line
    assert API_KEY not in line


def test_the_packaged_pricing_file_sells_nothing_in_usd_either(make_harness):
    h = make_harness(HOLT_PAYMENTS_ENABLED=True)
    h.svc.dodo = dodo = FakeDodo(products={"pro_1m": "pdt_1m", "pro_3m": "pdt_3m",
                                           "pro_12m": "pdt_12m"})
    assert h.get("/v1/passes").json()["on_sale"] is False
    for pid in ("pro_1m", "pro_3m", "pro_12m"):
        r = h.post("/v1/me/orders", {"pass": pid, "currency": "USD"}, user="u")
        assert r.status_code == 400
    assert dodo.calls == []


def test_staging_puts_the_packaged_passes_on_sale_in_usd(make_harness):
    h = make_harness(HOLT_ENV="staging", HOLT_PAYMENTS_ENABLED=True, HOLT_PASSES_ON_SALE=True)
    h.svc.dodo = FakeDodo(products={"pro_1m": "pdt_1m", "pro_3m": "pdt_3m",
                                    "pro_12m": "pdt_12m"})
    assert [(p["id"], p["amount"], p["currency"])
            for p in h.get("/v1/passes").json()["passes"]] == [
        ("pro_1m", 700, "USD"), ("pro_3m", 1500, "USD"), ("pro_12m", 3900, "USD")]


# --- opening a checkout ------------------------------------------------------------------


def test_a_usd_order_takes_its_price_from_the_server(hd):
    out = hd.post("/v1/me/orders", {"pass": "pro_3m", "currency": "USD", "amount": 1,
                                    "product_id": "pdt_1m"}, user="buyer").json()
    assert (out["provider"], out["amount"], out["currency"], out["days"], out["item"]) == (
        "dodo", 1500, "USD", 90, "pro_3m")
    assert out["key_id"] is None
    assert out["checkout_url"].startswith("https://") and out["provider_order_id"] in out["checkout_url"]
    [row] = rows(hd, Order)
    assert (row.id, row.provider, row.currency, row.amount, row.pack_id, row.expires_days,
            row.status, row.provider_order_id) == (
        out["order_id"], "dodo", "USD", 1500, "pro_3m", 90, "created", out["provider_order_id"])
    asked = hd.dodo.sessions[out["provider_order_id"]]["request"]
    assert asked == {
        "product_cart": [{"product_id": "pdt_3m", "quantity": 1}],
        "billing_currency": "USD",
        "return_url": f"https://holt.example/pricing/thanks?order={out['order_id']}",
        "cancel_url": "https://holt.example/pricing?currency=usd",
        "metadata": {"holt_order": out["order_id"], "pass": "pro_3m"},
        "feature_flags": {"allow_discount_code": False, "allow_currency_selection": False},
    }
    assert pro_days(hd, "buyer") == 0


def test_ordering_in_usd_needs_a_signed_in_user(hd):
    assert hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}).status_code == 401
    assert hd.dodo.calls == []


@pytest.mark.parametrize("change,why", [
    ({"price": 500}, "its price is 500"),
    ({"currency": "EUR"}, "priced in EUR"),
    ({"type": "recurring_price"}, "not a one-time product"),
    ({"pay_what_you_want": True}, "choose the price"),
    ({"discount": 10}, "discount"),
    ({"discount_bps": 1250}, "discount"),
    ({"purchasing_power_parity": True}, "buyer's country"),
])
def test_a_product_that_does_not_match_the_catalogue_opens_no_checkout(hd, caplog, change, why):
    hd.dodo.catalog["pdt_1m"]["price"].update(change)
    with caplog.at_level(logging.ERROR, logger="holt_server.payments"):
        r = hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream"
    assert why in caplog.text
    assert rows(hd, Order) == [] and hd.dodo.asked("/checkouts") == []
    # Fixed in Dodo's dashboard: the next try goes through.
    hd.dodo.catalog["pdt_1m"] = product(USD)
    assert checkout(hd)["amount"] == USD


def test_a_missing_or_localized_product_opens_no_checkout(hd):
    del hd.dodo.catalog["pdt_1m"]
    assert hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"},
                   user="buyer").status_code == 502
    hd.dodo.catalog["pdt_3m"]["pricing_mode"] = "by_country"
    assert hd.post("/v1/me/orders", {"pass": "pro_3m", "currency": "USD"},
                   user="buyer").status_code == 502
    assert rows(hd, Order) == [] and hd.dodo.asked("/checkouts") == []


def test_the_product_is_checked_once_for_a_while_then_again(hd):
    checkout(hd)
    checkout(hd)
    assert len(hd.dodo.asked("/products/")) == 1
    amount, at = hd.dodo.checked["pdt_1m"]
    hd.dodo.checked["pdt_1m"] = (amount, at - payments_dodo.PRODUCT_CHECK_S - 1)
    checkout(hd)
    assert len(hd.dodo.asked("/products/")) == 2


def test_dodo_failing_creates_no_order(hd):
    hd.dodo.fail = True
    r = hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream"
    assert rows(hd, Order) == []


@pytest.mark.parametrize("answer", [
    {"session_id": "cks_x", "checkout_url": None},
    {"session_id": "cks_x", "checkout_url": "http://plain.example/x"},
    {"session_id": "", "checkout_url": "https://checkout.example/x"},
    {"checkout_url": "https://checkout.example/x"},
])
def test_a_checkout_without_a_session_or_a_safe_url_creates_no_order(hd, monkeypatch, answer):
    real = hd.dodo._call
    monkeypatch.setattr(hd.dodo, "_call", lambda method, path, body=None: (
        answer if path == "/checkouts" else real(method, path, body)))
    r = hd.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"}, user="buyer")
    assert r.status_code == 502 and rows(hd, Order) == []


# --- the buyer's return --------------------------------------------------------------------


def test_the_return_gives_the_pass_once(hd):
    out = checkout(hd)
    payment = paid(hd, out)
    r = check(hd, out["order_id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "pro" and body["plan_expires_at"]
    assert (body["order"]["status"], body["order"]["provider"], body["order"]["currency"],
            body["order"]["amount"]) == ("paid", "dodo", "USD", USD)
    assert pro_days(hd, "buyer") == 30
    assert order_row(hd, out["order_id"]).provider_payment_id == payment["payment_id"]

    before = len(hd.dodo.calls)
    for _ in range(3):
        assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert len(hd.dodo.calls) == before  # a settled order asks Dodo nothing
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


def test_nothing_in_the_return_address_is_believed(hd):
    """The page hands over only the order id: a buyer who never paid, and says
    they did, gets nothing."""
    out = checkout(hd)
    r = hd.post(f"/v1/me/orders/{out['order_id']}/check",
                {"payment_id": "pay_made_up", "status": "succeeded"}, user="buyer")
    assert r.status_code == 200 and r.json()["order"]["status"] == "created"
    assert r.json()["plan"] == "free" and pro_days(hd, "buyer") == 0
    assert rows(hd, PlanEvent) == []


@pytest.mark.parametrize("tax,total", [(0, 700), (133, 833), (117, 700), (None, 700)])
def test_tax_on_top_of_the_price_or_inside_it_still_matches(hd, tax, total):
    out = checkout(hd)
    paid(hd, out, tax=tax, total=total)
    assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert pro_days(hd, "buyer") == 30


@pytest.mark.parametrize("how", [
    {"total": 100},
    {"total": 699},
    {"total": 833, "tax": 100},
    {"total": None},
    {"total": "700"},
    {"currency": "EUR"},
    {"currency": "INR"},
    {"cart": [{"product_id": "pdt_3m", "quantity": 1}]},
    {"cart": [{"product_id": "pdt_1m", "quantity": 2}]},
    {"cart": [{"product_id": "pdt_1m", "quantity": 1}, {"product_id": "pdt_3m", "quantity": 1}]},
    {"cart": []},
    {"cart": None},
    {"metadata": {"holt_order": "f" * 32}},
])
def test_a_payment_that_does_not_match_the_order_is_held_not_given(hd, caplog, how):
    out = checkout(hd)
    paid(hd, out, **how)
    with caplog.at_level(logging.ERROR, logger="holt_server.payments"):
        body = check(hd, out["order_id"]).json()
    assert body["order"]["status"] == "held" and body["plan"] == "free"
    assert "held" in caplog.text
    row = order_row(hd, out["order_id"])
    assert row.note and row.provider_payment_id is None
    assert pro_days(hd, "buyer") == 0 and rows(hd, PlanEvent) == []
    # Still held however often anyone asks, and by the webhook too.
    assert check(hd, out["order_id"]).json()["order"]["status"] == "held"
    payment = hd.dodo.payments[hd.dodo.sessions[out["provider_order_id"]]["payment_id"]]
    assert webhook(hd, hook_body("payment.succeeded", payment)).status_code == 200
    assert order_row(hd, out["order_id"]).status == "held" and pro_days(hd, "buyer") == 0


def test_a_product_id_removed_from_the_settings_holds_the_payment(hd):
    out = checkout(hd)
    paid(hd, out)
    hd.dodo.products.pop("pro_1m")
    assert check(hd, out["order_id"]).json()["order"]["status"] == "held"
    assert pro_days(hd, "buyer") == 0


def test_a_checkout_nobody_paid_in_stays_open(hd):
    out = checkout(hd)
    body = check(hd, out["order_id"]).json()
    assert body["order"]["status"] == "created" and body["plan"] == "free"
    assert hd.dodo.asked("/payments/") == []


@pytest.mark.parametrize("status", ["processing", "requires_customer_action", "requires_capture"])
def test_a_payment_not_finished_gives_nothing_yet(hd, status):
    out = checkout(hd)
    payment = paid(hd, out, status=status)
    assert check(hd, out["order_id"]).json()["order"]["status"] == "created"
    assert pro_days(hd, "buyer") == 0
    payment["status"] = "succeeded"
    assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert_one_grant_per_payment(hd, "buyer")


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_attempt_then_a_good_one_gives_once(hd, status):
    out = checkout(hd)
    paid(hd, out, status=status)
    assert check(hd, out["order_id"]).json()["order"]["status"] == "failed"
    assert pro_days(hd, "buyer") == 0
    good = paid(hd, out)  # the same checkout, another card
    assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert order_row(hd, out["order_id"]).provider_payment_id == good["payment_id"]
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


def test_dodo_down_on_the_return_gives_nothing_yet(hd):
    out = checkout(hd)
    payment = paid(hd, out)
    hd.dodo.fail = True
    assert check(hd, out["order_id"]).status_code == 502
    assert pro_days(hd, "buyer") == 0
    hd.dodo.fail = False
    assert webhook(hd, hook_body("payment.succeeded", payment)).json()["result"] == "paid"
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


def test_only_the_buyer_can_check_an_order(hd):
    out = checkout(hd)
    paid(hd, out)
    before = len(hd.dodo.calls)
    assert check(hd, out["order_id"], user="someone-else").status_code == 404
    assert hd.post(f"/v1/me/orders/{out['order_id']}/check").status_code == 401
    for bad in ("nope", "F" * 32, "0" * 31, "../../x"):
        assert check(hd, bad).status_code == 404
    assert len(hd.dodo.calls) == before and pro_days(hd, "buyer") == 0


def test_a_payment_made_in_another_checkout_does_not_pay_this_order(hd):
    mine, theirs = checkout(hd), checkout(hd, user="other", pass_="pro_3m")
    payment = paid(hd, mine)
    # Dodo (or anyone in between) answers the other session with my payment.
    hd.dodo.sessions[theirs["provider_order_id"]]["payment_id"] = payment["payment_id"]
    assert check(hd, theirs["order_id"], user="other").json()["order"]["status"] == "created"
    assert pro_days(hd, "other") == 0
    assert check(hd, mine["order_id"]).json()["order"]["status"] == "paid"
    assert_one_grant_per_payment(hd, "buyer")


def test_checking_a_razorpay_order_asks_dodo_nothing(hd):
    out = inr_checkout(hd)
    body = check(hd, out["order_id"]).json()
    assert body["order"]["status"] == "created" and body["order"]["provider"] == "razorpay"
    inr_confirm(hd, hd.rz.pay(out["provider_order_id"]))
    assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert hd.dodo.calls == []


def test_checks_at_dodo_are_limited_per_user(hd, monkeypatch):
    monkeypatch.setattr(payments, "CHECKS_PER_HOUR", 3)
    out = checkout(hd)
    assert [check(hd, out["order_id"]).status_code for _ in range(5)] == [200, 200, 200, 429, 429]
    other = checkout(hd, user="other")
    assert check(hd, other["order_id"], user="other").status_code == 200


def test_a_second_usd_pass_adds_its_days_and_stacks_on_an_inr_one(hd):
    inr_confirm(hd, hd.rz.pay(inr_checkout(hd)["provider_order_id"]))
    out = checkout(hd, pass_="pro_3m")
    paid(hd, out)
    check(hd, out["order_id"])
    assert pro_days(hd, "buyer") == 120
    assert_one_grant_per_payment(hd, "buyer")


# --- the webhook ---------------------------------------------------------------------------


def test_a_signed_webhook_gives_the_pass_and_a_replay_does_not(hd):
    out = checkout(hd)
    payment = paid(hd, out)
    body = hook_body("payment.succeeded", payment)
    r = webhook(hd, body)
    assert r.status_code == 200 and r.json() == {"ok": True, "result": "paid"}
    assert pro_days(hd, "buyer") == 30
    for msg_id in ("msg_1", "msg_2"):
        assert webhook(hd, body, signed(body, msg_id=msg_id)).json()["result"] == "already_paid"
    assert check(hd, out["order_id"]).json()["order"]["status"] == "paid"
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


def test_the_webhook_only_says_which_payment_and_dodo_says_what_it_is(hd):
    """A signed body claiming more than Dodo's API reports gives nothing."""
    out = checkout(hd)
    payment = paid(hd, out, status="processing")
    claimed = {**payment, "status": "succeeded"}
    assert webhook(hd, hook_body("payment.succeeded", claimed)).json()["result"] == "pending"
    assert pro_days(hd, "buyer") == 0
    slim = {"payload_type": "Payment", "payment_id": payment["payment_id"]}
    payment["status"] = "succeeded"
    assert webhook(hd, hook_body("payment.succeeded", slim)).json()["result"] == "paid"
    assert_one_grant_per_payment(hd, "buyer")


def bad_signatures(body: bytes) -> dict[str, dict[str, str]]:
    good = signed(body)
    return {
        "no headers": {},
        "no signature": {k: v for k, v in good.items() if k != "webhook-signature"},
        "no id": {k: v for k, v in good.items() if k != "webhook-id"},
        "no timestamp": {k: v for k, v in good.items() if k != "webhook-timestamp"},
        "another secret": signed(body, key=b"someone else's key"),
        "another id": {**good, "webhook-id": "msg_2"},
        "another time": {**good, "webhook-timestamp": str(int(time.time()) - 1)},
        "not a number": {**good, "webhook-timestamp": "now"},
        "too old": signed(body, at=time.time() - payments_dodo.TOLERANCE_S - 60),
        "from the future": signed(body, at=time.time() + payments_dodo.TOLERANCE_S + 60),
        "another version": {**good, "webhook-signature": good["webhook-signature"].replace("v1,", "v2,")},
        "no version": {**good, "webhook-signature": good["webhook-signature"][3:]},
        "razorpay's header": {"X-Razorpay-Signature": payments.sign("fake-webhook-secret", body)},
    }


@pytest.mark.parametrize("which", sorted(bad_signatures(b"")))
def test_an_unsigned_or_badly_signed_webhook_is_refused(hd, which):
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    before = len(hd.dodo.calls)
    r = webhook(hd, body, bad_signatures(body)[which])
    assert r.status_code == 400 and r.json()["error"]["code"] == "payment_unconfirmed"
    assert len(hd.dodo.calls) == before
    assert pro_days(hd, "buyer") == 0 and rows(hd, PlanEvent) == []


def test_a_webhook_body_changed_after_signing_is_refused(hd):
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    r = webhook(hd, body.replace(b"pro_1m", b"pro_3m"), signed(body))
    assert r.status_code == 400 and pro_days(hd, "buyer") == 0


def test_any_one_of_several_signatures_is_enough(hd):
    """While a secret is being rotated Dodo signs with both."""
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    headers = signed(body)
    headers["webhook-signature"] = f"v1,bm90IGl0 {headers['webhook-signature']}"
    assert webhook(hd, body, headers).json()["result"] == "paid"


def test_webhooks_are_refused_without_a_webhook_secret_or_without_dodo(make_hd):
    h = make_hd()
    out = checkout(h)
    body = hook_body("payment.succeeded", paid(h, out))
    h.svc.dodo = FakeDodo(secret="")
    assert webhook(h, body).status_code == 400
    h.svc.dodo = None
    r = webhook(h, body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "payments_off"
    assert pro_days(h, "buyer") == 0


def test_webhooks_need_the_internal_key(hd):
    body = hook_body("payment.succeeded", paid(hd, checkout(hd)))
    r = hd.client.post("/v1/payments/dodo/webhook", content=body, headers=signed(body))
    assert r.status_code == 401 and pro_days(hd, "buyer") == 0


def test_other_sales_and_other_events_are_acknowledged_and_ignored(hd):
    theirs = {"payment_id": "pay_other", "status": "succeeded", "total_amount": USD,
              "currency": "USD", "checkout_session_id": "cks_someone_elses",
              "product_cart": [{"product_id": "pdt_1m", "quantity": 1}], "metadata": {}}
    hd.dodo.payments["pay_other"] = theirs  # another product sold on the same Dodo account
    r = webhook(hd, hook_body("payment.succeeded", theirs))
    assert r.status_code == 200 and r.json()["result"] == "unknown_order"
    # Dodo's "send example" from the dashboard: a payment that doesn't exist.
    example = {"payload_type": "Payment", "payment_id": "pay_example"}
    assert webhook(hd, hook_body("payment.succeeded", example)).json()["result"] == "unknown_order"
    for event, data in (("subscription.active", {"subscription_id": "sub_1"}),
                        ("refund.failed", {"refund_id": "ref_1", "payment_id": "pay_other"}),
                        ("payment.succeeded", {"payment_id": "../../products/pdt_1m"}),
                        ("payment.succeeded", "a string")):
        r = webhook(hd, hook_body(event, data))
        assert r.status_code == 200 and r.json()["result"] == "ignored", event
    assert webhook(hd, b"not json").status_code == 400
    assert webhook(hd, b"[1, 2]").status_code == 400
    assert rows(hd, Order) == []


def test_a_payment_dodo_cannot_be_asked_about_is_tried_again(hd):
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    hd.dodo.fail = True
    assert webhook(hd, body).status_code == 502  # Dodo sends it again
    assert pro_days(hd, "buyer") == 0
    hd.dodo.fail = False
    assert webhook(hd, body).json()["result"] == "paid"
    assert_one_grant_per_payment(hd, "buyer")


def test_a_failed_payment_webhook_marks_the_order_and_a_later_one_pays_it(hd):
    out = checkout(hd)
    bad = paid(hd, out, status="failed")
    assert webhook(hd, hook_body("payment.failed", bad)).json()["result"] == "failed"
    row = order_row(hd, out["order_id"])
    assert row.status == "failed" and "declined" in row.note
    good = paid(hd, out)
    assert webhook(hd, hook_body("payment.succeeded", good)).json()["result"] == "paid"
    # The failure arriving late doesn't undo it.
    assert webhook(hd, hook_body("payment.failed", bad)).json()["result"] == "already_paid"
    assert order_row(hd, out["order_id"]).status == "paid" and pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


@pytest.mark.parametrize("session_id", [None, "cks_in_another_form"])
def test_a_payment_finds_its_order_by_its_metadata_without_the_session_id(hd, session_id):
    out = checkout(hd)
    payment = paid(hd, out)
    payment["checkout_session_id"] = session_id
    assert webhook(hd, hook_body("payment.succeeded", payment)).json()["result"] == "paid"
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


def test_metadata_naming_another_buyers_order_does_not_pay_it(hd):
    """Session and metadata disagree: nobody gets the pass."""
    mine, theirs = checkout(hd), checkout(hd, user="other")
    paid(hd, mine, metadata={"holt_order": theirs["order_id"], "pass": "pro_1m"})
    assert check(hd, mine["order_id"]).json()["order"]["status"] == "held"
    assert check(hd, theirs["order_id"], user="other").json()["order"]["status"] == "created"
    assert pro_days(hd, "buyer") == 0 and pro_days(hd, "other") == 0


def test_a_dodo_payment_never_settles_a_razorpay_order(hd):
    out = inr_checkout(hd)
    forged = {"payment_id": "pay_T99", "status": "succeeded", "total_amount": USD, "tax": 0,
              "currency": "USD", "checkout_session_id": out["provider_order_id"],
              "product_cart": [{"product_id": "pdt_1m", "quantity": 1}],
              "metadata": {"holt_order": out["order_id"]}}
    hd.dodo.payments["pay_T99"] = forged
    assert webhook(hd, hook_body("payment.succeeded", forged)).json()["result"] == "unknown_order"
    forged["checkout_session_id"] = None
    assert webhook(hd, hook_body("payment.succeeded", forged)).json()["result"] == "unknown_order"
    assert pro_days(hd, "buyer") == 0 and order_row(hd, out["order_id"]).status == "created"


def test_switching_payments_off_still_settles_usd_orders_already_paid(make_hd):
    h = make_hd()
    first, second = checkout(h), checkout(h, user="other")
    paid(h, first)
    late = paid(h, second)
    h.svc.settings.payments_enabled = False
    assert h.get("/v1/passes").json()["on_sale"] is False
    assert h.post("/v1/me/orders", {"pass": "pro_1m", "currency": "USD"},
                  user="buyer").status_code == 403
    assert check(h, first["order_id"]).json()["order"]["status"] == "paid"
    assert webhook(h, hook_body("payment.succeeded", late)).json()["result"] == "paid"
    assert pro_days(h, "buyer") == 30 and pro_days(h, "other") == 30


# --- concurrency -----------------------------------------------------------------------------


def test_the_return_and_the_webhooks_racing_give_once(hd):
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    jobs = [lambda: check(hd, out["order_id"])] * 4 + [lambda: webhook(hd, body)] * 4
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda f: f(), jobs))
    assert {r.status_code for r in results} == {200}
    assert pro_days(hd, "buyer") == 30
    assert len(rows(hd, PlanEvent)) == 1
    assert_one_grant_per_payment(hd, "buyer")


def test_many_webhook_deliveries_at_once_give_once(hd):
    out = checkout(hd)
    body = hook_body("payment.succeeded", paid(hd, out))
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(
            lambda i: webhook(hd, body, signed(body, msg_id=f"msg_{i}")), range(8)))
    assert sorted(r.json()["result"] for r in results) == ["already_paid"] * 7 + ["paid"]
    assert pro_days(hd, "buyer") == 30
    assert_one_grant_per_payment(hd, "buyer")


# --- refunds and disputes -----------------------------------------------------------------


def bought(h) -> tuple[dict, dict]:
    out = checkout(h)
    payment = paid(h, out)
    assert check(h, out["order_id"]).json()["order"]["status"] == "paid"
    return out, payment


def test_a_refund_is_written_on_the_order_and_changes_nothing_else(hd, caplog):
    out, payment = bought(hd)
    refund = {"payload_type": "Refund", "refund_id": "ref_T1", "amount": USD, "currency": "USD",
              "payment_id": payment["payment_id"], "status": "succeeded", "is_partial": False}
    body = hook_body("refund.succeeded", refund)
    with caplog.at_level(logging.ERROR, logger="holt_server.payments"):
        assert webhook(hd, body).json()["result"] == "recorded"
    assert "refund.succeeded ref_T1" in caplog.text and "Pro was not changed" in caplog.text
    row = order_row(hd, out["order_id"])
    assert row.status == "paid" and "refund.succeeded ref_T1: 700 USD" in row.note
    assert pro_days(hd, "buyer") == 30
    # Dodo sends it again: one line, not two.
    assert webhook(hd, body, signed(body, msg_id="msg_2")).json()["result"] == "recorded"
    assert order_row(hd, out["order_id"]).note.count("ref_T1") == 1
    assert hd.get("/v1/me/orders", user="buyer").json()["orders"][0]["status"] == "paid"
    assert_one_grant_per_payment(hd, "buyer")


def test_each_stage_of_a_dispute_is_written_on_the_order(hd):
    out, payment = bought(hd)
    dispute = {"payload_type": "Dispute", "dispute_id": "dp_T1", "amount": "7.00",
               "currency": "USD", "payment_id": payment["payment_id"],
               "dispute_status": "dispute_opened", "dispute_stage": "dispute"}
    for event in ("dispute.opened", "dispute.challenged", "dispute.lost", "dispute.opened"):
        assert webhook(hd, hook_body(event, dispute)).json()["result"] == "recorded"
    note = order_row(hd, out["order_id"]).note.splitlines()
    assert [line.split(" ", 1)[1] for line in note] == [
        "dispute.opened dp_T1: 7.00 USD", "dispute.challenged dp_T1: 7.00 USD",
        "dispute.lost dp_T1: 7.00 USD"]
    assert order_row(hd, out["order_id"]).status == "paid" and pro_days(hd, "buyer") == 30


def test_a_refund_for_a_payment_holt_does_not_know_is_acknowledged(hd):
    bought(hd)
    for data in ({"refund_id": "ref_T2", "payment_id": "pay_someone_elses", "amount": 1},
                 {"refund_id": "ref_T2"}, {"payment_id": "pay_D1"}):
        r = webhook(hd, hook_body("refund.succeeded", data))
        assert r.status_code == 200 and r.json()["result"] in ("unknown_order", "ignored")
    assert all(o.note is None for o in rows(hd, Order))


# --- purchase history ----------------------------------------------------------------------


def test_purchase_history_says_who_took_each_payment(hd):
    inr_confirm(hd, hd.rz.pay(inr_checkout(hd)["provider_order_id"]))
    out = checkout(hd, pass_="pro_3m")
    paid(hd, out)
    check(hd, out["order_id"])
    checkout(hd)  # opened, never paid: not a purchase
    orders = hd.get("/v1/me/orders", user="buyer").json()["orders"]
    assert [(o["provider"], o["currency"], o["amount"], o["status"], o["name"]) for o in orders] == [
        ("dodo", "USD", 1500, "paid", "Pro, 3 months"),
        ("razorpay", "INR", 9900, "paid", "Pro, 1 month")]


# --- the checks themselves -------------------------------------------------------------------


def test_the_signature_is_standard_webhooks(hd):
    """The worked example from the Standard Webhooks specification."""
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    body = b'{"test": 2432232314}'
    key = payments_dodo.signing_key(secret)
    assert payments_dodo.signature(key, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, body) == (
        "g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=")
    dodo = FakeDodo(secret=secret)
    headers = ("msg_p5jXN8AQM9LWM0D4loKWxJek", "1614265330",
               "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=")
    assert dodo.webhook_ok(body, *headers, at=1614265330 + 10)
    assert not dodo.webhook_ok(body, *headers)  # years old by now
    assert not dodo.webhook_ok(body + b" ", *headers, at=1614265330)


def test_ids_that_are_not_ids_never_reach_dodos_urls():
    dodo = FakeDodo()
    for bad in ("../products/pdt_1m", "pay_1?x=1", "", "pay 1", "a" * 81):
        for fetch in (dodo.fetch_payment, dodo.fetch_checkout, dodo.fetch_product):
            with pytest.raises(payments_dodo.DodoError):
                fetch(bad)
    assert dodo.calls == []


def test_errors_from_dodo_carry_its_code_but_never_the_key():
    import httpx

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert str(request.url) == "https://live.dodopayments.com/payments/pay_1"
        return httpx.Response(401, json={"code": "UNAUTHORIZED", "message": "Bad key."})

    dodo = payments_dodo.Dodo(API_KEY, "live", HOOK_SECRET, {},
                              client=httpx.Client(transport=httpx.MockTransport(answer)))
    with pytest.raises(payments_dodo.DodoError) as raised:
        dodo.fetch_payment("pay_1")
    assert raised.value.status == 401 and "UNAUTHORIZED Bad key." in str(raised.value)
    assert API_KEY not in str(raised.value)


def test_the_preflight_says_what_is_and_is_not_ready(tmp_path, pricing_file):
    s = settings(tmp_path, HOLT_PRICING_FILE=pricing_file, DODO_API_KEY=API_KEY)
    dodo = FakeDodo()
    ok, lines = payments_dodo.check(s, dodo)
    text = "\n".join(lines)
    assert ok is False  # no_product has a USD price and no product id
    assert "Dodo test mode" in text and "reads as a signing secret" in text
    assert "pro_1m (on sale): pdt_1m sells it for 700 cents" in text
    assert "not_yet (not on sale in the pricing file): pdt_12m sells it for 3900 cents" in text
    assert "no_product (on sale): no DODO_PRODUCT_NO_PRODUCT" in text
    assert "HOLT_PAYMENTS_ENABLED is 0" in text
    assert all(method == "GET" for method, _ in dodo.calls)  # it changes nothing at Dodo
    assert API_KEY not in text and HOOK_SECRET not in text

    dodo = FakeDodo(products={"pro_1m": "pdt_1m", "pro_3m": "pdt_3m", "not_yet": "pdt_12m",
                              "no_product": "pdt_3m"})
    dodo.catalog["pdt_1m"]["price"]["price"] = 70
    ok, lines = payments_dodo.check(s, dodo)
    text = "\n".join(lines)
    assert ok is False
    assert "pro_1m (on sale): pdt_1m can't sell it: its price is 70; the catalogue says 700" in text
    assert "no_product (on sale): pdt_3m can't sell it: its price is 1500" in text
    dodo.catalog["pdt_1m"]["price"]["price"] = 700
    dodo.catalog["pdt_6m"] = product(2500)
    dodo.products["no_product"] = "pdt_6m"
    assert payments_dodo.check(s, dodo)[0] is True

    assert payments_dodo.check(s, FakeDodo(secret=""))[0] is False
    dodo.fail = True
    ok, lines = payments_dodo.check(s, dodo)
    assert ok is False and "HTTP 500" in "\n".join(lines)
    assert payments_dodo.check(settings(tmp_path, DODO_API_KEY=""))[1] == ["DODO_API_KEY is not set"]
    assert payments_dodo.check(settings(tmp_path, DODO_API_KEY=API_KEY, DODO_ENV="prod"))[1] == [
        "DODO_ENV must be test or live"]
