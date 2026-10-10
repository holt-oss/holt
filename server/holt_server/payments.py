"""Pro passes: one-time payments, in INR through Razorpay and in USD through
Dodo Payments (API.md, "Passes").

A pass is one payment for a fixed number of days of Pro. It never renews.
Off by default. Passes are offered and orders created only when
`HOLT_PAYMENTS_ENABLED=1`, a processor is set up, and the pass is on sale
with a price in pricing.json (outside production, `HOLT_PASSES_ON_SALE=1`
puts every pass on sale). INR needs the Razorpay keys; USD needs Dodo's key,
its webhook secret and the pass's Dodo product id. Each works without the
other. Everything about an order (pass, days, price) comes from that file
when the order is created, never from the browser.

The Razorpay flow:

1. `POST /v1/me/orders {"pass"}` creates a Razorpay order for the pass's
   price and an `orders` row, and returns what Razorpay Checkout needs.
2. The buyer pays in Checkout. It hands the page `razorpay_order_id`,
   `razorpay_payment_id` and `razorpay_signature`, which `web/` passes to
   `POST /v1/me/orders/confirm`.
3. Razorpay also sends webhooks (`payment.authorized`, `payment.captured`,
   `order.paid`, `payment.failed`), which `web/` forwards, body untouched, to
   `POST /v1/payments/razorpay/webhook`.

Nothing is given on the browser's word. The confirm call checks the
payment signature (HMAC-SHA256 of `order_id|payment_id` with the key
secret) and then asks Razorpay for the payment; the webhook checks its
signature (HMAC-SHA256 of the raw body with the webhook secret). Either
way, Pro is given only for a captured payment whose amount and currency
match the order; an authorized one is captured first, and one that doesn't
match puts the order on `held` for a person to look at.

Giving the pass is one transaction: `UPDATE orders SET status='paid' WHERE
status IN ('created', 'failed')` and, only if that took, the user's plan set
to Pro for the pass's days, counted from when their current Pro ends if it
hasn't yet (a `PlanEvent` whose `reference` is the payment id). The confirm
call and the webhook both arrive, in either order, sometimes more than once,
sometimes at the same moment: exactly one of them gives it.

An order row keeps the pass id in `pack_id` and its days in `expires_days`
(the columns date from credit packs; `credits` is 0).

The Dodo flow (the client, and what it relies on in Dodo's API, are in
payments_dodo.py):

1. `POST /v1/me/orders {"pass", "currency": "USD"}` checks that the pass's
   Dodo product is still a one-time USD product at the catalogue's price,
   opens a hosted checkout for one of it (USD only, no discount codes), and
   keeps the session id on an `orders` row. The buyer is sent to Dodo.
2. Dodo sends them back to the thank-you page, which calls
   `POST /v1/me/orders/{id}/check`: the server asks Dodo for the session's
   payment with its API key. Nothing in the return address is read.
3. Dodo also sends webhooks (`payment.succeeded`, `payment.failed`, …), which
   `web/` forwards, body untouched, to `POST /v1/payments/dodo/webhook`. The
   signature is checked (Standard Webhooks); the payment it names is then
   fetched from Dodo, so both ways in settle the same thing.

Pro is given only for a `succeeded` payment that bought exactly one of the
pass's product, in USD, for the order's price (Dodo may add tax on top);
anything else puts the order on `held`. Giving it is the same transaction as
Razorpay's, so the return and the webhooks give once between them.

A refund or a dispute (`refund.succeeded`, `dispute.*`) is written on the
order's `note` and logged as an error. It changes nothing by itself: Pro
stays until a person takes it away (`python -m holt_server.credits`).

With payments switched off, confirm, check and the webhooks still settle
orders that already exist (someone may have paid just before the switch); no
new order can be made.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from holt_server import account_mail, credits, entitlements, payments_dodo, pricing, schema
from holt_server.db import Order, User, iso, now, utc
from holt_server.deps import Caller, caller, internal, services, signed_in
from holt_server.errors import ApiError, upstream

if TYPE_CHECKING:
    from holt_server.services import Services
    from holt_server.settings import Settings

log = logging.getLogger("holt_server.payments")

router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})

API = "https://api.razorpay.com/v1"
TIMEOUT_S = 20.0
CURRENCY = "INR"
# Razorpay's smallest INR charge (paise).
MIN_AMOUNT = 100
# Razorpay webhook bodies are a few KB.
MAX_WEBHOOK_BYTES = 256 * 1024
# Times an hour one user's unsettled Dodo orders are looked up at Dodo (the
# thank-you page asks a few times per purchase).
CHECKS_PER_HOUR = 120

ORDER_ID = re.compile(r"^order_[A-Za-z0-9]{1,40}$")
PAYMENT_ID = re.compile(r"^pay_[A-Za-z0-9]{1,40}$")
# Ours: 32 hex characters.
HOLT_ORDER_ID = re.compile(r"^[0-9a-f]{32}$")

OFF = "Passes aren't on sale yet. Everything free in Holt keeps working."
UNCONFIRMED = ("We couldn't confirm that payment. If money left your account, Pro "
               "will start in a few minutes, or the payment will be refunded.")


# --- Razorpay -------------------------------------------------------------------------


class ProviderError(Exception):
    pass


def sign(secret: str, message: str | bytes) -> str:
    data = message.encode("utf-8") if isinstance(message, str) else message
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


def same(expected: str, given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(expected.encode(), given.strip().encode())


class Razorpay:
    """The Razorpay calls Holt makes, over HTTPS with basic auth (no SDK).
    Tests replace `svc.razorpay` with a fake that has the same methods."""

    name = "razorpay"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str,
                 client: httpx.Client | None = None) -> None:
        self.key_id = key_id
        self._secret = key_secret
        self._webhook_secret = webhook_secret
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        try:
            res = self._client.request(method, f"{API}{path}", json=body,
                                       auth=(self.key_id, self._secret))
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay {path}: {type(exc).__name__}") from exc
        if res.status_code >= 400:
            try:
                detail = res.json().get("error", {}).get("description", "")
            except ValueError:
                detail = ""
            raise ProviderError(f"razorpay {path}: HTTP {res.status_code} {detail}")
        return res.json()

    def create_order(self, *, amount: int, currency: str, receipt: str,
                     notes: dict[str, str]) -> dict:
        return self._call("POST", "/orders", {"amount": amount, "currency": currency,
                                               "receipt": receipt[:40], "notes": notes})

    def fetch_payment(self, payment_id: str) -> dict:
        return self._call("GET", f"/payments/{payment_id}")

    def capture(self, payment_id: str, *, amount: int, currency: str) -> dict:
        return self._call("POST", f"/payments/{payment_id}/capture",
                          {"amount": amount, "currency": currency})

    def payment_signature_ok(self, order_id: str, payment_id: str, signature: str) -> bool:
        return same(sign(self._secret, f"{order_id}|{payment_id}"), signature)

    def webhook_signature_ok(self, body: bytes, signature: str | None) -> bool:
        return bool(self._webhook_secret) and same(sign(self._webhook_secret, body), signature)

    def close(self) -> None:
        self._client.close()


def build(settings: Settings) -> Razorpay | None:
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        return None
    return Razorpay(settings.razorpay_key_id, settings.razorpay_key_secret,
                    settings.razorpay_webhook_secret)


async def call(fn, *args, **kwargs) -> dict:
    """A Razorpay or Dodo call, off the event loop, its failure made plain."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ProviderError as exc:
        log.warning("razorpay call failed: %s", exc)
        raise upstream("Razorpay") from exc
    except payments_dodo.DodoError as exc:
        log.warning("dodo call failed: %s", exc)
        raise upstream("Dodo Payments") from exc


