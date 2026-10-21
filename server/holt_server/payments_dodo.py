"""Dodo Payments: the calls Holt makes for USD passes, and its webhook signature.

Dodo is the merchant of record for USD. The buyer pays on Dodo's hosted
checkout and comes back to Holt; `payments.py` has the flow, this is the
client. What it relies on, from docs.dodopayments.com:

- Hosts: `https://test.dodopayments.com` and `https://live.dodopayments.com`,
  `Authorization: Bearer <key>`. A key works only on its own mode's host.
- `POST /checkouts` (`product_cart`, `return_url`, `metadata`, …) →
  `session_id`, `checkout_url`.
- `GET /checkouts/{id}` → `payment_id`, `payment_status` (both null until the
  buyer submits a payment).
- `GET /payments/{payment_id}` → `status` (`succeeded`, `failed`, `cancelled`,
  `processing`, …), `total_amount` (with tax) and `tax` in cents, `currency`,
  `product_cart` (`product_id`, `quantity`), `checkout_session_id`, `metadata`.
- `GET /products/{id}` → `price` (`type`, `price`, `currency`, …).
- Webhooks follow Standard Webhooks: headers `webhook-id`,
  `webhook-timestamp` and `webhook-signature`; the signature is the base64
  HMAC-SHA256 of `{id}.{timestamp}.{body}` with the base64-decoded secret
  (after its `whsec_`), sent as space-separated `v1,<signature>`.

A price in Dodo lives on the product, not in the request, so the checks that
keep the catalogue in charge are here too: `product_problem` before a
checkout is opened, `mismatch` before a payment gives anything.

`python -m holt_server.payments_dodo` checks the settings against Dodo
without changing anything there: the key, the webhook secret, and each
pass's product against the catalogue's price. Run it before switching USD on.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from holt_server.settings import Settings

HOSTS = {"test": "https://test.dodopayments.com", "live": "https://live.dodopayments.com"}
# Two calls fit in the 20 seconds the web app waits for the server.
TIMEOUT_S = 10.0
CURRENCY = "USD"
# How far a webhook's timestamp may be from now (Standard Webhooks: 5 minutes).
TOLERANCE_S = 300
# How long a product that matched the catalogue is taken to still match.
PRODUCT_CHECK_S = 600

ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
PAYMENT_ID = re.compile(r"^pay_[A-Za-z0-9_-]{1,76}$")

PAYMENT_EVENTS = {"payment.succeeded", "payment.failed", "payment.processing",
                  "payment.cancelled"}
# Money going back, or in question: written on the order, never acted on.
AFTER_SALE_EVENTS = {"refund.succeeded", "dispute.opened", "dispute.challenged",
                     "dispute.accepted", "dispute.cancelled", "dispute.expired",
                     "dispute.won", "dispute.lost"}


class DodoError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def signing_key(secret: str) -> bytes | None:
    """The bytes a `whsec_…` secret signs with; None if it isn't one."""
    body = secret.strip().removeprefix("whsec_")
    if not body:
        return None
    try:
        return base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        return None


