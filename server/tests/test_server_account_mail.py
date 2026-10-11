"""Account emails (account_mail.py, account_email.py): the welcome, a pass's
receipt and the "ending" emails; who gets which and when, the product emails
switch, and the sent-log that makes each go out once. A fake provider, no
network."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from holt_server import account_email, account_mail, alerts, mailer, payments
from holt_server.db import AccountEmail, AccountMail, Order, PlanEvent, User, now
from sqlalchemy import select

from test_server_contributions import call
from test_server_mailer import FakeMailer

YOU = "you@example.com"
# 15:30 in India, where the seeded alert settings say the user is.
NOON = datetime(2026, 10, 10, 10, tzinfo=UTC)


@pytest.fixture
def hm(make_harness):
    h = make_harness(HOLT_ACCOUNT_EMAILS=True, HOLT_PR_WATCH=True)
    h.svc.mailer = h.outbox = FakeMailer()
    return h


def settle(h) -> None:
    """Wait for the runs `kick` started."""
    async def go():
        while account_mail._background:
            await asyncio.sleep(0.01)
    h.client.portal.call(go)


def sign_in(h, user="u1", email: str | None = YOU, first=False):
    r = h.post("/v1/me/sign-in", {"email": email, "first": first}, user=user)
    settle(h)
    return r


def run(h, at=None) -> account_mail.Run:
    async def go():
        return await account_mail.run(h.svc, at)
    return h.client.portal.call(go)


def log(h) -> list[tuple[str, str, str]]:
    async def go(s):
        rows = (await s.execute(select(AccountEmail).order_by(AccountEmail.id))).scalars()
        return [(r.user_id, r.key, r.status) for r in rows]
    return call(h, go)


def watcher(h, trial_ends: datetime, user="u1", enabled=True, email: str | None = YOU,
            **user_fields) -> None:
    """A user who turned alerts on, whose free days end at `trial_ends`."""
    async def go(s):
        s.add(User(id=user, plan="free", alerts_trial_ends_at=trial_ends, **user_fields))
        row = alerts.new_settings(h.svc, user)
        row.enabled, row.email, row.tz = enabled, email, "Asia/Kolkata"
        s.add(row)
    call(h, go)


def pro(h, expires: datetime, user="u1", actor="payment") -> None:
    """Put a user on Pro until `expires`, as a payment (or an admin) would."""
    async def go(s):
        got = await s.get(User, user)
        if got is None:
            s.add(User(id=user, plan="pro", plan_expires_at=expires))
        else:
            got.plan, got.plan_expires_at = "pro", expires
        s.add(PlanEvent(user_id=user, plan="pro", expires_at=expires, reason="pass pro_1m",
                        actor=actor))
    call(h, go)


def unsubscribe_token(msg: mailer.Message) -> str:
    assert msg.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    return msg.headers["List-Unsubscribe"].removeprefix(
        "<https://githolt.com/api/alerts/unsubscribe?t=").removesuffix(">")


# --- the welcome ----------------------------------------------------------------------------


def test_a_first_sign_in_gets_one_welcome_ever(hm):
    assert sign_in(hm, first=True).status_code == 204
    [msg] = hm.outbox.sent
    assert (msg.to, msg.subject) == (YOU, "Welcome to Holt")
    for link in ("https://githolt.com", "https://githolt.com/find",
                 "https://githolt.com/settings/alerts"):
        assert f'href="{link}"' in msg.html and link in msg.text
    assert f"https://githolt.com/alerts/unsubscribe?t={unsubscribe_token(msg)}" in msg.text
    assert log(hm) == [("u1", "welcome", "sent")]
    # Signing in again, the scheduled run, even a second "first": nothing more.
    sign_in(hm)
    sign_in(hm, first=True)
    assert run(hm).sent == 0
    assert len(hm.outbox.sent) == 1


def test_an_account_from_before_gets_no_welcome(hm):
    sign_in(hm, first=False)
    assert run(hm).sent == 0 and hm.outbox.sent == []


def test_the_welcome_is_not_sent_a_day_late(hm):
    """Switching the emails on doesn't write to people who signed up earlier."""
    async def old(s):
        row = await account_mail.prefs(s, hm.svc, "u1")
        row.email, row.welcome_due_at = YOU, now() - timedelta(hours=25)
    call(hm, old)
    assert run(hm).sent == 0


