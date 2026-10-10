"""Account emails: who gets which, once each (API.md, "Account emails").

Five emails, and no more:

- `welcome`: once per account, at its first sign-in;
- `receipt`: for each paid pass. It always goes out;
- `trial_ending`: `TRIAL_WARN` before the free days of PR alerts end, and
  `trial_ended`: once when they have, for someone whose alerts were on;
- `pass_ending`: `PASS_WARN` before a paid pass ends (passes don't renew).

Off unless `HOLT_ACCOUNT_EMAILS=1`, and nothing is sent without the mailer
(`RESEND_API_KEY`, mailer.py). The address is the one the user signed in with:
`web/` reports it at each sign-in (`POST /v1/me/sign-in`), and until it has,
the alert settings' address, which is the same one, stands in. Nobody types
an address here.

Every email but the receipt respects one switch, `account_mail.product_on`:
on by default, turned off by the email's "Stop these emails" link and its
one-click header, with the token mechanism alert emails use (the same web
page and route take both kinds of token).

`account_emails` is the sent-log. A send first claims its (user, key) row,
which is unique, so each email goes out once however many runs, requests and
processes find it due. A claim the provider couldn't take is given back and
tried again on a later run.

`run` sends what is due. It runs every `EVERY_S` in the API process, and at
once after a first sign-in or a paid order (`kick`). Account emails count
against the same daily limit as alert emails; a receipt may use the few sends
the others keep in hand.

    python -m holt_server.account_mail                      # one run now
    python -m holt_server.account_mail samples <user id>    # see `send_samples`
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from holt_server import (
    account_email,
    alert_email,
    alerts,
    credits,
    entitlements,
    mailer,
    pricing,
    schema,
)
from holt_server.db import (
    AccountEmail,
    AccountMail,
    AlertSettings,
    Order,
    PlanEvent,
    User,
    now,
    utc,
)
from holt_server.deps import Caller, caller, internal, services, signed_in
from holt_server.errors import ApiError
from holt_server.schema import Model

if TYPE_CHECKING:
    from holt_server.services import Services

log = logging.getLogger("holt_server.account_mail")

router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})

EVERY_S = 900.0
# The emails the "product emails" switch covers: all but the receipt.
PRODUCT = frozenset({"welcome", "trial_ending", "trial_ended", "pass_ending"})
# A welcome or a receipt is sent within this long of the sign-in or payment,
# or not at all (switching the emails on doesn't write to last month's users).
FRESH = timedelta(hours=24)
TRIAL_WARN = timedelta(days=2)
PASS_WARN = timedelta(days=3)
# An "ends on" email isn't sent with less than this left.
MIN_NOTICE = timedelta(hours=12)
# "Your alerts have stopped" isn't sent later than this after they did.
ENDED_WINDOW = timedelta(days=3)
# A claim this old with no outcome was cut off mid-send: it is given back.
# The provider's idempotency key stops a second copy if the first did go.
STUCK = timedelta(minutes=15)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


# --- what is due (pure) -----------------------------------------------------------------


@dataclass(frozen=True)
class Due:
    user_id: str
    kind: str
    # The sent-log key: the kind, with what it is about when there can be several.
    key: str
    # The order a receipt is for.
    order_id: str | None = None


def trial_due(access: alerts.Access, trial_ends: datetime | None, enabled: bool,
              at: datetime) -> str | None:
    """Which email the free days of alerts call for now, if any. Nothing for
    someone who switched alerts off, or whom a pass covers."""
    if trial_ends is None or not enabled:
        return None
    if access.state == "trial" and MIN_NOTICE < trial_ends - at <= TRIAL_WARN:
        return "trial_ending"
    # `until` is later than the free days' end when a pass ran out after them:
    # that end had its own email.
    if (access.state == "ended" and access.until == trial_ends
            and at - trial_ends < ENDED_WINDOW):
        return "trial_ended"
    return None


def pass_due(expires: datetime | None, paid: bool, at: datetime) -> str | None:
    """The sent-log key of the "your pass ends" email due now, if one is.
    The end date is part of it, so a second pass, which moves the end, gets
    its own email. `paid`: the Pro came from a payment, not an admin's gift."""
    if not paid or expires is None or not MIN_NOTICE < expires - at <= PASS_WARN:
        return None
    return f"pass_ending:{expires:%Y-%m-%d}"