# --- what is on sale -----------------------------------------------------------------


def razorpay_on(svc: Services) -> bool:
    return svc.settings.payments_enabled and svc.razorpay is not None


def dodo_on(svc: Services) -> bool:
    """Whether USD can be sold at all: the key and a webhook secret that reads."""
    return (svc.settings.payments_enabled and svc.dodo is not None
            and svc.dodo.webhooks_on)


def payments_on(svc: Services) -> bool:
    return razorpay_on(svc) or dodo_on(svc)


def price(p: pricing.Pass) -> int | None:
    """The pass's INR price when it is on sale, else None."""
    amount = p.price.inr_paise
    if not p.on_sale or amount is None or amount < MIN_AMOUNT:
        return None
    return amount


def usd_price(svc: Services, pid: str, p: pricing.Pass) -> int | None:
    """The pass's USD price when it is on sale and has a Dodo product, else None."""
    amount = p.price.usd_cents
    if not p.on_sale or not amount or pid not in svc.dodo.products:
        return None
    return amount


def prices(svc: Services, pid: str, p: pricing.Pass) -> list[schema.PassPrice]:
    """What the pass can be bought for now, INR first."""
    out = []
    if razorpay_on(svc) and (amount := price(p)) is not None:
        out.append(schema.PassPrice(currency=CURRENCY, amount=amount))
    if dodo_on(svc) and (amount := usd_price(svc, pid, p)) is not None:
        out.append(schema.PassPrice(currency=payments_dodo.CURRENCY, amount=amount))
    return out