def test_the_welcome_leaves_alerts_out_while_pr_watch_is_off(make_harness):
    h = make_harness(HOLT_ACCOUNT_EMAILS=True)
    h.svc.mailer = h.outbox = FakeMailer()
    sign_in(h, first=True)
    [msg] = h.outbox.sent
    assert "Find projects that welcome first-time contributors" in msg.text
    assert "Go get merged." in msg.text
    assert "Turn on PR alerts" not in msg.text + msg.html and "settings/alerts" not in msg.html


def test_the_address_is_the_one_from_sign_in(hm, caplog):
    assert sign_in(hm, email="not an address").status_code == 400
    # No address reported and none on the alert settings: nothing to send to,
    # and the log says so.
    with caplog.at_level("INFO", logger="holt_server.account_mail"):
        sign_in(hm, email=None, first=True)
    assert hm.outbox.sent == [] and log(hm) == []
    assert "1 waiting for a sign-in address" in caplog.text
    assert run(hm).no_address == 1
    # The next sign-in brings it, within the day.
    sign_in(hm)
    assert [m.to for m in hm.outbox.sent] == [YOU]


def test_the_alert_settings_address_stands_in_until_a_sign_in_reports_one(hm):
    watcher(hm, NOON + timedelta(days=2), email="alerts@example.com")
    assert run(hm, NOON).sent == 1
    assert hm.outbox.sent[0].to == "alerts@example.com"


# --- the product emails switch ----------------------------------------------------------------


def test_one_click_unsubscribe_stops_product_emails_and_not_receipts(hm):
    sign_in(hm, first=True)
    token = unsubscribe_token(hm.outbox.sent[0])
    r = hm.post("/v1/alerts/unsubscribe", {"token": token})
    assert r.json() == {"email_on": False, "emails": "product"}
    assert hm.get("/v1/me/emails", user="u1").json() == {"email": YOU, "product_emails": False}

    paid(hm)  # the receipt goes out all the same
    assert [m.subject for m in hm.outbox.sent[1:]] == [receipt_subject(hm, "u1")]
    # The page's undo turns them back on.
    assert hm.post("/v1/alerts/resubscribe", {"token": token}).json() == {
        "email_on": True, "emails": "product"}
    assert hm.get("/v1/me/emails", user="u1").json()["product_emails"] is True


def test_the_ending_emails_respect_the_switch(hm):
    watcher(hm, now() + timedelta(days=1, hours=20))
    assert hm.put("/v1/me/emails", {"product_emails": False}, user="u1").json() == {
        "email": None, "product_emails": False}
    assert run(hm, in_daytime(hm)).sent == 0 and log(hm) == []
    hm.put("/v1/me/emails", {"product_emails": True}, user="u1")
    assert run(hm, in_daytime(hm)).sent == 1
    assert hm.outbox.sent[0].subject.startswith("Your free PR alerts end on ")


def in_daytime(h) -> datetime:
    """Now, or a few hours on when it is night in India (the "ending" emails
    keep the quiet hours), still inside the two days before the end."""
    at = now()
    while mailer.quiet(at.astimezone(mailer.zone("Asia/Kolkata"))):
        at += timedelta(hours=1)
    return at


def unsubscribe_token_for(h, user: str) -> str:
    async def go(s):
        row = await s.get(AccountMail, user)
        return account_mail.unsubscribe_token(h.svc.settings.secret_key, user,
                                              row.unsubscribe_nonce)
    return call(h, go)


def test_an_alert_emails_token_and_an_account_emails_token_are_not_the_same(hm):
    watcher(hm, now() + timedelta(days=10))
    sign_in(hm)
    async def alert_token(s):
        from holt_server.db import AlertSettings
        row = await s.get(AlertSettings, "u1")
        return alerts.unsubscribe_token(hm.svc.settings.secret_key, "u1", row.unsubscribe_nonce)
    r = hm.post("/v1/alerts/unsubscribe", {"token": call(hm, alert_token)})
    assert r.json() == {"email_on": False, "emails": "alerts"}
    assert hm.get("/v1/me/emails", user="u1").json()["product_emails"] is True
    assert hm.post("/v1/alerts/unsubscribe", {"token": "f" * 64}).status_code == 404