# --- the unsubscribe token ---------------------------------------------------------------


def unsubscribe_token(secret: str, user_id: str, nonce: str) -> str:
    """As `alerts.unsubscribe_token`, for the product emails switch. Its own
    prefix: a token for one kind of email never works for the other."""
    return hmac.new(f"account-unsubscribe|{secret}".encode(), f"{user_id}|{nonce}".encode(),
                    hashlib.sha256).hexdigest()


def _rotate(svc: Services, row: AccountMail) -> None:
    row.unsubscribe_nonce = alerts.new_nonce()
    row.unsubscribe_hash = alerts.token_hash(
        unsubscribe_token(svc.settings.secret_key, row.user_id, row.unsubscribe_nonce))


async def prefs(s: AsyncSession, svc: Services, user_id: str) -> AccountMail:
    """The user's row, added to the session if there isn't one. Caller commits."""
    row = await s.get(AccountMail, user_id)
    if row is None:
        row = AccountMail(user_id=user_id, email=None, product_on=True, unsubscribe_nonce="",
                          unsubscribe_hash="", created_at=now(), updated_at=now())
        _rotate(svc, row)
        s.add(row)
    return row


async def set_by_token(s: AsyncSession, token: str, on: bool) -> bool:
    """Turn product emails off (or back on) for the token's owner. False when
    the token isn't one of ours. Caller commits."""
    row = (await s.execute(select(AccountMail).where(
        AccountMail.unsubscribe_hash == alerts.token_hash(token)))).scalar_one_or_none()
    if row is None:
        return False
    row.product_on, row.updated_at = on, now()
    return True


# --- rendering --------------------------------------------------------------------------


def day(d: datetime, tz: ZoneInfo) -> str:
    """"14 October"."""
    local = d.astimezone(tz)
    return f"{local.day} {local:%B}"


def day_year(d: datetime, tz: ZoneInfo) -> str:
    """"14 October 2026"."""
    return f"{day(d, tz)} {d.astimezone(tz).year}"


def money(amount: int, currency: str) -> str:
    """Minor units as people write them: "₹99", "₹249.50", "$7"."""
    whole, rest = divmod(amount, 100)
    number = f"{whole:,}" + (f".{rest:02d}" if rest else "")
    sign = {"INR": "₹", "USD": "$"}.get(currency)
    return f"{sign}{number}" if sign else f"{number} {currency}"


def pro_gives(cat: pricing.Catalogue) -> tuple[int | None, bool]:
    """What Pro gives, for the confirmation: merge plans a month (None when
    they aren't part of it), and whether PR alerts are."""
    pro = cat.plans.get(pricing.PRO)
    features = pro.features if pro else {}
    plans = features.get("merge_plan")
    return (plans.per_month if plans is not None else None), alerts.FEATURE in features


def pass_name(cat: pricing.Catalogue, pass_id: str, days: int | None) -> str:
    """"1 month"."""
    p = cat.passes.get(pass_id)
    return p.name if p is not None else f"{days or 0} days"


def _on_sale(svc: Services) -> bool:
    from holt_server import payments  # it imports this module for `kick`

    return payments.passes_body(svc).on_sale


@dataclass(frozen=True)
class Urls:
    home: str
    find: str
    alerts: str
    prs: str
    me: str
    pricing: str
    refunds: str

    @classmethod
    def of(cls, svc: Services) -> Urls:
        web = svc.settings.web_url.rstrip("/")
        return cls(web, f"{web}/find", f"{web}/settings/alerts", f"{web}/me/contributions",
                   f"{web}/me", f"{web}/pricing", f"{web}/refunds")


