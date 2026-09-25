"""What a verified payment event does to a user's entitlements.

The only callers are the signature-checked `/v1/billing/verify` and the
HMAC-checked webhook, so nothing a browser merely claims changes what anyone
has. Every function takes an open session and does not commit: the caller
commits once, so an event's effects and its idempotency record land together
or not at all.

Idempotency, layer by layer:
* webhook deliveries are recorded by event id (`WebhookEvent`), so a retried
  or replayed delivery is a no-op;
* a pack is credited under `UPDATE payments SET credited = true WHERE ...
  credited = false`, so the verify call and the webhook for the same payment
  (which both arrive, in either order) credit it once between them;
* subscription events set state (status, period end) rather than add to it,
  so applying one twice changes nothing.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from holt_server.billing.provider import Event, PaymentInfo, SubscriptionInfo
from holt_server.db import Payment, Subscription, User, now, utc
from holt_server.plans import FREE, Catalog

log = logging.getLogger("holt_server.billing")

# A subscription in one of these never grants access again; a late or
# out-of-order "activated" must not revive it.
FINAL = {"cancelled", "completed", "expired"}
# Statuses in which the user is (or is about to be) paying.
LIVE = {"created", "authenticated", "active", "pending"}


async def credit_pack(s: AsyncSession, catalog: Catalog, payment: Payment,
                      provider_payment_id: str | None,
                      paid: PaymentInfo | None = None) -> bool:
    """Mark a pack order paid and add its credits, once. Returns True if this
    call did the crediting."""
    pack = catalog.packs.get(payment.item)
    if pack is None:
        log.error("payment %s is for unknown pack %r", payment.id, payment.item)
        return False
    if paid is not None and (paid.amount != payment.amount
                             or paid.currency.upper() != payment.currency):
        # The order fixes the amount, so this should not happen. If it does,
        # a person looks at it; nobody is credited for a different sum.
        log.error("payment %s amount mismatch: %s %s vs order %s %s", payment.id,
                  paid.amount, paid.currency, payment.amount, payment.currency)
        return False
    values = {"status": "paid", "credited": True, "updated_at": now()}
    if provider_payment_id and not payment.provider_payment_id:
        values["provider_payment_id"] = provider_payment_id
    done = await s.execute(update(Payment).where(
        Payment.id == payment.id, Payment.credited.is_(False)).values(**values))
    if done.rowcount != 1:
        return False
    await s.execute(update(User).where(User.id == payment.user_id)
                    .values(pack_credits=User.pack_credits + pack.reports))
    return True


async def fail_payment(s: AsyncSession, payment: Payment) -> None:
    await s.execute(update(Payment).where(Payment.id == payment.id,
                                          Payment.status == "created")
                    .values(status="failed", updated_at=now()))


async def _user(s: AsyncSession, user_id: str) -> User:
    user = await s.get(User, user_id)
    if user is None:
        user = User(id=user_id, plan=FREE, ai_used=0, ai_period="")
        s.add(user)
        await s.flush()
    return user


def _later(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(utc(a), utc(b))


async def apply_subscription(s: AsyncSession, event_type: str, info: SubscriptionInfo,
                             payment: PaymentInfo | None = None) -> Subscription | None:
    """Apply one subscription state change. Safe to repeat and to reorder."""
    sub = (await s.execute(select(Subscription).where(
        Subscription.provider_subscription_id == info.id))).scalar_one_or_none()
    if sub is None:
        log.warning("event %s for unknown subscription %s", event_type, info.id)
        return None
    kind = event_type.removeprefix("subscription.")
    user = await _user(s, sub.user_id)

    if payment is not None and kind == "charged":
        await _record_subscription_payment(s, sub, payment)

    if kind in ("activated", "charged", "resumed"):
        if sub.status in FINAL:
            # A cancelled subscription can still bill its last paid cycle; keep
            # the period end current, but it does not become active again.
            sub.current_end = _later(sub.current_end, info.current_end)
        else:
            sub.status = "active"
            sub.current_start = _later(sub.current_start, info.current_start)
            sub.current_end = _later(sub.current_end, info.current_end)
        _grant(user, sub)
    elif kind == "authenticated":
        # Mandate set up; nothing is paid yet, so nothing is granted.
        if sub.status == "created":
            sub.status = "authenticated"
    elif kind == "pending":
        # A renewal charge failed and Razorpay is retrying. Access continues
        # through the grace period; nothing changes here.
        if sub.status not in FINAL:
            sub.status = "pending"
    elif kind in ("halted", "paused"):
        if sub.status not in FINAL:
            sub.status = kind
        _revoke(user, sub)
    elif kind == "cancelled":
        sub.status = "cancelled"
        sub.cancel_at_period_end = True
        sub.current_end = _later(sub.current_end, info.current_end)
        # Access continues to the end of the cycle already paid for.
        if sub.current_end is None or utc(sub.current_end) <= now():
            _revoke(user, sub)
    elif kind in ("completed", "expired"):
        sub.status = kind
        _revoke(user, sub)
    sub.updated_at = now()
    return sub


def _grant(user: User, sub: Subscription) -> None:
    if sub.current_end is None:
        return
    if user.plan not in (FREE, sub.plan) and user.plan_until is None:
        return  # a manual grant is left alone
    user.plan = sub.plan
    user.plan_until = sub.current_end
    user.cycle_start = sub.current_start


def _revoke(user: User, sub: Subscription) -> None:
    # Only the plan this subscription gave. Another subscription or a manual
    # grant is not this event's business.
    if user.plan == sub.plan and user.plan_until is not None:
        user.plan, user.plan_until, user.cycle_start = FREE, None, None


async def _record_subscription_payment(s: AsyncSession, sub: Subscription,
                                       payment: PaymentInfo) -> None:
    exists = (await s.execute(select(Payment.id).where(
        Payment.provider_payment_id == payment.id))).scalar_one_or_none()
    if exists is None:
        s.add(Payment(user_id=sub.user_id, provider=sub.provider, kind="subscription",
                      item=sub.plan, provider_payment_id=payment.id,
                      provider_subscription_id=sub.provider_subscription_id,
                      amount=payment.amount, currency=payment.currency.upper(),
                      status="paid", credited=True))


async def apply_event(s: AsyncSession, catalog: Catalog, event: Event) -> str:
    """One verified webhook event. Returns what it did, for logs and tests."""
    if event.type in ("payment.paid", "payment.failed") and event.payment:
        info = event.payment
        if not info.order_id:
            return "ignored"
        payment = (await s.execute(select(Payment).where(
            Payment.provider_order_id == info.order_id))).scalar_one_or_none()
        if payment is None or payment.kind != "pack":
            return "ignored"  # not one of our pack orders (subscriptions bill via invoices)
        if event.type == "payment.failed":
            await fail_payment(s, payment)
            return "failed"
        return "credited" if await credit_pack(s, catalog, payment, info.id, info) \
            else "already"
    if event.type.startswith("subscription.") and event.subscription:
        sub = await apply_subscription(s, event.type, event.subscription, event.payment)
        return sub.status if sub else "ignored"
    return "ignored"
