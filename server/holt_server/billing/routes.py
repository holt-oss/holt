"""Billing endpoints: plans, checkout, verify, cancel, and the provider webhook.

Checkout creates the provider-side order or subscription and returns what the
browser's checkout widget needs. It grants nothing. Access changes only in
`/v1/billing/verify` (after the provider's payment signature checks out) and in
the webhook (after its HMAC checks out). Both go through `service.py`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from holt_server import quota
from holt_server.api import (
    Caller,
    caller,
    get_user,
    internal,
    me_body,
    services,
    signed_in,
)
from holt_server.billing import service
from holt_server.billing.provider import ProviderError
from holt_server.db import Payment, Subscription, WebhookEvent
from holt_server.errors import ApiError, upstream
from holt_server.plans import FREE

log = logging.getLogger("holt_server.billing")

router = APIRouter(prefix="/v1")
webhooks = APIRouter()

NOT_SET_UP = "Payments aren't available yet. BYOK (your own API key) is free and unlimited."


def provider(svc):
    if svc.payments is None:
        raise ApiError("not_implemented", NOT_SET_UP, status=501)
    return svc.payments


async def call(fn, *args, **kwargs):
    """A provider call, off the event loop, with its failure made plain."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except ProviderError as exc:
        log.warning("payment provider call failed: %s", exc)
        raise upstream("The payment provider") from exc


# --- plans ----------------------------------------------------------------------


@router.get("/plans", dependencies=[Depends(internal)])
async def plans(request: Request) -> dict[str, Any]:
    svc = services(request)
    return {**svc.catalog.public(),
            "provider": svc.payments.name if svc.payments else None}


# --- checkout -----------------------------------------------------------------------


class CheckoutIn(BaseModel):
    plan: str | None = Field(None, max_length=40)
    pack: str | None = Field(None, max_length=40)
    currency: str = Field("INR", min_length=3, max_length=3)

    @model_validator(mode="after")
    def one_thing(self):
        if bool(self.plan) == bool(self.pack):
            raise ValueError("give exactly one of plan or pack")
        self.currency = self.currency.upper()
        return self