def render(svc: Services, kind: str, f: account_email.Frame, tz: ZoneInfo, *,
           user: User | None = None, order: Order | None = None,
           on_sale: bool | None = None) -> alert_email.RenderedEmail:
    """One email, from the rows it is about. `on_sale` (a pass can be bought
    now) is read from the server when not given."""
    u = Urls.of(svc)
    pricing_url = u.pricing if (_on_sale(svc) if on_sale is None else on_sale) else None
    if kind == "welcome":
        return account_email.welcome_email(
            f, u.home, u.find, u.alerts if svc.settings.pr_watch else None)
    if kind == "receipt":
        cat = entitlements.catalogue(svc)
        until = utc(user.plan_expires_at) if user and user.plan == pricing.PRO else None
        paid = utc(order.paid_at) or now()
        merge_plans, with_alerts = pro_gives(cat)
        return account_email.receipt_email(
            f, pass_name=pass_name(cat, order.pack_id, order.expires_days),
            amount=money(order.amount, order.currency), paid_on=mailer.short_date(
                paid.astimezone(tz)),
            # The year only when the pass runs into another one.
            until=(day(until, tz) if until.astimezone(tz).year == paid.astimezone(tz).year
                   else day_year(until, tz)) if until else None,
            merge_plans=merge_plans, alerts=with_alerts,
            payment=order.provider_payment_id or "", plan_url=u.home,
            alerts_url=u.alerts if svc.settings.pr_watch else None, refunds_url=u.refunds)
    if kind in ("trial_ending", "trial_ended"):
        make = (account_email.trial_ending_email if kind == "trial_ending"
                else account_email.trial_ended_email)
        return make(f, day=day(utc(user.alerts_trial_ends_at), tz), days=alerts.TRIAL_DAYS,
                    prs_url=u.prs, pricing_url=pricing_url)
    if kind == "pass_ending":
        return account_email.pass_ending_email(
            f, day=day(utc(user.plan_expires_at), tz), open_url=u.me, pricing_url=pricing_url)
    raise ValueError(f"no account email {kind!r}")


def message(svc: Services, d: Due, row: AccountMail, to: str,
            out: alert_email.RenderedEmail) -> mailer.Message:
    headers = {}
    if d.kind in PRODUCT:
        web = svc.settings.web_url.rstrip("/")
        token = unsubscribe_token(svc.settings.secret_key, row.user_id, row.unsubscribe_nonce)
        # One click, no sign-in (RFC 8058), by the route alert emails use.
        headers = {"List-Unsubscribe": f"<{web}/api/alerts/unsubscribe?t={token}>",
                   "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return mailer.Message(
        to=to, subject=out.subject, html=out.html, text=out.text, headers=headers,
        idempotency_key="holt-account-" + hashlib.sha256(
            f"{d.user_id}|{d.key}".encode()).hexdigest()[:40])


def frame(svc: Services, d: Due, row: AccountMail, to: str) -> account_email.Frame:
    web = svc.settings.web_url.rstrip("/")
    link = None
    if d.kind in PRODUCT:
        token = unsubscribe_token(svc.settings.secret_key, row.user_id, row.unsubscribe_nonce)
        link = f"{web}/alerts/unsubscribe?t={token}"
    return account_email.Frame(to=to, home_url=web, unsubscribe_url=link)


# --- one run ----------------------------------------------------------------------------


@dataclass
class Run:
    sent: int = 0
    failed: int = 0
    # Left for a later run: the provider's daily limit is near.
    held: int = 0
    # Due, with no address to send it to.
    no_address: int = 0
    # Why nothing was tried: "off" (the switch), "no_mailer", or None.
    skipped: str | None = None


def on(svc: Services) -> bool:
    return svc.settings.account_emails and svc.mailer is not None