def passes_body(svc: Services) -> schema.Passes:
    if not payments_on(svc):
        return schema.Passes(on_sale=False, passes=[], features=[])
    cat = entitlements.catalogue(svc)
    out = [schema.PassOffer(id=pid, name=p.name, days=p.days, amount=sold[0].amount,
                            currency=sold[0].currency, prices=sold)
           for pid, p in cat.passes.items() if (sold := prices(svc, pid, p))]
    if not out:
        return schema.Passes(on_sale=False, passes=[], features=[])
    features = [schema.PassFeature(id=f, name=cat.features[f].name, per_month=a.per_month,
                                   unlimited=a.unlimited)
                for f, a in cat.plans[pricing.PRO].features.items()]
    return schema.Passes(on_sale=True, passes=out, features=features)


def startup_line(svc: Services) -> tuple[int, str]:
    """The one line the server logs about passes at startup, and its level."""
    s = svc.settings
    if s.passes_on_sale and not s.sell_every_pass:
        return logging.ERROR, ("passes: HOLT_PASSES_ON_SALE is set in production, so it is "
                               "ignored; only the pricing file puts a pass on sale there")
    if not s.payments_enabled:
        return logging.INFO, "passes: off (HOLT_PAYMENTS_ENABLED is 0)"
    trouble = dodo_trouble(svc)
    level = logging.WARNING if trouble else logging.INFO
    if svc.razorpay is None and svc.dodo is None:
        return level, f"passes: off (no Razorpay keys, no Dodo key){trouble}"
    offers = passes_body(svc).passes
    if not offers:
        return level, f"passes: off (no pass is on sale){trouble}"
    how = " (HOLT_PASSES_ON_SALE)" if s.sell_every_pass else ""
    sold = []
    inr = [o.id for o in offers if any(p.currency == CURRENCY for p in o.prices)]
    if inr:
        mode = "test" if svc.razorpay.key_id.startswith("rzp_test_") else "LIVE"
        sold.append(f"{', '.join(inr)}; Razorpay {mode} keys")
    usd = [o.id for o in offers
           if any(p.currency == payments_dodo.CURRENCY for p in o.prices)]
    if usd:
        mode = "test" if svc.dodo.env == "test" else "LIVE"
        sold.append(f"{', '.join(usd)} in USD; Dodo {mode} mode")
    return level, f"passes: on sale{how}: {'; '.join(sold)}{trouble}"


def dodo_trouble(svc: Services) -> str:
    """Why USD isn't on sale although someone began to set Dodo up, for the
    startup line; empty when it is, or when nobody did."""
    s = svc.settings
    if svc.dodo is None:
        return "; Dodo off (DODO_ENV must be test or live)" if s.dodo_api_key else ""
    if not svc.dodo.webhooks_on:
        return "; Dodo off (DODO_WEBHOOK_SECRET is missing or not a whsec_ secret)"
    if not svc.dodo.products:
        return "; Dodo off (no DODO_PRODUCT_PRO_* is set)"
    return ""


def order_name(o: Order, p: pricing.Pass | None) -> str:
    if p is not None:
        return f"Pro, {p.name}"
    if o.credits:  # a credit pack, from before passes
        return f"{o.credits} credits"
    return f"Pro, {o.expires_days} days"


def order_body(svc: Services, o: Order) -> schema.Order:
    p = entitlements.catalogue(svc).passes.get(o.pack_id)
    return schema.Order(id=o.id, item=o.pack_id, name=order_name(o, p),
                        days=None if o.credits else o.expires_days,
                        amount=o.amount, currency=o.currency, provider=o.provider,
                        status=o.status,
                        created_at=iso(o.created_at), paid_at=iso(o.paid_at))


# --- settling a payment ------------------------------------------------------------------


