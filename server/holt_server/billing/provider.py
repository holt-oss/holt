"""The payment-provider seam.

A provider does four things: take money once (an order, for packs), take money
monthly (a subscription, for plans), prove that a payment the browser reports
really happened (a signature), and tell us about changes later (webhooks,
likewise signed). Everything else -- what a payment buys, when access starts
and stops -- is ours, in `service.py`, and is the same for every provider.

Webhooks are normalised into `Event`s here so `service.py` never parses a
provider's JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """The provider refused or failed a call. The message is for logs."""


@dataclass(frozen=True)
class Order:
    id: str
    amount: int
    currency: str


@dataclass(frozen=True)
class SubscriptionInfo:
    id: str
    status: str
    current_start: datetime | None = None
    current_end: datetime | None = None
    short_url: str | None = None


@dataclass(frozen=True)
class PaymentInfo:
    id: str
    amount: int
    currency: str
    status: str  # captured | authorized | failed | ...
    order_id: str | None = None
    subscription_id: str | None = None


@dataclass(frozen=True)
class Event:
    """One webhook delivery, provider-neutral.

    `type` uses our vocabulary:
      payment.paid, payment.failed,
      subscription.authenticated | activated | charged | pending | halted |
      cancelled | completed | expired | paused | resumed,
      or "ignored" for anything we do not act on.
    """

    id: str
    type: str
    payment: PaymentInfo | None = None
    subscription: SubscriptionInfo | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class PaymentProvider(Protocol):
    name: str
    #: The public key the browser's checkout widget needs. Never the secret.
    public_key: str

    def create_order(self, *, amount: int, currency: str, receipt: str,
                     notes: dict[str, str]) -> Order: ...

    def create_subscription(self, *, provider_plan_id: str, total_count: int,
                            notes: dict[str, str]) -> SubscriptionInfo: ...

    def fetch_subscription(self, subscription_id: str) -> SubscriptionInfo: ...

    def cancel_subscription(self, subscription_id: str, *,
                            at_period_end: bool = True) -> SubscriptionInfo: ...

    def verify_order_payment(self, *, order_id: str, payment_id: str,
                             signature: str) -> bool: ...

    def verify_subscription_payment(self, *, subscription_id: str, payment_id: str,
                                    signature: str) -> bool: ...

    def verify_webhook(self, body: bytes, signature: str) -> bool: ...

    def parse_webhook(self, body: bytes, event_id: str | None) -> Event: ...