async def due(s: AsyncSession, svc: Services, at: datetime) -> list[Due]:
    """Every email due now and not in the sent-log: receipts first, then
    welcomes, then the "ending" ones."""
    found: list[Due] = []
    for order in (await s.execute(
            select(Order).where(Order.status == "paid", Order.credits == 0,
                                Order.paid_at >= at - FRESH).order_by(Order.paid_at))).scalars():
        found.append(Due(order.user_id, "receipt", f"receipt:{order.id}", order.id))
    for user_id in (await s.execute(
            select(AccountMail.user_id).where(AccountMail.welcome_due_at >= at - FRESH)
            .order_by(AccountMail.welcome_due_at))).scalars():
        found.append(Due(user_id, "welcome", "welcome"))
    for user, enabled in await s.execute(
            select(User, AlertSettings.enabled)
            .join(AlertSettings, AlertSettings.user_id == User.id)
            .where(User.alerts_trial_ends_at > at - ENDED_WINDOW,
                   User.alerts_trial_ends_at <= at + TRIAL_WARN)):
        kind = trial_due(alerts.access_for(svc, user, at), utc(user.alerts_trial_ends_at),
                         bool(enabled), at)
        if kind:
            found.append(Due(user.id, kind, kind))
    ending = (await s.execute(
        select(User).where(User.plan == pricing.PRO, User.plan_expires_at > at,
                           User.plan_expires_at <= at + PASS_WARN))).scalars().all()
    if ending:
        # Whoever set the plan last: a payment, or an admin.
        last: dict[str, str | None] = {}
        for user_id, actor in await s.execute(
                select(PlanEvent.user_id, PlanEvent.actor)
                .where(PlanEvent.user_id.in_([u.id for u in ending])).order_by(PlanEvent.id)):
            last[user_id] = actor
        for user in ending:
            key = pass_due(utc(user.plan_expires_at), last.get(user.id) == "payment", at)
            if key:
                found.append(Due(user.id, "pass_ending", key))
    if not found:
        return []
    logged = {(u, k) for u, k in await s.execute(
        select(AccountEmail.user_id, AccountEmail.key)
        .where(AccountEmail.user_id.in_({d.user_id for d in found})))}
    return [d for d in found if (d.user_id, d.key) not in logged]


_said_off = False


async def run(svc: Services, at: datetime | None = None) -> Run:
    """Send what is due. Does nothing with the switch off or without a mailer."""
    global _said_off
    if not on(svc):
        if svc.settings.account_emails and not _said_off:
            _said_off = True
            log.info("account emails are switched on, but RESEND_API_KEY (or "
                     "HOLT_SECRET_KEY) isn't set: none are sent")
        return Run(skipped="no_mailer" if svc.settings.account_emails else "off")
    at = at or now()
    out = Run()
    async with svc.db.session() as s:
        await s.execute(delete(AccountEmail).where(AccountEmail.status == "pending",
                                                   AccountEmail.sent_at < at - STUCK))
        await s.commit()
        todo = await due(s, svc, at)
        left = svc.settings.alert_email_daily_limit - await mailer.sent_today(s, at)
    for d in todo:
        # A receipt may use the sends the other emails keep in hand.
        if left <= (0 if d.kind == "receipt" else mailer.LIMIT_MARGIN):
            out.held += 1
            continue
        try:
            ok = await _send(svc, d, at)
        except mailer.MailLater as exc:
            log.warning("account emails: the provider didn't take one (%s); it is tried "
                        "again next run", exc)
            out.failed += 1
            break  # busy or down: the rest would go the same way
        except Exception:  # noqa: BLE001 -- one person's email never blocks the others
            log.exception("account emails: sending one failed")
            out.failed += 1
            continue
        left -= ok == "sent"
        out.sent += ok == "sent"
        out.failed += ok == "failed"
        out.no_address += ok == "no_address"
    if out.held:
        log.warning("account emails: %d held back, the provider's daily limit (%d) is near",
                    out.held, svc.settings.alert_email_daily_limit)
    return out