async def order_by_provider_id(svc: Services, provider_order_id: str | None) -> Order | None:
    if not provider_order_id:
        return None
    async with svc.db.session() as s:
        return (await s.execute(select(Order).where(
            Order.provider_order_id == provider_order_id))).scalar_one_or_none()


def pass_ends(user: User | None, days: int, at: datetime) -> datetime | None:
    """When Pro ends after adding a pass of `days`: from the end of the Pro
    the user has now if it hasn't lapsed, else from `at`. None: they already
    have Pro with no end (an admin grant), which a pass doesn't shorten."""
    start = at
    if user is not None and user.plan == pricing.PRO:
        ends = utc(user.plan_expires_at)
        if ends is None:
            return None
        start = max(ends, at)
    return start + timedelta(days=days)


async def credit(svc: Services, order_id: str, payment_id: str) -> bool:
    """Mark the order paid by `payment_id` and give what it bought,
    atomically: a pass's days of Pro (or, for an order from before passes, its
    credits). True if this call did it; False if the order was already paid
    (or the payment already paid another order, which is logged)."""
    at = now()
    async with svc.db.session() as s:
        order = await s.get(Order, order_id)
        try:
            took = await s.execute(
                update(Order).where(Order.id == order_id,
                                    Order.status.in_(("created", "failed")))
                .values(status="paid", provider_payment_id=payment_id, paid_at=at,
                        updated_at=at, note=None))
            if took.rowcount != 1:
                await s.rollback()
                return False
            if order.credits:
                expires = (at + timedelta(days=order.expires_days)
                           if order.expires_days else None)
                lot = await credits.add_lot(s, order.user_id, order.credits, origin="pack",
                                            kind="purchase", pack_id=order.pack_id,
                                            reference=payment_id, expires_at=expires)
                await s.execute(update(Order).where(Order.id == order_id)
                                .values(lot_id=lot.id))
            else:
                user = (await s.execute(select(User).where(User.id == order.user_id)
                                        .with_for_update())).scalar_one()
                ends = pass_ends(user, order.expires_days or 0, at)
                if not (user.plan == pricing.PRO and ends is None):
                    await entitlements.write_plan(
                        s, svc, order.user_id, pricing.PRO, expires_at=ends,
                        reason=f"pass {order.pack_id}", actor="payment", reference=payment_id)
            await s.commit()
        except IntegrityError:
            await s.rollback()
            log.error("payment %s is already recorded against another order; order %s "
                      "not credited", payment_id, order_id)
            return False
    log.info("order %s (%s) paid by %s for %s", order_id, order.pack_id, payment_id,
             order.user_id)
    account_mail.kick(svc)  # the receipt
    return True


async def set_status(svc: Services, order_id: str, status: str, note: str) -> None:
    """`failed` or `held`, from an unpaid order only: a paid one stays paid."""
    async with svc.db.session() as s:
        await s.execute(update(Order).where(Order.id == order_id,
                                            Order.status.in_(("created", "failed")))
                        .values(status=status, note=note, updated_at=now()))
        await s.commit()


async def settle(svc: Services, payment: dict[str, Any]) -> str:
    """Act on a payment Razorpay vouched for (a signed webhook, or a fetch after
    a signed callback). Returns what happened, for the log and the tests."""
    order = await order_by_provider_id(svc, payment.get("order_id"))
    pid = str(payment.get("id") or "")
    if order is None:
        return "unknown_order"
    if not PAYMENT_ID.match(pid):
        return "ignored"
    if order.status == "paid":
        if order.provider_payment_id != pid and payment.get("status") == "captured":
            log.error("order %s was paid twice (%s, then %s): refund the second",
                      order.id, order.provider_payment_id, pid)
        return "already_paid"
    if payment.get("status") == "failed":
        await set_status(svc, order.id, "failed", str(payment.get("error_description") or ""))
        return "failed"
    amount, currency = payment.get("amount"), str(payment.get("currency") or "").upper()
    if amount != order.amount or currency != order.currency:
        note = f"payment {pid} was {amount} {currency}; the order is {order.amount} {order.currency}"
        log.error("order %s held: %s", order.id, note)
        await set_status(svc, order.id, "held", note)
        return "held"
    status = payment.get("status")
    if status == "authorized":
        rz = svc.razorpay
        if rz is None:
            return "pending"
        try:
            captured = await asyncio.to_thread(rz.capture, pid, amount=order.amount,
                                               currency=order.currency)
        except ProviderError as exc:
            # Often: captured already (by the other path, or automatically).
            log.info("capture of %s: %s; checking", pid, exc)
            captured = await call(rz.fetch_payment, pid)
        status = captured.get("status")
    if status == "captured":
        return "paid" if await credit(svc, order.id, pid) else "already_paid"
    return "pending"