def test_a_new_address_gets_a_new_unsubscribe_link(hm):
    sign_in(hm)
    old = unsubscribe_token_for(hm, "u1")
    sign_in(hm, email="new@example.com")
    assert unsubscribe_token_for(hm, "u1") != old
    assert hm.post("/v1/alerts/unsubscribe", {"token": old}).status_code == 404


# --- the receipt ------------------------------------------------------------------------------


def paid(h, user="u1", order_id="o1", payment="pay_A1") -> bool:
    """An order for the 1 month pass, paid: through the real credit path."""
    async def go(s):
        if await s.get(User, user) is None:
            s.add(User(id=user, plan="free"))
        s.add(Order(id=order_id, user_id=user, pack_id="pro_1m", credits=0, expires_days=30,
                    amount=9900, currency="INR", provider="razorpay",
                    provider_order_id=f"order_{order_id}"))
    call(h, go)
    took = h.client.portal.call(lambda: payments.credit(h.svc, order_id, payment))
    settle(h)
    return took


def receipt_subject(h, user: str) -> str:
    return "You're on Holt Pro"


def pro_until(h, user: str) -> str:
    """"31 October", with the year when the pass runs into the next one."""
    async def go(s):
        return (await s.get(User, user)).plan_expires_at
    ends = call(h, go)
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=UTC)
    utc_ = mailer.zone("UTC")
    same_year = ends.year == now().year
    return account_mail.day(ends, utc_) if same_year else account_mail.day_year(ends, utc_)


def test_a_paid_pass_gets_a_receipt_once(hm):
    sign_in(hm)
    assert paid(hm) is True
    [msg] = hm.outbox.sent
    assert msg.to == YOU and msg.subject == receipt_subject(hm, "u1")
    for line in ("You're on Pro.", f"Your pass is live through {pro_until(hm, 'u1')}.",
                 "Here's what you've got:", "30 merge plans a month. Get your first PR ",
                 "PR alerts. We'll let you know ",
                 "Make a merge plan: https://githolt.com",
                 "Turn on PR alerts: https://githolt.com/settings/alerts",
                 "₹99 · 1 month pass · paid ", " · one-time, no auto-renewal",
                 "Payment ID pay_A1 (keep it for refunds)",
                 "Refund policy: https://githolt.com/refunds"):
        assert line in msg.text
    # The payment details are small print, under the one solid button.
    assert msg.html.count('class="h-btn"') == 1
    assert msg.html.index("make a merge plan") < msg.html.index("Payment ID pay_A1")
    # Transactional: no unsubscribe header or link.
    assert msg.headers == {} and "Stop these emails" not in msg.text + msg.html
    assert log(hm) == [("u1", "receipt:o1", "sent")]
    # The webhook arriving after the confirm call, and later runs: nothing more.
    assert hm.client.portal.call(lambda: payments.credit(hm.svc, "o1", "pay_A1")) is False
    settle(hm)
    assert run(hm).sent == 0 and len(hm.outbox.sent) == 1
    # A second pass is a second receipt.
    paid(hm, order_id="o2", payment="pay_B2")
    assert len(hm.outbox.sent) == 2 and "Payment ID pay_B2" in hm.outbox.sent[1].text


def test_a_session_from_before_these_emails_still_gets_its_receipt(hm):
    """Checkout reports the session's address (web's order route), as a
    sign-in would, without making a welcome due."""
    hm.post("/v1/me/sign-in", {"email": YOU, "first": False}, user="old")
    settle(hm)
    assert hm.outbox.sent == []
    paid(hm, user="old")
    assert [(m.to, m.subject) for m in hm.outbox.sent] == [(YOU, "You're on Holt Pro")]


def test_a_receipt_goes_out_past_the_margin_the_other_emails_keep(make_harness):
    h = make_harness(HOLT_ACCOUNT_EMAILS=True, HOLT_ALERT_EMAIL_DAILY_LIMIT=6)
    h.svc.mailer = h.outbox = FakeMailer()
    sign_in(h)
    paid(h)
    sign_in(h, user="u2", email="two@example.com", first=True)
    # 6 a day, 5 kept in hand, 1 sent: the welcome waits, a receipt doesn't.
    assert [m.subject for m in h.outbox.sent] == [receipt_subject(h, "u1")]
    assert run(h).held == 1
    paid(h, user="u2", order_id="o2", payment="pay_B2")
    assert [m.to for m in h.outbox.sent] == [YOU, "two@example.com"]