def signature(key: bytes, msg_id: str, timestamp: int, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


class Dodo:
    """The Dodo calls Holt makes, over HTTPS with a bearer key (no SDK).
    Tests replace `svc.dodo` with a fake that has the same methods."""

    name = "dodo"

    def __init__(self, api_key: str, env: str, webhook_secret: str,
                 products: dict[str, str], client: httpx.Client | None = None) -> None:
        self.env = env
        self._base = HOSTS[env]
        self._key = api_key
        self._hook_key = signing_key(webhook_secret)
        # Pass id -> the Dodo product that sells it.
        self.products = dict(products)
        # Product id -> (the price it matched, when): see payments.py.
        self.checked: dict[str, tuple[int, float]] = {}
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    @property
    def webhooks_on(self) -> bool:
        return self._hook_key is not None

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        try:
            res = self._client.request(method, f"{self._base}{path}", json=body,
                                       headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise DodoError(f"dodo {path}: {type(exc).__name__}") from exc
        if res.status_code >= 400:
            try:
                err = res.json()
                detail = f"{err.get('code', '')} {err.get('message', '')}".strip()
            except (ValueError, AttributeError):
                detail = ""
            raise DodoError(f"dodo {path}: HTTP {res.status_code} {detail}"[:300],
                            status=res.status_code)
        try:
            data = res.json()
        except ValueError as exc:
            raise DodoError(f"dodo {path}: not JSON") from exc
        if not isinstance(data, dict):
            raise DodoError(f"dodo {path}: not an object")
        return data

    def create_checkout(self, *, product_id: str, return_url: str, cancel_url: str,
                        metadata: dict[str, str]) -> dict:
        """A hosted checkout for one of `product_id`, in USD at the product's
        own price: no discount code, no other currency."""
        return self._call("POST", "/checkouts", {
            "product_cart": [{"product_id": product_id, "quantity": 1}],
            "billing_currency": CURRENCY,
            "return_url": return_url,
            "cancel_url": cancel_url,
            "metadata": metadata,
            "feature_flags": {"allow_discount_code": False,
                              "allow_currency_selection": False},
        })

    def fetch_checkout(self, session_id: str) -> dict:
        return self._call("GET", f"/checkouts/{_path_id(session_id)}")

    def fetch_payment(self, payment_id: str) -> dict:
        return self._call("GET", f"/payments/{_path_id(payment_id)}")

    def fetch_product(self, product_id: str) -> dict:
        return self._call("GET", f"/products/{_path_id(product_id)}")

    def webhook_ok(self, body: bytes, msg_id: str | None, timestamp: str | None,
                   given: str | None, at: float | None = None) -> bool:
        if self._hook_key is None or not (msg_id and timestamp and given):
            return False
        try:
            ts = int(timestamp.strip())
        except ValueError:
            return False
        if abs((time.time() if at is None else at) - ts) > TOLERANCE_S:
            return False
        expected = signature(self._hook_key, msg_id.strip(), ts, body).encode()
        for part in given.split():
            version, _, value = part.partition(",")
            if version == "v1" and hmac.compare_digest(expected, value.encode()):
                return True
        return False

    def close(self) -> None:
        self._client.close()


def _path_id(value: str) -> str:
    if not ID.match(value):
        raise DodoError("dodo: not an id")
    return value


def build(settings: Settings) -> Dodo | None:
    env = settings.dodo_env.strip().lower()
    if not settings.dodo_api_key or env not in HOSTS:
        return None
    return Dodo(settings.dodo_api_key, env, settings.dodo_webhook_secret,
                settings.dodo_products)


def product_problem(product: dict[str, Any], amount: int) -> str | None:
    """Why this Dodo product can't sell a pass priced at `amount` cents; None
    if it can: one payment, exactly that price in USD for every buyer."""
    price = product.get("price")
    if not isinstance(price, dict):
        return "it has no price"
    if product.get("is_recurring") or price.get("type") != "one_time_price":
        return "it is not a one-time product"
    if price.get("currency") != CURRENCY:
        return f"it is priced in {price.get('currency')}, not {CURRENCY}"
    if price.get("price") != amount:
        return f"its price is {price.get('price')}; the catalogue says {amount}"
    if price.get("pay_what_you_want"):
        return "it lets the buyer choose the price"
    if price.get("discount") or price.get("discount_bps"):
        return "it has a discount"
    if price.get("purchasing_power_parity") or product.get("pricing_mode"):
        return "its price changes with the buyer's country"
    return None


def mismatch(payment: dict[str, Any], *, product_id: str | None, amount: int,
             currency: str, order_id: str) -> str | None:
    """Why this payment doesn't pay the order; None if it does: one of the
    pass's product, in the order's currency, for its price. Dodo adds tax to
    a price that doesn't include it, so the price is the total or the total
    less tax."""
    cart = payment.get("product_cart")
    items = [(i.get("product_id"), i.get("quantity")) for i in cart
             if isinstance(i, dict)] if isinstance(cart, list) else []
    if not product_id or items != [(product_id, 1)]:
        return f"it bought {items}; the order is one of {product_id or 'a product not set up'}"
    total, tax = payment.get("total_amount"), payment.get("tax") or 0
    paid = str(payment.get("currency") or "").upper()
    if (type(total) is not int or type(tax) is not int or paid != currency
            or amount not in (total, total - tax)):
        return f"it was {total} {paid} (tax {tax}); the order is {amount} {currency}"
    meta = payment.get("metadata")
    named = meta.get("holt_order") if isinstance(meta, dict) else None
    if named is not None and named != order_id:
        return f"it names order {str(named)[:40]}"
    return None


def check(settings: Settings, dodo: Dodo | None = None) -> tuple[bool, list[str]]:
    """Whether USD could be sold on these settings, and a line per thing looked at."""
    from holt_server import pricing

    dodo = dodo or build(settings)
    if dodo is None:
        return False, ["DODO_API_KEY is not set" if not settings.dodo_api_key
                       else "DODO_ENV must be test or live"]
    lines = [f"Dodo {dodo.env} mode ({HOSTS[dodo.env]})"]
    ok = dodo.webhooks_on
    lines.append("DODO_WEBHOOK_SECRET: reads as a signing secret" if ok
                 else "DODO_WEBHOOK_SECRET: missing, or not a whsec_ secret")
    cat = pricing.cached(settings.pricing_file, settings.sell_every_pass)
    for pid, p in cat.passes.items():
        amount, product_id = p.price.usd_cents, dodo.products.get(pid)
        if not amount:
            continue
        sale = "on sale" if p.on_sale else "not on sale in the pricing file"
        if not product_id:
            lines.append(f"{pid} ({sale}): no DODO_PRODUCT_{pid.upper()}")
            ok = False
            continue
        try:
            why = product_problem(dodo.fetch_product(product_id), amount)
        except DodoError as exc:
            why = str(exc)
        lines.append(f"{pid} ({sale}): {product_id} "
                     + (f"can't sell it: {why}" if why else f"sells it for {amount} cents"))
        ok = ok and not why
    if not settings.payments_enabled:
        lines.append("HOLT_PAYMENTS_ENABLED is 0: nothing is sold yet")
    return ok, lines


def main() -> int:
    from holt_server.settings import get_settings

    ok, lines = check(get_settings())
    print("\n".join(lines))
    print("USD checkout: ready" if ok else "USD checkout: NOT ready")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