@router.post("/billing/checkout")
async def checkout(body: CheckoutIn, request: Request,
                   who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    pay = provider(svc)
    user = await get_user(svc, user_id)
    base = {"provider": pay.name, "key_id": pay.public_key, "currency": body.currency}

    if body.pack:
        pack = svc.catalog.packs.get(body.pack)
        if pack is None:
            raise ApiError("invalid_request", "There's no such report pack.")
        price = pack.price(body.currency)
        if price is None:
            raise ApiError("invalid_request", f"{pack.name} isn't sold in {body.currency}.")
        order = await call(pay.create_order, amount=price.amount, currency=price.currency,
                           receipt=f"pack-{uuid.uuid4().hex[:16]}",
                           notes={"user_id": user_id, "pack": pack.id})
        async with svc.db.session() as s:
            s.add(Payment(user_id=user_id, provider=pay.name, kind="pack", item=pack.id,
                          provider_order_id=order.id, amount=price.amount,
                          currency=price.currency, status="created"))
            await s.commit()
        return {**base, "kind": "order", "order_id": order.id, "amount": price.amount,
                "name": "Holt", "description": pack.name}

    plan = svc.catalog.plans.get(body.plan or "")
    if plan is None or plan.id == FREE:
        raise ApiError("invalid_request", "There's no such paid plan.")
    price = plan.price(body.currency)
    if price is None:
        raise ApiError("invalid_request", f"{plan.name} isn't sold in {body.currency}.")
    if not price.razorpay_plan_id:
        raise ApiError("not_implemented", f"The {plan.name} plan can't be bought yet.",
                       status=501)
    current = quota.effective_plan(user, svc.catalog, svc.grace)
    live = await _live_subscription(svc, user_id)
    if live is not None and live.status in ("active", "pending"):
        raise ApiError("already_subscribed",
                       f"You're already on the {current.name} plan. Cancel it first "
                       "to switch; you keep it until the end of the month you paid for.")
    if live is not None:
        # An unfinished checkout (created, or mandate set but not yet charged).
        if live.plan == plan.id and live.currency == price.currency:
            # Same thing again: hand back the same subscription, never a second one.
            return {**base, "kind": "subscription",
                    "subscription_id": live.provider_subscription_id,
                    "amount": live.amount, "name": "Holt",
                    "description": f"{plan.name} plan", "short_url": None}
        # They changed their mind: cancel the old one at once so it can never charge.
        await call(pay.cancel_subscription, live.provider_subscription_id,
                   at_period_end=False)
        async with svc.db.session() as s:
            row = await s.get(Subscription, live.id)
            row.status, row.cancel_at_period_end = "cancelled", True
            await s.commit()
    sub = await call(pay.create_subscription, provider_plan_id=price.razorpay_plan_id,
                     total_count=svc.settings.subscription_cycles,
                     notes={"user_id": user_id, "plan": plan.id})
    async with svc.db.session() as s:
        s.add(Subscription(user_id=user_id, provider=pay.name,
                           provider_subscription_id=sub.id, plan=plan.id,
                           currency=price.currency, amount=price.amount,
                           status="created"))
        try:
            await s.commit()
        except IntegrityError:
            # Another checkout for this user won the race (one live subscription
            # per user). Make sure the one we just created can never charge.
            await s.rollback()
            try:
                await call(pay.cancel_subscription, sub.id, at_period_end=False)
            except ApiError:
                log.error("could not cancel duplicate subscription %s", sub.id)
            raise ApiError("already_subscribed", "A checkout for a plan is already "
                           "open. Finish it, or try again in a minute.") from None
    return {**base, "kind": "subscription", "subscription_id": sub.id,
            "amount": price.amount, "name": "Holt", "description": f"{plan.name} plan",
            "short_url": sub.short_url}


async def _live_subscription(svc, user_id: str) -> Subscription | None:
    """The user's one live, renewing subscription (see db.LIVE_SUBSCRIPTION)."""
    async with svc.db.session() as s:
        return (await s.execute(
            select(Subscription).where(Subscription.user_id == user_id,
                                       Subscription.status.in_(service.LIVE),
                                       Subscription.cancel_at_period_end.is_(False))
            .order_by(Subscription.created_at.desc()).limit(1)
        )).scalar_one_or_none()


# --- verify ---------------------------------------------------------------------------


class VerifyIn(BaseModel):
    """What Razorpay Checkout hands the page on success, passed on unchanged."""

    razorpay_payment_id: str = Field(max_length=100)
    razorpay_signature: str = Field(max_length=200)
    razorpay_order_id: str | None = Field(None, max_length=100)
    razorpay_subscription_id: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def one_thing(self):
        if bool(self.razorpay_order_id) == bool(self.razorpay_subscription_id):
            raise ValueError("give exactly one of razorpay_order_id or "
                             "razorpay_subscription_id")
        return self


BAD_SIGNATURE = ("We couldn't confirm that payment. If money left your account, it "
                 "will show up here within a few minutes, or be refunded.")


@router.post("/billing/verify")
async def verify(body: VerifyIn, request: Request,
                 who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    pay = provider(svc)

    if body.razorpay_order_id:
        if not pay.verify_order_payment(order_id=body.razorpay_order_id,
                                        payment_id=body.razorpay_payment_id,
                                        signature=body.razorpay_signature):
            raise ApiError("invalid_signature", BAD_SIGNATURE)
        async with svc.db.session() as s:
            payment = (await s.execute(select(Payment).where(
                Payment.provider_order_id == body.razorpay_order_id,
                Payment.user_id == user_id))).scalar_one_or_none()
            if payment is None:
                raise ApiError("not_found", "We couldn't find that order.")
            try:
                await service.credit_pack(s, svc.catalog, payment, body.razorpay_payment_id)
                await s.commit()
            except IntegrityError as exc:  # payment id already used on another order
                await s.rollback()
                raise ApiError("invalid_signature", BAD_SIGNATURE) from exc
        status = "paid"
    else:
        sub_id = body.razorpay_subscription_id
        if not pay.verify_subscription_payment(subscription_id=sub_id,
                                               payment_id=body.razorpay_payment_id,
                                               signature=body.razorpay_signature):
            raise ApiError("invalid_signature", BAD_SIGNATURE)
        async with svc.db.session() as s:
            owned = (await s.execute(select(Subscription.id).where(
                Subscription.provider_subscription_id == sub_id,
                Subscription.user_id == user_id))).scalar_one_or_none()
        if owned is None:
            raise ApiError("not_found", "We couldn't find that subscription.")
        # The signature proves a payment was made for this subscription; the
        # period it pays for comes from the provider, not from the browser.
        info = await call(pay.fetch_subscription, sub_id)
        async with svc.db.session() as s:
            if info.status == "active":
                sub = await service.apply_subscription(s, "subscription.activated", info)
            else:
                sub = await service.apply_subscription(s, f"subscription.{info.status}",
                                                       info)
            await s.commit()
        status = sub.status if sub else "pending"
    user = await get_user(svc, user_id)
    return {"status": status, "me": await me_body(svc, user)}


# --- cancel ---------------------------------------------------------------------------


@router.post("/billing/cancel")
async def cancel(request: Request, who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    pay = provider(svc)
    sub = await _live_subscription(svc, user_id)
    if sub is None:
        raise ApiError("not_found", "You don't have a subscription to cancel.")
    # Paid: at period end, so they keep what they paid for; the provider's
    # `subscription.cancelled` webhook finalises it. Not yet paid: at once.
    paid = sub.status in ("active", "pending")
    await call(pay.cancel_subscription, sub.provider_subscription_id, at_period_end=paid)
    async with svc.db.session() as s:
        row = await s.get(Subscription, sub.id)
        row.cancel_at_period_end = True
        if not paid:
            row.status = "cancelled"
        await s.commit()
    return await me_body(svc, await get_user(svc, user_id))


# --- webhook -----------------------------------------------------------------------------


# Razorpay webhook bodies are a few KB. Anything near this is not one.
MAX_WEBHOOK_BYTES = 1024 * 1024


async def bounded_body(request: Request, limit: int = MAX_WEBHOOK_BYTES) -> bytes:
    """The request body, refusing to read more than `limit` bytes, declared or
    streamed (chunked bodies have no Content-Length to check up front)."""
    too_big = ApiError("invalid_request", "Request body too large.", status=413)
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise too_big
        except ValueError:
            raise ApiError("invalid_request", "Bad Content-Length.") from None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    return b"".join(chunks)


@webhooks.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> dict[str, Any]:
    svc = services(request)
    pay = svc.payments
    if pay is None or pay.name != "razorpay":
        raise ApiError("not_found", "There is nothing at this address.")
    body = await bounded_body(request)
    if not x_razorpay_signature or not pay.verify_webhook(body, x_razorpay_signature):
        raise ApiError("invalid_signature", "Bad webhook signature.")
    try:
        # Deduplicated on the signed body; the event-id header is only logged.
        event = pay.parse_webhook(body)
    except (ValueError, KeyError, TypeError) as exc:
        raise ApiError("invalid_request", "Malformed webhook body.") from exc

    async with svc.db.session() as s:
        s.add(WebhookEvent(provider=pay.name, event_id=event.id, type=event.type))
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            return {"ok": True, "duplicate": True}
        try:
            result = await service.apply_event(s, svc.catalog, event)
            await s.commit()
        except IntegrityError:
            # e.g. a payment id already used on another order. It will never
            # apply, so record it and say 200 rather than have it retried forever.
            await s.rollback()
            log.error("webhook %s %s conflicts with stored payments", event.id, event.type)
            s.add(WebhookEvent(provider=pay.name, event_id=event.id, type=event.type))
            await s.commit()
            result = "conflict"
    log.info("webhook %s (header id %s) %s -> %s", event.id, x_razorpay_event_id,
             event.type, result)
    return {"ok": True, "result": result}