# --- Dodo: settling a payment -------------------------------------------------------------


async def dodo_order(svc: Services, payment: dict[str, Any]) -> Order | None:
    """The order a Dodo payment belongs to: the one whose checkout session it
    was made in, else the one its metadata names (the server put the order's
    id there when it opened the checkout; a buyer can't)."""
    session_id = payment.get("checkout_session_id")
    order = await order_by_provider_id(svc, session_id if isinstance(session_id, str) else None)
    if order is None:
        meta = payment.get("metadata")
        named = meta.get("holt_order") if isinstance(meta, dict) else None
        if isinstance(named, str) and HOLT_ORDER_ID.match(named):
            async with svc.db.session() as s:
                order = await s.get(Order, named)
    return order if order is not None and order.provider == payments_dodo.Dodo.name else None


async def settle_dodo(svc: Services, payment: dict[str, Any]) -> str:
    """Act on a payment as Dodo's API returned it (`GET /payments/{id}`, asked
    with our key). Returns what happened, for the log and the tests."""
    order = await dodo_order(svc, payment)
    pid = str(payment.get("payment_id") or "")
    if order is None:
        return "unknown_order"
    if not payments_dodo.PAYMENT_ID.match(pid):
        return "ignored"
    status = payment.get("status")
    if order.status == "paid":
        if order.provider_payment_id != pid and status == "succeeded":
            log.error("order %s was paid twice (%s, then %s): refund the second",
                      order.id, order.provider_payment_id, pid)
        return "already_paid"
    if status in ("failed", "cancelled"):
        await set_status(svc, order.id, "failed", str(payment.get("error_message") or ""))
        return "failed"
    if status != "succeeded":
        return "pending"
    product_id = svc.dodo.products.get(order.pack_id) if svc.dodo is not None else None
    why = payments_dodo.mismatch(payment, product_id=product_id, amount=order.amount,
                                 currency=order.currency, order_id=order.id)
    if why:
        note = f"payment {pid}: {why}"
        log.error("order %s held: %s", order.id, note)
        await set_status(svc, order.id, "held", note)
        return "held"
    return "paid" if await credit(svc, order.id, pid) else "already_paid"


async def dodo_payment(svc: Services, payment_id: str) -> dict[str, Any] | None:
    """The payment, from Dodo. None if Dodo has no such payment."""
    try:
        payment = await asyncio.to_thread(svc.dodo.fetch_payment, payment_id)
    except payments_dodo.DodoError as exc:
        if exc.status == 404:
            return None
        log.warning("dodo call failed: %s", exc)
        raise upstream("Dodo Payments") from exc
    if payment.get("payment_id") != payment_id:
        log.error("dodo answered for payment %r when asked for %s",
                  str(payment.get("payment_id"))[:80], payment_id)
        raise upstream("Dodo Payments")
    return payment


async def look_up(svc: Services, order: Order) -> str:
    """Ask Dodo what became of the order's checkout, and settle it."""
    session = await call(svc.dodo.fetch_checkout, order.provider_order_id)
    pid = session.get("payment_id")
    if not isinstance(pid, str) or not payments_dodo.PAYMENT_ID.match(pid):
        return "pending"  # the buyer hasn't submitted a payment yet
    payment = await dodo_payment(svc, pid)
    if payment is None:
        return "pending"
    found = await dodo_order(svc, payment)
    if found is None or found.id != order.id:
        log.error("dodo payment %s is not for order %s", pid, order.id)
        return "ignored"
    return await settle_dodo(svc, payment)