# --- the free days of alerts ending -----------------------------------------------------------


def test_when_the_trial_emails_are_due():
    ends = NOON + timedelta(days=5)
    trial, over = alerts.Access("trial", ends), alerts.Access("ended", ends)
    due = account_mail.trial_due
    assert due(trial, ends, True, ends - timedelta(days=2, minutes=1)) is None
    assert due(trial, ends, True, ends - timedelta(days=2)) == "trial_ending"
    assert due(trial, ends, True, ends - timedelta(hours=13)) == "trial_ending"
    # Too close to the end to say "ends on": the "stopped" email follows.
    assert due(trial, ends, True, ends - timedelta(hours=11)) is None
    assert due(over, ends, True, ends) == "trial_ended"
    assert due(over, ends, True, ends + timedelta(days=2, hours=23)) == "trial_ended"
    assert due(over, ends, True, ends + timedelta(days=3)) is None
    # Alerts switched off, a pass covering them, or a pass that ran out later.
    assert due(trial, ends, False, ends - timedelta(days=1)) is None
    assert due(alerts.Access("pro", ends + timedelta(days=30)), ends, True,
               ends - timedelta(days=1)) is None
    assert due(alerts.Access("ended", ends + timedelta(days=1)), ends, True,
               ends + timedelta(days=2)) is None
    assert due(alerts.Access("off"), None, True, NOON) is None


def test_two_days_before_and_once_when_they_end(hm):
    ends = NOON + timedelta(days=2)
    watcher(hm, ends)
    assert run(hm, NOON - timedelta(hours=1)).sent == 0  # more than two days left
    assert run(hm, NOON).sent == 1
    [msg] = hm.outbox.sent
    assert msg.subject == "Your free PR alerts end on 12 October"
    assert "You've had 14 days of alerts." in msg.text
    assert "No worries. Reports, Find, and your pull requests page are still free." in msg.text
    assert "https://githolt.com/me/contributions" in msg.text
    # No pass is on sale here: no link to pricing.
    assert "pricing" not in msg.text + msg.html
    assert unsubscribe_token(msg)
    assert run(hm, NOON + timedelta(days=1)).sent == 0
    assert run(hm, ends + timedelta(minutes=5)).sent == 1
    ended = hm.outbox.sent[1]
    assert ended.subject == "Your free PR alerts have ended"
    assert "Your 14 days of PR alerts are up." in ended.text
    assert "As of 12 October, Holt has stopped watching your open PRs" in ended.text
    assert run(hm, ends + timedelta(days=1)).sent == 0
    assert [k for _, k, _ in log(hm)] == ["trial_ending", "trial_ended"]


def test_the_ending_emails_keep_the_quiet_hours(hm):
    night = datetime(2026, 10, 10, 20, tzinfo=UTC)  # 1:30 in India
    watcher(hm, night + timedelta(days=1, hours=20))
    assert run(hm, night).sent == 0 and log(hm) == []
    assert run(hm, night + timedelta(hours=7)).sent == 1  # 8:30


def test_no_trial_emails_for_someone_a_pass_covers_or_with_alerts_off(hm):
    watcher(hm, NOON + timedelta(days=1), user="covered", plan_expires_at=None)
    pro(hm, NOON + timedelta(days=40), user="covered")
    watcher(hm, NOON + timedelta(days=1), user="off", enabled=False)
    assert run(hm, NOON).sent == 0
    assert run(hm, NOON + timedelta(days=1, hours=1)).sent == 0