async def _send(svc: Services, d: Due, at: datetime) -> str | None:
    """Claim one email in the sent-log, send it and record how it went:
    "sent", "failed" (the provider refused it for good) or "no_address".
    None when it isn't to be sent now: switched off by the user, the quiet
    hours, or another run has it."""
    async with svc.db.session() as s:
        row = await prefs(s, svc, d.user_id)
        if d.kind in PRODUCT and not row.product_on:
            return None
        alert_row = await s.get(AlertSettings, d.user_id)
        to = row.email or (alert_row.email if alert_row else None)
        if not to:
            return "no_address"
        tz = mailer.zone(alert_row.tz if alert_row else "UTC")
        # The "ending" emails keep the alert emails' quiet hours, for someone
        # whose time zone is known.
        if (d.kind in PRODUCT and d.kind != "welcome" and alert_row is not None
                and mailer.quiet(at.astimezone(tz))):
            return None
        # The token comes from HOLT_SECRET_KEY: if that was rotated, the
        # stored hash is brought in step so this email's link works.
        current = alerts.token_hash(unsubscribe_token(
            svc.settings.secret_key, row.user_id, row.unsubscribe_nonce))
        if current != row.unsubscribe_hash:
            row.unsubscribe_hash = current
        user = await s.get(User, d.user_id)
        order = await s.get(Order, d.order_id) if d.order_id else None
        out = render(svc, d.kind, frame(svc, d, row, to), tz, user=user, order=order)
        msg = message(svc, d, row, to, out)
        claim = AccountEmail(user_id=d.user_id, kind=d.kind, key=d.key, status="pending",
                             sent_at=at)
        s.add(claim)
        try:
            await s.commit()
        except IntegrityError:  # another run has it (or made the user's row just now)
            await s.rollback()
            return None
        claim_id = claim.id
    provider_id, status = None, "sent"
    try:
        provider_id = await asyncio.to_thread(svc.mailer.send, msg)
    except mailer.MailRefused as exc:
        log.warning("account emails: the provider refused one (%d)", exc.status)
        provider_id, status = str(exc.status), "failed"
    except BaseException:
        async with svc.db.session() as s:
            await s.execute(delete(AccountEmail).where(AccountEmail.id == claim_id))
            await s.commit()
        raise
    async with svc.db.session() as s:
        await s.execute(update(AccountEmail).where(AccountEmail.id == claim_id)
                        .values(status=status, provider_id=provider_id))
        await s.commit()
    return status


_background: set[asyncio.Task] = set()


async def _quietly(svc: Services) -> None:
    try:
        got = await run(svc)
    except Exception:  # noqa: BLE001 -- the scheduled run tries again
        log.exception("account emails failed")
        return
    if got.sent or got.failed or got.no_address:
        # Said here and not by the scheduled run, which would repeat it.
        log.info("account emails: %d sent, %d failed, %d waiting for a sign-in address "
                 "(sent once the user signs in again)", got.sent, got.failed, got.no_address)


def kick(svc: Services) -> None:
    """Send what is due now, without waiting for it: called after a first
    sign-in and after an order is paid, so those emails don't wait for the
    next scheduled run. Nothing happens with the emails off."""
    if not on(svc):
        return
    task = asyncio.create_task(_quietly(svc), name="holt-account-mail-now")
    _background.add(task)
    task.add_done_callback(_background.discard)


