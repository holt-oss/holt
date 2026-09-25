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

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from holt_server.billing.provider import (
    DisputeInfo,
    Event,
    PaymentInfo,
    SubscriptionInfo,
)
from holt_server.db import Payment, Refund, Subscription, User, now, utc
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


# Events that describe a subscription still in progress. One of these carrying
# an older billing period than we already hold is stale (delivered late) and
# is ignored; it must not rewind the period or revive a halted subscription.
ONGOING = {"authenticated", "activated", "charged", "resumed", "pending", "halted", "paused"}
REVIVING = {"activated", "charged", "resumed", "pending"}


def _stale(sub: Subscription, kind: str, info: SubscriptionInfo) -> bool:
    if kind not in ONGOING or sub.current_end is None or info.current_end is None:
        return False
    new, old = utc(info.current_end), utc(sub.current_end)
    if new < old:
        return True
    # Same period, but it was halted/paused since: only a new period revives it.
    return new == old and sub.status in ("halted", "paused") and kind in REVIVING


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
    if _stale(sub, kind, info):
        log.info("stale %s for %s ignored", event_type, info.id)
        return sub

    if kind in ("activated", "charged", "resumed"):
        if sub.status in FINAL:
            # Over; a late or trailing charge event grants nothing.
            pass
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


def _grants(user: User, sub: Subscription) -> bool:
    """Is `sub` the subscription behind the user's current plan?"""
    if user.plan_subscription_id is not None:
        return user.plan_subscription_id == sub.provider_subscription_id
    # Granted before the granting id was recorded.
    return user.plan == sub.plan and user.plan_until is not None


def _grant(user: User, sub: Subscription) -> None:
    if sub.current_end is None:
        return
    if user.plan != FREE and user.plan_until is None and user.plan_subscription_id is None:
        return  # a manual grant is left alone
    if user.plan != FREE and not _grants(user, sub) and user.plan_until is not None:
        # Another subscription gave the plan. An older one's late events, or one
        # the user has cancelled, must not take it over or overwrite its dates.
        if sub.cancel_at_period_end or utc(sub.current_end) <= utc(user.plan_until):
            return
    user.plan = sub.plan
    user.plan_until = sub.current_end
    user.cycle_start = sub.current_start
    user.plan_subscription_id = sub.provider_subscription_id


def _revoke(user: User, sub: Subscription) -> None:
    # Only the plan this subscription gave. Another (newer) subscription or a
    # manual grant is not this event's business.
    if user.plan != FREE and _grants(user, sub):
        user.plan, user.plan_until, user.cycle_start = FREE, None, None
        user.plan_subscription_id = None


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
    if event.type == "refund.processed" and event.refund:
        r = event.refund
        return await apply_refund(s, catalog, r.id, r.payment_id, r.amount, r.currency)
    if event.type.startswith("dispute.") and event.dispute:
        return await apply_dispute(s, catalog, event.type.removeprefix("dispute."),
                                   event.dispute)
    if event.type.startswith("subscription.") and event.subscription:
        sub = await apply_subscription(s, event.type, event.subscription, event.payment)
        return sub.status if sub else "ignored"
    return "ignored"


# --- refunds and disputes -------------------------------------------------------


async def _payment_by_provider_id(s: AsyncSession, provider_payment_id: str) -> Payment | None:
    return (await s.execute(select(Payment).where(
        Payment.provider_payment_id == provider_payment_id))).scalar_one_or_none()


async def apply_refund(s: AsyncSession, catalog: Catalog, refund_id: str,
                       provider_payment_id: str, amount: int, currency: str) -> str:
    """Money went back to the payer. Take back what it bought, once per refund.

    Packs lose the refunded share of their reports (rounded up, since refunded
    money buys nothing), never going below zero; reports already used stay
    used. A fully refunded subscription payment ends the plan it granted.
    """
    payment = await _payment_by_provider_id(s, provider_payment_id)
    if payment is None:
        log.warning("refund %s for unknown payment %s", refund_id, provider_payment_id)
        return "ignored"
    done = (await s.execute(select(Refund.id).where(
        Refund.provider_refund_id == refund_id))).scalar_one_or_none()
    if done is not None:
        return "already"
    s.add(Refund(provider=payment.provider, provider_refund_id=refund_id,
                 payment_id=payment.id, amount=amount, currency=currency.upper()))
    payment.refunded_amount = min(payment.amount, (payment.refunded_amount or 0) + amount)
    full = payment.refunded_amount >= payment.amount
    payment.status = "refunded" if full else "partially_refunded"
    payment.updated_at = now()

    if payment.kind == "pack" and payment.credited:
        pack = catalog.packs.get(payment.item)
        reports = pack.reports if pack else 0
        take = min(reports, -(-reports * amount // payment.amount)) if payment.amount else 0
        if take:
            await s.execute(update(User).where(User.id == payment.user_id).values(
                pack_credits=case((User.pack_credits > take, User.pack_credits - take),
                                  else_=0)))
    elif payment.kind == "subscription" and full and payment.provider_subscription_id:
        sub = (await s.execute(select(Subscription).where(
            Subscription.provider_subscription_id == payment.provider_subscription_id
        ))).scalar_one_or_none()
        if sub is not None:
            _revoke(await _user(s, sub.user_id), sub)
    log.warning("refund %s: %s %s on payment %s (%s)", refund_id, amount, currency,
                provider_payment_id, payment.status)
    return "refunded"


async def apply_dispute(s: AsyncSession, catalog: Catalog, phase: str,
                        dispute: DisputeInfo) -> str:
    """A chargeback. While open, the payment is flagged and pack credits are
    frozen (kept, not spendable); lost is treated as a refund."""
    payment = await _payment_by_provider_id(s, dispute.payment_id)
    if payment is None:
        log.error("DISPUTE %s %s on unknown payment %s", phase, dispute.id, dispute.payment_id)
        return "ignored"
    log.error("DISPUTE %s: %s on payment %s (%s %s, user %s)", phase, dispute.id,
              dispute.payment_id, dispute.amount, dispute.currency, payment.user_id)
    if phase == "created":
        payment.disputed = True
        if payment.kind == "pack":
            await s.execute(update(User).where(User.id == payment.user_id)
                            .values(packs_frozen=True))
        return "disputed"
    payment.disputed = False
    await s.flush()
    if phase == "lost":
        await apply_refund(s, catalog, f"dispute:{dispute.id}", dispute.payment_id,
                           dispute.amount, dispute.currency)
    if payment.kind == "pack":
        others = (await s.execute(select(Payment.id).where(
            Payment.user_id == payment.user_id, Payment.kind == "pack",
            Payment.disputed.is_(True)))).first()
        if others is None:
            await s.execute(update(User).where(User.id == payment.user_id)
                            .values(packs_frozen=False))
    return f"dispute_{phase}"
