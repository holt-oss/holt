"""Razorpay: Orders API for packs, Subscriptions API for plans. UPI, cards and
netbanking all go through the same Checkout on the client.

Plain HTTPS with basic auth, no SDK. Signatures, per Razorpay's docs:

* order payment:        HMAC-SHA256(order_id + "|" + payment_id, key_secret)
* subscription payment: HMAC-SHA256(payment_id + "|" + subscription_id, key_secret)
* webhook:              HMAC-SHA256(raw request body, webhook_secret),
                        in the X-Razorpay-Signature header

All compared in constant time. Amounts are in the currency's minor unit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from holt_server.billing.provider import (
    DisputeInfo,
    Event,
    Order,
    PaymentInfo,
    ProviderError,
    RefundInfo,
    SubscriptionInfo,
)

API = "https://api.razorpay.com/v1"
TIMEOUT_S = 20.0

SUBSCRIPTION_EVENTS = {
    "subscription.authenticated", "subscription.activated", "subscription.charged",
    "subscription.pending", "subscription.halted", "subscription.cancelled",
    "subscription.completed", "subscription.expired", "subscription.paused",
    "subscription.resumed",
}


def _hmac(secret: str, message: str | bytes) -> str:
    data = message.encode("utf-8") if isinstance(message, str) else message
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()


def _same(expected: str, given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(expected, given.strip())


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


def _subscription(entity: dict[str, Any]) -> SubscriptionInfo:
    return SubscriptionInfo(
        id=entity["id"], status=entity.get("status", ""),
        current_start=_ts(entity.get("current_start")),
        current_end=_ts(entity.get("current_end")),
        short_url=entity.get("short_url"),
    )


def _payment(entity: dict[str, Any]) -> PaymentInfo:
    return PaymentInfo(
        id=entity["id"], amount=int(entity.get("amount") or 0),
        currency=entity.get("currency", ""), status=entity.get("status", ""),
        order_id=entity.get("order_id"), subscription_id=entity.get("subscription_id"),
    )


class Razorpay:
    name = "razorpay"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str,
                 client: httpx.Client | None = None) -> None:
        self.public_key = key_id
        self._secret = key_secret
        self._webhook_secret = webhook_secret
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    # --- API calls ---------------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        try:
            response = self._client.request(method, f"{API}{path}", json=body,
                                            auth=(self.public_key, self._secret))
        except httpx.HTTPError as exc:
            raise ProviderError(f"razorpay {path}: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("description", "")
            except ValueError:
                detail = ""
            raise ProviderError(f"razorpay {path}: HTTP {response.status_code} {detail}")
        return response.json()

    def create_order(self, *, amount: int, currency: str, receipt: str,
                     notes: dict[str, str]) -> Order:
        data = self._call("POST", "/orders", {"amount": amount, "currency": currency,
                                               "receipt": receipt[:40], "notes": notes})
        return Order(id=data["id"], amount=int(data["amount"]), currency=data["currency"])

    def create_subscription(self, *, provider_plan_id: str, total_count: int,
                            notes: dict[str, str]) -> SubscriptionInfo:
        return _subscription(self._call("POST", "/subscriptions", {
            "plan_id": provider_plan_id, "total_count": total_count,
            "customer_notify": 1, "notes": notes}))

    def fetch_subscription(self, subscription_id: str) -> SubscriptionInfo:
        return _subscription(self._call("GET", f"/subscriptions/{subscription_id}"))

    def cancel_subscription(self, subscription_id: str, *,
                            at_period_end: bool = True) -> SubscriptionInfo:
        return _subscription(self._call(
            "POST", f"/subscriptions/{subscription_id}/cancel",
            {"cancel_at_cycle_end": 1 if at_period_end else 0}))

    # --- signatures ----------------------------------------------------------

    def verify_order_payment(self, *, order_id: str, payment_id: str,
                             signature: str) -> bool:
        return _same(_hmac(self._secret, f"{order_id}|{payment_id}"), signature)

    def verify_subscription_payment(self, *, subscription_id: str, payment_id: str,
                                    signature: str) -> bool:
        return _same(_hmac(self._secret, f"{payment_id}|{subscription_id}"), signature)

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False
        return _same(_hmac(self._webhook_secret, body), signature)

    # --- webhooks -------------------------------------------------------------

    def parse_webhook(self, body: bytes) -> Event:
        data = json.loads(body)
        kind = data.get("event", "")
        payload = data.get("payload") or {}

        def entity(name: str) -> dict[str, Any] | None:
            return (payload.get(name) or {}).get("entity")

        payment = _payment(e) if (e := entity("payment")) else None
        subscription = _subscription(e) if (e := entity("subscription")) else None
        refund = dispute = None
        if e := entity("refund"):
            refund = RefundInfo(id=e["id"], payment_id=e["payment_id"],
                                amount=int(e.get("amount") or 0),
                                currency=(e.get("currency") or "").upper())
        if e := entity("dispute"):
            dispute = DisputeInfo(id=e["id"], payment_id=e["payment_id"],
                                  amount=int(e.get("amount") or 0),
                                  currency=(e.get("currency") or "").upper())
        # Idempotency key: the signed body itself. Razorpay's X-Razorpay-Event-Id
        # header is not covered by the signature, so anyone replaying a captured
        # delivery could change it; a retry of the same event has the same body.
        eid = "sha256:" + hashlib.sha256(body).hexdigest()

        if kind in ("payment.captured", "order.paid"):
            etype = "payment.paid"
        elif kind == "payment.failed":
            etype = "payment.failed"
        elif kind in SUBSCRIPTION_EVENTS:
            etype = kind
        elif kind == "refund.processed" and refund:
            etype = "refund.processed"
        elif kind.startswith("payment.dispute.") and dispute:
            etype = "dispute." + kind.removeprefix("payment.dispute.")
        else:
            etype = "ignored"
        return Event(id=eid, type=etype, payment=payment, subscription=subscription,
                     refund=refund, dispute=dispute, raw=data)