def test_the_pricing_link_is_there_only_while_a_pass_is_on_sale():
    f = account_email.Frame(YOU, "https://githolt.com", "https://githolt.com/alerts/unsubscribe?t=x")
    kw = dict(day="12 October", days=14, prs_url="https://githolt.com/me/contributions")
    on = account_email.trial_ended_email(f, pricing_url="https://githolt.com/pricing", **kw)
    off = account_email.trial_ended_email(f, pricing_url=None, **kw)
    assert "Want the alerts back? Get them with Holt Pro:\nhttps://githolt.com/pricing" in on.text
    assert ('Want the alerts back? <a class="h-link" href="https://githolt.com/pricing"'
            in on.html and ">Get them with Holt Pro</a>." in on.html)
    assert "The rest of Holt is still free: Reports, Find, and your pull requests page." in on.text
    assert "pricing" not in off.text + off.html and "Holt Pro" not in off.text
    assert "The rest is still free. Reports, Find, and your pull requests page." in off.text
    ending = account_email.trial_ending_email(f, pricing_url="https://githolt.com/pricing", **kw)
    assert ("If you want to keep the alerts running, Holt Pro has you covered:\n"
            "https://githolt.com/pricing") in ending.text
    assert "Everything else is still yours." in ending.text
    plain = account_email.trial_ending_email(f, pricing_url=None, **kw)
    assert "No worries. Reports, Find, and your pull requests page are still free." in plain.text
    assert "pricing" not in plain.text + plain.html


# --- a pass ending ----------------------------------------------------------------------------


def test_when_the_pass_ending_email_is_due():
    ends = NOON + timedelta(days=10)
    due = account_mail.pass_due
    assert due(ends, True, ends - timedelta(days=3, minutes=1)) is None
    assert due(ends, True, ends - timedelta(days=3)) == "pass_ending:2026-10-20"
    assert due(ends, True, ends - timedelta(hours=13)) == "pass_ending:2026-10-20"
    assert due(ends, True, ends - timedelta(hours=11)) is None
    assert due(ends, False, ends - timedelta(days=1)) is None  # an admin's gift
    assert due(None, True, NOON) is None  # Pro with no end


def test_three_days_before_a_pass_ends_and_again_for_the_next_pass(hm):
    sign_in(hm)
    ends = NOON + timedelta(days=3)
    pro(hm, ends)
    pro(hm, NOON + timedelta(days=2), user="gift", actor="admin")
    assert run(hm, NOON - timedelta(hours=1)).sent == 0
    assert run(hm, NOON).sent == 1
    [msg] = hm.outbox.sent
    assert msg.subject == "Your Holt Pro pass ends on 13 October"
    assert "No renewal, no surprise charge. It was a one-time pass." in msg.text
    assert "Reports, Find, and your pull requests page will keep working." in msg.text
    assert "Open Holt: https://githolt.com/me" in msg.text and unsubscribe_token(msg)
    assert run(hm, NOON + timedelta(days=1)).sent == 0
    # Another pass moves the end: that end gets its own email, three days before.
    later = ends + timedelta(days=30)
    pro(hm, later)
    assert run(hm, NOON + timedelta(days=2)).sent == 0
    assert run(hm, later - timedelta(days=2)).sent == 1
    assert [k for _, k, _ in log(hm)] == ["pass_ending:2026-10-13", "pass_ending:2026-11-12"]


def test_a_pass_on_sale_is_the_ending_emails_button():
    f = account_email.Frame(YOU, "https://githolt.com", "https://githolt.com/alerts/unsubscribe?t=x")
    on = account_email.pass_ending_email(f, day="13 October", open_url="https://githolt.com/me",
                                         pricing_url="https://githolt.com/pricing")
    assert "If you want another pass:\nhttps://githolt.com/pricing" in on.text
    assert "Nothing will renew and you won't be charged again. It was a one-time pass." in on.text
    assert on.html.count('class="h-btn"') == 1 and "get another pass →" in on.html


# --- once each --------------------------------------------------------------------------------


def test_two_runs_at_once_send_one_email(hm):
    watcher(hm, NOON + timedelta(days=2))

    async def both():
        return await asyncio.gather(account_mail.run(hm.svc, NOON),
                                    account_mail.run(hm.svc, NOON))
    a, b = hm.client.portal.call(both)
    assert a.sent + b.sent == 1 and len(hm.outbox.sent) == 1
    assert log(hm) == [("u1", "trial_ending", "sent")]


def test_trouble_at_the_provider_is_tried_again_and_a_refusal_is_not(hm):
    watcher(hm, NOON + timedelta(days=2))
    hm.outbox.error = mailer.MailLater("503")
    got = run(hm, NOON)
    assert (got.sent, got.failed) == (0, 1) and log(hm) == []  # the claim is given back
    hm.outbox.error = None
    assert run(hm, NOON + timedelta(minutes=15)).sent == 1

    watcher(hm, NOON + timedelta(days=2), user="u2", email="bad@example.com")
    hm.outbox.error = mailer.MailRefused(422)
    assert run(hm, NOON + timedelta(minutes=30)).failed == 1
    hm.outbox.error = None
    assert run(hm, NOON + timedelta(minutes=45)).sent == 0
    assert log(hm) == [("u1", "trial_ending", "sent"), ("u2", "trial_ending", "failed")]