async def after_sale(svc: Services, event: str, what: dict[str, Any]) -> str:
    """A refund or a dispute on a payment that paid an order: written on the
    order and logged as an error, once. Pro is neither taken away nor quietly
    kept: a person decides (`python -m holt_server.credits`)."""
    pid = what.get("payment_id")
    ref = str(what.get("refund_id") or what.get("dispute_id") or "")[:80]
    if not isinstance(pid, str) or not pid or not ref:
        return "ignored"
    line = f"{event} {ref}"
    async with svc.db.session() as s:
        order = (await s.execute(
            select(Order).where(Order.provider == payments_dodo.Dodo.name,
                                Order.provider_payment_id == pid)
            .with_for_update())).scalar_one_or_none()
        if order is None:
            return "unknown_order"
        if line in (order.note or ""):
            return "recorded"
        at = now()
        money = f"{what.get('amount')} {what.get('currency') or ''}".strip()[:40]
        entry = f"{at.date().isoformat()} {line}: {money}"
        order.note = f"{order.note}\n{entry}" if order.note else entry
        order.updated_at = at
        await s.commit()
        order_id, user_id, item = order.id, order.user_id, order.pack_id
    log.error("order %s (%s, user %s): %s on payment %s for %s. Pro was not changed: "
              "decide by hand", order_id, item, user_id, line, pid, money)
    return "recorded"


# --- routes ----------------------------------------------------------------------------


class OrderIn(BaseModel):
    pass_: str = Field(alias="pass", min_length=1, max_length=40)
    # INR is paid through Razorpay, USD through Dodo Payments.
    currency: Literal["INR", "USD"] = "INR"


class ConfirmIn(BaseModel):
    """What Razorpay Checkout hands the page on success, passed on unchanged."""

    razorpay_order_id: str = Field(max_length=60)
    razorpay_payment_id: str = Field(max_length=60)
    razorpay_signature: str = Field(max_length=200)


@router.get("/passes", dependencies=[Depends(internal)])
async def get_passes(request: Request) -> schema.Passes:
    return passes_body(services(request))


@router.post("/me/orders")
async def create_order(body: OrderIn, request: Request,
                       who: Caller = Depends(caller)) -> schema.Checkout:
    svc = services(request)
    user_id = signed_in(who)
    if not payments_on(svc):
        raise ApiError("payments_off", OFF)
    pid = body.pass_
    p = entitlements.catalogue(svc).passes.get(pid)
    if body.currency == payments_dodo.CURRENCY:
        return await create_dodo_order(svc, who, user_id, pid, p)
    amount = price(p) if p and razorpay_on(svc) else None
    if p is None or amount is None:
        raise ApiError("invalid_request", "That pass isn't on sale.")
    svc.limiter.hit(who.rate_key, who.limit(svc))
    await credits.ensure_user(svc, user_id)
    row = Order(id=uuid.uuid4().hex, user_id=user_id, pack_id=pid, credits=0,
                expires_days=p.days, amount=amount, currency=CURRENCY,
                provider="razorpay", status="created")
    rz = svc.razorpay
    made = await call(rz.create_order, amount=amount, currency=CURRENCY, receipt=row.id,
                      notes={"holt_order": row.id, "pass": pid})
    if made.get("amount") != amount or not ORDER_ID.match(str(made.get("id") or "")):
        log.error("razorpay order for %s came back as %r", row.id,
                  {k: made.get(k) for k in ("id", "amount", "currency")})
        raise upstream("Razorpay")
    row.provider_order_id = made["id"]
    at = now()
    row.created_at = row.updated_at = at
    async with svc.db.session() as s:
        s.add(row)
        await s.commit()
    return schema.Checkout(order_id=row.id, provider="razorpay", key_id=rz.key_id,
                           provider_order_id=row.provider_order_id, amount=amount,
                           currency=CURRENCY, name="Holt", description=f"Pro, {p.name}",
                           item=pid, days=p.days)


async def product_sells(svc: Services, product_id: str, amount: int) -> None:
    """Refuse to open a checkout unless the Dodo product is still a one-time
    USD product at the catalogue's price: Dodo charges what the product says,
    so this is what keeps the price the server's. Asked again every few minutes."""
    dodo = svc.dodo
    at = now().timestamp()
    matched = dodo.checked.get(product_id)
    if matched and matched[0] == amount and at - matched[1] < payments_dodo.PRODUCT_CHECK_S:
        return
    product = await call(dodo.fetch_product, product_id)
    why = payments_dodo.product_problem(product, amount)
    if why:
        dodo.checked.pop(product_id, None)
        log.error("dodo product %s can't sell its pass: %s", product_id, why)
        raise upstream("Dodo Payments")
    dodo.checked[product_id] = (amount, at)


