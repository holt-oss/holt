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


def _share(reports: int, refunded: int, amount: int) -> int:
    """Reports covered by `refunded` of `amount`, rounded up: refunded money buys nothing."""
    if refunded <= 0 or amount <= 0:
        return 0
    return min(reports, -(-reports * refunded // amount))


async def credit_pack(s: AsyncSession, catalog: Catalog, payment: Payment,
                      provider_payment_id: str | None,
                      paid: PaymentInfo | None = None) -> bool:
    """Mark a pack order paid and add its credits, once. Returns True if this
    call did the crediting.

    A refund can arrive before this (Razorpay sends events in any order); what
    was already refunded is subtracted, and a fully refunded pack credits nothing.
    """
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
    if payment.credited:
        return False
    if provider_payment_id:
        await _adopt_early_refunds(s, payment, provider_payment_id)
    refunded = payment.refunded_amount or 0
    taken = _share(pack.reports, refunded, payment.amount)
    grant = pack.reports - taken
    values = {"credited": True, "credits_left": grant, "credits_taken": taken,
              "updated_at": now(),
              "status": "paid" if not refunded else payment.status}
    if provider_payment_id and not payment.provider_payment_id:
        values["provider_payment_id"] = provider_payment_id
    done = await s.execute(update(Payment).where(
        Payment.id == payment.id, Payment.credited.is_(False)).values(**values))
    if done.rowcount != 1:
        return False
    if grant:
        await s.execute(update(User).where(User.id == payment.user_id)
                        .values(pack_credits=User.pack_credits + grant))
    return True


async def _adopt_early_refunds(s: AsyncSession, payment: Payment, provider_payment_id: str,
                               ) -> None:
    """A refund recorded against this payment id before we knew its order."""
    early = (await s.execute(select(Payment).where(
        Payment.provider_payment_id == provider_payment_id,
        Payment.kind == "unmatched"))).scalar_one_or_none()
    if early is None:
        return
    payment.refunded_amount = min(payment.amount,
                                  (payment.refunded_amount or 0) + (early.refunded_amount or 0))
    if payment.refunded_amount:
        payment.status = ("refunded" if payment.refunded_amount >= payment.amount
                          else "partially_refunded")
    await s.execute(update(Refund).where(Refund.payment_id == early.id)
                    .values(payment_id=payment.id))
    await s.delete(early)
    await s.flush()


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
REVIVING = {"activated", "charged", "pending"}


def _stale(sub: Subscription, kind: str, info: SubscriptionInfo) -> bool:
    if kind not in ONGOING or sub.current_end is None or info.current_end is None:
        return False
    new, old = utc(info.current_end), utc(sub.current_end)
    if new < old:
        return True
    # Same period, but it was halted/paused since: only a new period revives
    # it, except `resumed`, which is exactly how a paused subscription restarts.
    if kind == "resumed" and sub.status == "paused":
        return False
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
        r, p = event.refund, event.payment
        return await apply_refund(s, catalog, r.id, r.payment_id, r.amount, r.currency,
                                  order_id=p.order_id if p else None,
                                  payment_amount=p.amount if p else None)
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


async def _payment_for_refund(s: AsyncSession, provider_payment_id: str,
                               order_id: str | None, amount_hint: int,
                               currency: str) -> Payment:
    """The payment a refund is about, found by payment id, else by order id,
    else recorded on its own until the order turns up (see credit_pack)."""
    payment = await _payment_by_provider_id(s, provider_payment_id)
    if payment is None and order_id:
        payment = (await s.execute(select(Payment).where(
            Payment.provider_order_id == order_id))).scalar_one_or_none()
        if payment is not None and not payment.provider_payment_id:
            payment.provider_payment_id = provider_payment_id
    if payment is None:
        payment = Payment(user_id="", provider="razorpay", kind="unmatched", item="",
                          provider_payment_id=provider_payment_id, amount=amount_hint,
                          currency=currency.upper(), status="created")
        s.add(payment)
    await s.flush()
    return payment


async def apply_refund(s: AsyncSession, catalog: Catalog, refund_id: str,
                       provider_payment_id: str, amount: int, currency: str,
                       order_id: str | None = None, payment_amount: int | None = None,
                       ) -> str:
    """Money went back to the payer. Take back what it bought, once per refund.

    Packs: the cumulative refunded share of the pack's reports, rounded up
    (refunded money buys nothing), taken only from that pack's unspent
    credits, so reports already used stay used and other packs are never
    touched. A fully refunded subscription payment ends the plan it granted.
    A refund that arrives before the pack is credited is kept against the
    payment and subtracted when crediting happens.
    """
    done = (await s.execute(select(Refund.id).where(
        Refund.provider_refund_id == refund_id))).scalar_one_or_none()
    if done is not None:
        return "already"
    payment = await _payment_for_refund(s, provider_payment_id, order_id,
                                        payment_amount or amount, currency)
    s.add(Refund(provider=payment.provider, provider_refund_id=refund_id,
                 payment_id=payment.id, amount=amount, currency=currency.upper()))
    total = (payment.refunded_amount or 0) + amount
    payment.refunded_amount = min(payment.amount, total) if payment.amount else total
    full = bool(payment.amount) and payment.refunded_amount >= payment.amount
    payment.status = "refunded" if full else "partially_refunded"
    payment.updated_at = now()

    if payment.kind == "pack" and payment.credited:
        pack = catalog.packs.get(payment.item)
        target = _share(pack.reports if pack else 0, payment.refunded_amount, payment.amount)
        take = min(max(0, target - (payment.credits_taken or 0)), payment.credits_left or 0)
        payment.credits_taken = max(payment.credits_taken or 0, target)
        if take:
            payment.credits_left -= take
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
    return "refunded" if payment.kind != "unmatched" else "recorded"


# Dispute phases (Razorpay: payment.dispute.<phase>). Only a settled dispute
# unfreezes; anything still open keeps pack credits frozen.
DISPUTE_OPEN = {"created", "under_review", "action_required"}
DISPUTE_SETTLED = {"won", "lost", "closed"}


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
    if phase in DISPUTE_OPEN:
        payment.disputed = True
        if payment.kind == "pack":
            await s.execute(update(User).where(User.id == payment.user_id)
                            .values(packs_frozen=True))
        return "disputed"
    if phase not in DISPUTE_SETTLED:
        return "ignored"
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