def test_a_send_cut_off_midway_is_tried_again(hm):
    watcher(hm, NOON + timedelta(days=2))
    call(hm, lambda s: _add(s, AccountEmail(user_id="u1", kind="trial_ending",
                                            key="trial_ending", status="pending",
                                            sent_at=NOON - timedelta(minutes=5))))
    assert run(hm, NOON).sent == 0  # another run may still be sending it
    assert run(hm, NOON + timedelta(minutes=11)).sent == 1
    assert log(hm) == [("u1", "trial_ending", "sent")]


async def _add(s, row) -> None:
    s.add(row)


def test_every_message_has_its_own_idempotency_key(hm):
    sign_in(hm, first=True)
    paid(hm)
    keys = [m.idempotency_key for m in hm.outbox.sent]
    assert len(set(keys)) == 2 and all(k.startswith("holt-account-") for k in keys)


# --- off --------------------------------------------------------------------------------------


def test_nothing_is_sent_with_the_switch_off(make_harness):
    h = make_harness(HOLT_PR_WATCH=True, RESEND_API_KEY="re_test")
    h.svc.mailer = h.outbox = FakeMailer()
    assert sign_in(h, first=True).status_code == 204
    watcher(h, now() + timedelta(days=1), user="u2")
    paid(h, user="u3")
    assert run(h).skipped == "off"
    assert h.outbox.sent == [] and log(h) == []
    # The address is kept, so the emails have somewhere to go once they're on.
    assert h.get("/v1/me/emails", user="u1").json() == {"email": YOU, "product_emails": True}


def test_nothing_is_sent_without_the_provider_key(make_harness):
    h = make_harness(HOLT_ACCOUNT_EMAILS=True, HOLT_PR_WATCH=True)
    assert h.svc.mailer is None
    sign_in(h, first=True)
    paid(h)
    assert run(h).skipped == "no_mailer" and log(h) == []


# --- the lab page and the samples -------------------------------------------------------------


def test_the_lab_serves_every_email_outside_production(make_harness):
    h = make_harness(HOLT_ENV="staging")
    emails = h.get("/v1/lab/emails").json()["emails"]
    assert [e["kind"] for e in emails] == [
        "welcome", "receipt", "trial_ending", "trial_ending", "trial_ended", "trial_ended",
        "pass_ending", "pass_ending", "alert_now", "alert_now", "alert_daily"]
    for e in emails:
        assert e["html"].startswith("<!doctype html>") and e["text"] and e["subject"]
        assert "(=^•ω•^=)" in e["html"] and "<img" not in e["html"]
    assert make_harness(HOLT_ENV="production").get("/v1/lab/emails").status_code == 404
    assert h.client.get("/v1/lab/emails").status_code == 401  # the internal key


def _said(html: str) -> str:
    """An HTML part's words: tags and the hidden preview line's padding out."""
    body = html.split("</head>")[1]
    for entity, char in (("&#847;&zwnj;&nbsp;", ""), ("&nbsp;", " "), ("&amp;", "&"),
                         ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
        body = body.replace(entity, char)
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())


def test_the_samples_are_the_owners_text(make_harness):
    """The owner reviews the samples: email_samples.md is their text, with
    each sample's subject, preview line and text part."""
    written = (Path(__file__).parent / "email_samples.md").read_text(encoding="utf-8")
    blocks = re.findall(
        r"^## \d+\. ([^\n]+?)  \(`\w+`\)\n\n\*\*Subject:\*\* ([^\n]+)\n\n"
        r"\*\*Preview line:\*\* ([^\n]+)\n\n\*\*Body:\*\*\n\n```text\n(.+?)\n```$",
        written, re.M | re.S)
    got = [(e.name, e.subject, e.preheader, e.text)
           for e in account_mail.samples(make_harness().svc)]
    assert len(blocks) == 11 and [name for name, *_ in blocks] == [name for name, *_ in got]
    for want, have in zip(blocks, got, strict=True):
        assert have == want, want[0]