async def create_dodo_order(svc: Services, who: Caller, user_id: str, pid: str,
                            p: pricing.Pass | None) -> schema.Checkout:
    amount = usd_price(svc, pid, p) if p and dodo_on(svc) else None
    if p is None or amount is None:
        raise ApiError("invalid_request", "That pass isn't on sale.")
    svc.limiter.hit(who.rate_key, who.limit(svc))
    await credits.ensure_user(svc, user_id)
    dodo = svc.dodo
    product_id = dodo.products[pid]
    await product_sells(svc, product_id, amount)
    row = Order(id=uuid.uuid4().hex, user_id=user_id, pack_id=pid, credits=0,
                expires_days=p.days, amount=amount, currency=payments_dodo.CURRENCY,
                provider=dodo.name, status="created")
    site = svc.settings.web_url.rstrip("/")
    made = await call(dodo.create_checkout, product_id=product_id,
                      return_url=f"{site}/pricing/thanks?order={row.id}",
                      cancel_url=f"{site}/pricing?currency=usd",
                      metadata={"holt_order": row.id, "pass": pid})
    session_id, url = made.get("session_id"), made.get("checkout_url")
    if not (isinstance(session_id, str) and payments_dodo.ID.match(session_id)
            and isinstance(url, str) and url.startswith("https://")):
        log.error("dodo checkout for %s came back without a session id or a URL", row.id)
        raise upstream("Dodo Payments")
    row.provider_order_id = session_id
    at = now()
    row.created_at = row.updated_at = at
    async with svc.db.session() as s:
        s.add(row)
        await s.commit()
    return schema.Checkout(order_id=row.id, provider="dodo", key_id=None,
                           provider_order_id=session_id, checkout_url=url, amount=amount,
                           currency=payments_dodo.CURRENCY, name="Holt",
                           description=f"Pro, {p.name}", item=pid, days=p.days)


async def confirmed(svc: Services, order_id: str, user_id: str) -> schema.OrderConfirmed:
    async with svc.db.session() as s:
        order = await s.get(Order, order_id)
    user = await credits.get_user(svc, user_id)
    cat = entitlements.catalogue(svc)
    plan = entitlements.effective_plan(cat, user)
    return schema.OrderConfirmed(
        order=order_body(svc, order), plan=plan,
        plan_expires_at=iso(user.plan_expires_at) if plan != pricing.FREE else None)


@router.post("/me/orders/confirm")
async def confirm_order(body: ConfirmIn, request: Request,
                        who: Caller = Depends(caller)) -> schema.OrderConfirmed:
    svc = services(request)
    user_id = signed_in(who)
    rz = svc.razorpay
    if rz is None:
        raise ApiError("payments_off", OFF)
    oid, pid = body.razorpay_order_id, body.razorpay_payment_id
    if not (ORDER_ID.match(oid) and PAYMENT_ID.match(pid)
            and rz.payment_signature_ok(oid, pid, body.razorpay_signature)):
        log.warning("confirm for %s with a bad signature (user %s)", oid[:60], user_id)
        raise ApiError("payment_unconfirmed", UNCONFIRMED)
    order = await order_by_provider_id(svc, oid)
    if order is None or order.user_id != user_id:
        raise ApiError("not_found", "We couldn't find that order.")
    if order.status != "paid":
        payment = await call(rz.fetch_payment, pid)
        if payment.get("order_id") != oid or payment.get("id") != pid:
            log.error("payment %s is not for order %s", pid, oid)
            raise ApiError("payment_unconfirmed", UNCONFIRMED)
        result = await settle(svc, payment)
        log.info("confirm %s %s -> %s", oid, pid, result)
    return await confirmed(svc, order.id, user_id)


@router.post("/me/orders/{order_id}/check")
async def check_order(order_id: str, request: Request,
                      who: Caller = Depends(caller)) -> schema.OrderConfirmed:
    """Where one of the user's orders stands. For a Dodo order not settled
    yet, Dodo is asked first (the buyer is back from its checkout): nothing
    comes from the browser but which order to look at."""
    svc = services(request)
    user_id = signed_in(who)
    order = None
    if HOLT_ORDER_ID.match(order_id):
        async with svc.db.session() as s:
            order = await s.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise ApiError("not_found", "We couldn't find that order.")
    if (order.provider == payments_dodo.Dodo.name and order.status in ("created", "failed")
            and svc.dodo is not None):
        svc.read_limiter.hit(f"order-check:{who.rate_key}", CHECKS_PER_HOUR)
        result = await look_up(svc, order)
        log.info("check %s -> %s", order.id, result)
    return await confirmed(svc, order.id, user_id)