async def schedule(svc: Services, first_delay_s: float = 120.0) -> None:
    """Every EVERY_S, in the API process, until cancelled."""
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            got = await run(svc)
            if got.sent or got.failed:
                log.info("account emails: %d sent, %d failed", got.sent, got.failed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- try again next time
            log.exception("account emails failed")
        await asyncio.sleep(EVERY_S)


# --- routes -----------------------------------------------------------------------------


class SignInBody(Model):
    """POST /v1/me/sign-in: what `web/` knows at a sign-in."""

    # The address the sign-in provider gave for this account. Never typed.
    email: str | None = Field(None, max_length=320)
    # This sign-in created the account.
    first: bool = False


class EmailPrefs(Model):
    # Where account emails go: the sign-in address, once `web/` has reported it.
    email: str | None
    # The welcome and the "ending" emails. A receipt goes out either way.
    product_emails: bool


class EmailPrefsBody(Model):
    product_emails: bool


class LabEmail(Model):
    # welcome | receipt | trial_ending | trial_ended | pass_ending, or PR
    # watch's alert_now | alert_daily
    kind: str
    # What the sample shows: "Welcome", "Alerts ending, a pass on sale".
    name: str
    subject: str
    preheader: str
    html: str
    text: str


class LabEmails(Model):
    emails: list[LabEmail]


def _prefs_body(row: AccountMail | None) -> EmailPrefs:
    return EmailPrefs(email=row.email if row else None,
                      product_emails=row.product_on if row else True)


@router.post("/me/sign-in", status_code=204, response_class=Response)
async def sign_in(body: SignInBody, request: Request,
                  who: Caller = Depends(caller)) -> Response:
    """`web/` calls this at every sign-in. It keeps the account's address in
    step and, for a first sign-in, makes the welcome email due. The address is
    kept with the emails switched off too, so they have somewhere to go once
    they are on."""
    svc = services(request)
    user_id = signed_in(who)
    email = body.email.strip() if body.email else None
    if email is not None and not _EMAIL.fullmatch(email):
        raise ApiError("invalid_request", "That doesn't look like an email address.")
    await credits.ensure_user(svc, user_id)
    at = now()
    async with svc.db.session() as s:
        row = await prefs(s, svc, user_id)
        if email and email != row.email:
            # The old inbox's unsubscribe links mustn't reach the new address.
            row.email = email
            _rotate(svc, row)
        if body.first and row.welcome_due_at is None:
            row.welcome_due_at = at
        row.updated_at = at
        try:
            await s.commit()
        except IntegrityError:  # two sign-ins at once made the row twice
            await s.rollback()
    kick(svc)
    return Response(status_code=204)


@router.get("/me/emails")
async def get_email_prefs(request: Request, who: Caller = Depends(caller)) -> EmailPrefs:
    svc = services(request)
    user_id = signed_in(who)
    async with svc.db.session() as s:
        return _prefs_body(await s.get(AccountMail, user_id))


@router.put("/me/emails")
async def put_email_prefs(body: EmailPrefsBody, request: Request,
                          who: Caller = Depends(caller)) -> EmailPrefs:
    svc = services(request)
    user_id = signed_in(who)
    async with svc.db.session() as s:
        row = await prefs(s, svc, user_id)
        row.product_on, row.updated_at = body.product_emails, now()
        try:
            await s.commit()
        except IntegrityError:  # two first saves at once
            raise ApiError("internal", "Something went wrong on our side. Try again.") from None
        return _prefs_body(row)


def samples(svc: Services, to: str = "you@example.com",
            unsubscribe_url: str | None = None) -> list[LabEmail]:
    """Every Holt email on made-up data: the account emails, each way they
    can read, and PR watch's two."""
    at = datetime(2026, 10, 1, 9, tzinfo=mailer.zone("UTC"))
    tz = mailer.zone("Asia/Kolkata")
    u = Urls.of(svc)
    stop = unsubscribe_url or f"{u.home}/alerts/unsubscribe?t=sample"
    user = User(id="lab", plan=pricing.PRO, plan_expires_at=at + timedelta(days=30),
                alerts_trial_ends_at=at + timedelta(days=2))
    order = Order(id="lab", user_id="lab", pack_id="pro_1m", credits=0, expires_days=30,
                  amount=9900, currency="INR", provider="razorpay",
                  provider_order_id="order_lab", provider_payment_id="pay_Q7hXw2LmN4vT9c",
                  status="paid", paid_at=at)
    ending = User(id="lab", plan=pricing.PRO, plan_expires_at=at + timedelta(days=3))
    shown = [("welcome", "Welcome", user, None),
             ("receipt", "Pass confirmation", user, None),
             ("trial_ending", "Alerts ending, a pass on sale", user, True),
             ("trial_ending", "Alerts ending, no pass on sale", user, False),
             ("trial_ended", "Alerts ended, a pass on sale", user, True),
             ("trial_ended", "Alerts ended, no pass on sale", user, False),
             ("pass_ending", "Pass ending, a pass on sale", ending, True),
             ("pass_ending", "Pass ending, no pass on sale", ending, False)]
    out = []
    for kind, name, who, on_sale in shown:
        f = account_email.Frame(to=to, home_url=u.home,
                                unsubscribe_url=stop if kind in PRODUCT else None)
        got = render(svc, kind, f, tz, user=who, order=order, on_sale=bool(on_sale))
        out.append(LabEmail(kind=kind, name=name, subject=got.subject,
                            preheader=got.preheader, html=got.html, text=got.text))

    def pr(kind: str, repo: str, number: int, title: str, facts: dict) -> alert_email.EmailAlert:
        return alert_email.EmailAlert(
            kind=kind, repo=repo, number=number, title=title,
            pr_url=f"https://github.com/{repo}/pull/{number}", report_url=f"{u.home}/{repo}",
            facts=facts)

    click = pr("changes", "pallets/click", 2811, "Fix shell completion for nested groups",
               {"who": "davidism"})
    frame_ = alert_email.EmailFrame(
        to=to, status="Alerts until 14 Oct. Your turn right away, the rest at 8:00.",
        prs_url=u.prs, settings_url=u.alerts, unsubscribe_url=stop, home_url=u.home)
    watch = [
        ("alert_now", "PR watch: your turn", alert_email.your_turn_email([click], frame_)),
        ("alert_now", "PR watch: your turn, two pull requests", alert_email.your_turn_email(
            [click, pr("reply", "astral-sh/ruff", 14022, "Add a rule for unused loop variables",
                       {"who": "charliermarsh"})], frame_)),
        ("alert_daily", "PR watch: daily", alert_email.daily_email([
            pr("late_reply", "processing/p5.js", 7120,
               "Add describe() to the textToPoints reference", {"days": 6, "slow_hours": 96}),
            pr("stale_soon", "EbookFoundation/free-programming-books", 11020,
               "Add Rust books in Hindi", {"quiet": 25, "close": 30}),
            pr("approved", "dotnet/efcore", 3310, "Translate DateOnly.DayNumber on SQLite",
               {"who": "jrios"}),
            pr("closed", "moment/moment", 6120, "Add an Odia locale", {}),
        ], frame_, "Thursday 1 October")),
    ]
    out += [LabEmail(kind=kind, name=name, subject=got.subject, preheader=got.preheader,
                     html=got.html, text=got.text) for kind, name, got in watch]
    return out


async def send_samples(svc: Services, user_id: str) -> int:
    """Send one real copy of every sample to a user's own sign-in address, so
    the owner can read them in a real inbox. Not in production. Returns how
    many went out. Nothing is written to the sent-log."""
    if svc.settings.env == "production":
        raise ValueError("samples aren't sent in production")
    if svc.mailer is None:
        raise ValueError("no mailer: RESEND_API_KEY (or HOLT_SECRET_KEY) isn't set")
    async with svc.db.session() as s:
        row = await s.get(AccountMail, user_id)
        alert_row = await s.get(AlertSettings, user_id)
        to = (row.email if row else None) or (alert_row.email if alert_row else None)
        if not to:
            raise ValueError("no sign-in address on file for that user: sign in again first")
        row = await prefs(s, svc, user_id)
        await s.commit()
        web = svc.settings.web_url.rstrip("/")
        stop = (f"{web}/alerts/unsubscribe?t="
                + unsubscribe_token(svc.settings.secret_key, user_id, row.unsubscribe_nonce))
    stamp = now().isoformat()
    sent = 0
    for i, e in enumerate(samples(svc, to, stop)):
        await asyncio.to_thread(svc.mailer.send, mailer.Message(
            to=to, subject=e.subject, html=e.html, text=e.text, headers={},
            idempotency_key="holt-sample-" + hashlib.sha256(
                f"{user_id}|{i}|{stamp}".encode()).hexdigest()[:40]))
        sent += 1
    return sent


@router.get("/lab/emails", dependencies=[Depends(internal)])
async def lab_emails(request: Request) -> LabEmails:
    """Every Holt email on made-up data, for the owner to read on staging.
    Not in production."""
    svc = services(request)
    if svc.settings.env == "production":
        raise ApiError("not_found", "There's nothing here.")
    return LabEmails(emails=samples(svc))


def main(argv: list[str] | None = None) -> int:
    from holt_server.services import Services
    from holt_server.settings import get_settings

    args = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level="INFO")
    if args and (args[0] != "samples" or len(args) != 2):
        print("usage: python -m holt_server.account_mail [samples <user id>]")
        return 2

    async def go() -> Run | int:
        svc = Services(get_settings())
        try:
            return await send_samples(svc, args[1]) if args else await run(svc)
        finally:
            svc.http.close()
            await svc.db.dispose()

    try:
        got = asyncio.run(go())
    except ValueError as exc:
        print(exc)
        return 1
    if isinstance(got, int):
        print(f"sent {got} samples")
    elif got.skipped == "off":
        print("account emails are off (HOLT_ACCOUNT_EMAILS)")
    elif got.skipped:
        print("account emails are on, but there is no RESEND_API_KEY")
    else:
        print(f"sent {got.sent}, failed {got.failed}, held back {got.held}, "
              f"no address {got.no_address}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