def test_the_html_and_the_text_say_the_same(make_harness):
    for e in account_mail.samples(make_harness().svc):
        said = _said(e.html)
        assert e.preheader in said, e.name
        for line in e.text.replace("`", "").splitlines():
            # A link is its address in the text and its words in the HTML.
            line = re.sub(r" ?https://\S+", "", line)
            # The one line that is a button's words there: "get another pass →".
            if line == "If you want another pass:":
                assert "get another pass →" in said
                continue
            for part in re.split(r"(?<=[.?:,]) | · ", line):
                assert part.rstrip(".:?,-").lower() in said.lower(), (e.name, line)


def test_the_welcome_has_alerts_while_pr_watch_is_on():
    f = account_email.Frame(YOU, "https://githolt.com", "https://githolt.com/alerts/unsubscribe?t=x")
    out = account_email.welcome_email(f, "https://githolt.com", "https://githolt.com/find",
                                      "https://githolt.com/settings/alerts")
    assert ("Turn on PR alerts: we'll let you know when a maintainer replies to one of your "
            "PRs.\nhttps://githolt.com/settings/alerts") in out.text
    # Addresses are in backticks in the text only.
    assert "replace `github.com` with `githolt.com` in its address." in out.text
    assert "replace github.com with githolt.com in its address." in out.html
    assert "`" not in out.html


def test_a_receipt_says_only_what_the_pass_gives():
    f = account_email.Frame(YOU, "https://githolt.com")
    kw = dict(pass_name="1 month", amount="₹99", paid_on="1 Oct", payment="pay_1",
              plan_url="https://githolt.com", alerts_url=None,
              refunds_url="https://githolt.com/refunds")
    forever = account_email.receipt_email(f, until=None, merge_plans=30, alerts=False, **kw)
    assert forever.preheader == "Your Pro pass is live. Here's what you get."
    assert "Your pass is live.\n\nHere's what you've got:" in forever.text
    assert "PR alerts" not in forever.text + forever.html
    bare = account_email.receipt_email(f, until="31 October", merge_plans=None, alerts=False,
                                       **kw)
    assert bare.preheader == "Your Pro pass is live through 31 October."
    assert "Here's what you've got" not in bare.text + bare.html
    assert "Open Holt: https://githolt.com" in bare.text


def test_text_from_outside_is_escaped():
    f = account_email.Frame('a"<b>@example.com', "https://githolt.com", "https://x/?a=1&b=2")
    out = account_email.receipt_email(
        f, pass_name="<i>1 month</i>", amount="₹99", paid_on="1 Oct", until="31 October",
        merge_plans=30, alerts=True, payment="pay_<x>", plan_url="https://githolt.com",
        alerts_url=None, refunds_url="https://githolt.com/refunds")
    assert "<i>" not in out.html and "pay_<x>" not in out.html
    assert "&lt;i&gt;1 month&lt;/i&gt;" in out.html and "a&quot;&lt;b&gt;@example.com" in out.html


def test_money():
    assert account_mail.money(9900, "INR") == "₹99"
    assert account_mail.money(24950, "INR") == "₹249.50"
    assert account_mail.money(123400, "INR") == "₹1,234"
    assert account_mail.money(700, "USD") == "$7"
    assert account_mail.money(1550, "USD") == "$15.50"
    assert account_mail.money(700, "EUR") == "7 EUR"


def test_samples_go_to_the_users_own_address_and_never_in_production(make_harness):
    h = make_harness(HOLT_ENV="staging", HOLT_PR_WATCH=True)
    h.svc.mailer = h.outbox = FakeMailer()
    send = lambda user: h.client.portal.call(  # noqa: E731
        lambda: account_mail.send_samples(h.svc, user))
    with pytest.raises(ValueError, match="no sign-in address"):
        send("u1")
    sign_in(h)
    assert send("u1") == 11
    assert {m.to for m in h.outbox.sent} == {YOU} and log(h) == []
    prod = make_harness(HOLT_ENV="production")
    prod.svc.mailer = FakeMailer()
    with pytest.raises(ValueError, match="production"):
        prod.client.portal.call(lambda: account_mail.send_samples(prod.svc, "u1"))