@router.get("/me/orders")
async def list_orders(request: Request, who: Caller = Depends(caller),
                      limit: int = Query(50, ge=1, le=200)) -> schema.Orders:
    """The user's purchases, newest first. Checkouts never finished are left out."""
    svc = services(request)
    user_id = signed_in(who)
    async with svc.db.session() as s:
        rows = (await s.execute(
            select(Order).where(Order.user_id == user_id, Order.status != "created")
            .order_by(Order.created_at.desc()).limit(limit))).scalars().all()
    return schema.Orders(orders=[order_body(svc, o) for o in rows])


async def bounded_body(request: Request, limit: int = MAX_WEBHOOK_BYTES) -> bytes:
    too_big = ApiError("invalid_request", "Request body too large.", status=413)
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > limit):
        raise too_big
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


PAYMENT_EVENTS = {"payment.authorized", "payment.captured", "payment.failed", "order.paid"}


@router.post("/payments/razorpay/webhook", dependencies=[Depends(internal)])
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Razorpay's webhook, forwarded by `web/` with the body byte for byte.
    Answers 200 for anything signed, even events it ignores, so Razorpay
    doesn't retry them; 400 for anything not signed."""
    svc = services(request)
    rz = svc.razorpay
    if rz is None:
        raise ApiError("payments_off", OFF)
    body = await bounded_body(request)
    if not rz.webhook_signature_ok(body, x_razorpay_signature):
        log.warning("razorpay webhook with a bad signature refused")
        raise ApiError("payment_unconfirmed", "Bad webhook signature.")
    try:
        data = json.loads(body)
        event = str(data.get("event") or "")
        payment = ((data.get("payload") or {}).get("payment") or {}).get("entity")
    except (ValueError, AttributeError) as exc:
        raise ApiError("invalid_request", "Malformed webhook body.") from exc
    if event not in PAYMENT_EVENTS or not isinstance(payment, dict):
        return {"ok": True, "result": "ignored"}
    result = await settle(svc, payment)
    log.info("razorpay webhook %s %s -> %s", event, payment.get("id"), result)
    return {"ok": True, "result": result}


@router.post("/payments/dodo/webhook", dependencies=[Depends(internal)])
async def dodo_webhook(
    request: Request,
    webhook_id: str | None = Header(default=None),
    webhook_timestamp: str | None = Header(default=None),
    webhook_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Dodo's webhook, forwarded by `web/` with the body byte for byte and its
    three Standard Webhooks headers. Answers 200 for anything signed, even
    events it ignores; 400 for anything not signed; 502 (Dodo retries) when
    Dodo can't be asked about the payment."""
    svc = services(request)
    dodo = svc.dodo
    if dodo is None:
        raise ApiError("payments_off", OFF)
    body = await bounded_body(request)
    if not dodo.webhook_ok(body, webhook_id, webhook_timestamp, webhook_signature):
        log.warning("dodo webhook with a bad signature refused")
        raise ApiError("payment_unconfirmed", "Bad webhook signature.")
    try:
        data = json.loads(body)
        event = str(data.get("type") or "")
        what = data.get("data")
    except (ValueError, AttributeError) as exc:
        raise ApiError("invalid_request", "Malformed webhook body.") from exc
    if not isinstance(what, dict):
        return {"ok": True, "result": "ignored"}
    if event in payments_dodo.AFTER_SALE_EVENTS:
        result = await after_sale(svc, event, what)
    elif event in payments_dodo.PAYMENT_EVENTS:
        result = await dodo_event(svc, what)
    else:
        return {"ok": True, "result": "ignored"}
    log.info("dodo webhook %s %s -> %s", event, str(what.get("payment_id"))[:80], result)
    return {"ok": True, "result": result}


async def dodo_event(svc: Services, what: dict[str, Any]) -> str:
    """A signed payment event. It says which payment; what the payment is,
    and which order it is for, comes from Dodo's API, the same as on the
    buyer's return."""
    pid = what.get("payment_id")
    if not isinstance(pid, str) or not payments_dodo.PAYMENT_ID.match(pid):
        return "ignored"
    payment = await dodo_payment(svc, pid)
    if payment is None:
        return "unknown_order"
    return await settle_dodo(svc, payment)
