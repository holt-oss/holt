"""PR watch's emails (mailer.py, alert_email.py): which alerts go out when
(the pure `plan`), what the two emails look like, and sending through a fake
provider. No network."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from holt_server import alert_email, alerts, alerts_api, mailer
from holt_server.db import Alert, AlertEmail, AlertSettings, User
from holt_server.mailer import Pending, Prefs, Queue
from sqlalchemy import select

from test_server_contributions import call

CLICK = ("pallets/click", 2811)
P5 = ("processing/p5.js", 7120)


def ist(hour: int, minute: int = 0, day: int = 1) -> datetime:
    """A time on a day in October 2026, said in India's clock (UTC+5:30)."""
    return (datetime(2026, 10, day, hour, minute, tzinfo=UTC)
            - timedelta(hours=5, minutes=30))


def prefs(**kw) -> Prefs:
    values = dict(user_id="u1", tz="Asia/Kolkata", last_daily_on=date(2026, 10, 1))
    values.update(kw)
    return Prefs(**values)


def alert(id_: int, kind: str, at: datetime, pr=CLICK) -> Pending:
    return Pending(id_, kind, pr, at)


def one(q: Queue, at: datetime):
    return mailer.plan_user(q, at)


# --- right away ---------------------------------------------------------------------------


def test_your_turn_goes_out_right_away_and_the_rest_waits():
    at = ist(14)
    q = Queue(prefs(), (alert(1, "changes", at - timedelta(minutes=10)),
                        alert(2, "late_reply", at - timedelta(minutes=10), P5)))
    email, done = one(q, at)
    assert (email.kind, email.alert_ids, done) == ("now", (1,), None)


def test_alerts_from_one_check_wait_five_minutes_and_go_together():
    at = ist(14)
    fresh = Queue(prefs(), (alert(1, "reply", at - timedelta(minutes=3)),))
    assert one(fresh, at) == (None, None)
    both = Queue(prefs(), (alert(1, "reply", at - timedelta(minutes=6)),
                           alert(2, "changes", at - timedelta(minutes=6), P5)))
    email, _ = one(both, at)
    assert email.alert_ids == (1, 2)  # one email, not two


def test_at_most_one_right_away_email_per_pull_request_a_day():
    at = ist(15)
    q = Queue(prefs(), (alert(3, "reply", at - timedelta(minutes=10)),
                        alert(4, "reply", at - timedelta(minutes=10), P5)),
              emailed=frozenset({CLICK}))
    email, _ = one(q, at)
    assert email.alert_ids == (4,)  # click was emailed today: its second one waits
    # ...for the next daily email, which takes it.
    tomorrow = ist(8, 5, day=2)
    email, _ = one(Queue(prefs(), (alert(3, "reply", at - timedelta(minutes=10)),),
                         emailed=frozenset({CLICK})), tomorrow)
    assert (email.kind, email.alert_ids) == ("daily", (3,))


def test_only_the_daily_email_sends_nothing_right_away():
    at = ist(14)
    q = Queue(prefs(email_mode="daily"), (alert(1, "changes", at - timedelta(minutes=10)),))
    assert one(q, at) == (None, None)


def test_everything_as_it_happens():
    at = ist(14)
    q = Queue(prefs(email_mode="all"), (alert(1, "merged", at - timedelta(minutes=10)),
                                        alert(2, "late_reply", at - timedelta(minutes=10), P5)))
    email, _ = one(q, at)
    assert (email.kind, email.alert_ids) == ("now", (1, 2))


def test_email_switched_off_sends_nothing():
    at = ist(14)
    q = Queue(prefs(email_on=False, last_daily_on=None),
              (alert(1, "changes", at - timedelta(minutes=10)),))
    assert one(q, at) == (None, None)


# --- quiet hours and the daily email --------------------------------------------------------


@pytest.mark.parametrize("at", [ist(22), ist(23, 30), ist(2), ist(7, 59)])
def test_no_email_between_22_and_8(at):
    q = Queue(prefs(last_daily_on=date(2026, 9, 30)),
              (alert(1, "changes", at - timedelta(minutes=10)),))
    assert one(q, at) == (None, None)


def test_a_night_time_your_turn_goes_in_the_8_oclock_email():
    night = ist(23, 30, day=1)
    q = Queue(prefs(), (alert(1, "changes", night), alert(2, "merged", night, P5)))
    assert one(q, ist(7, 55, day=2)) == (None, None)
    email, done = one(q, ist(8, 0, day=2))
    # One email at 8:00 with both, not a "your turn" email and a daily one.
    assert (email.kind, email.alert_ids, email.local_date) == ("daily", (1, 2), date(2026, 10, 2))
    assert done is None


def test_the_daily_email_runs_once_a_day():
    at = ist(8, 5, day=2)
    q = Queue(prefs(last_daily_on=date(2026, 10, 2)),
              (alert(2, "late_reply", at - timedelta(hours=3)),))
    assert one(q, at) == (None, None)  # done today; "late_reply" isn't sent right away


def test_the_daily_email_is_skipped_when_empty():
    email, done = one(Queue(prefs()), ist(8, 5, day=2))
    assert email is None
    assert done == date(2026, 10, 2)  # marked done, so it isn't asked again today


def test_the_daily_email_holds_the_last_36_hours():
    at = ist(8, 5, day=3)
    q = Queue(prefs(), (alert(1, "merged", at - timedelta(hours=40)),
                        alert(2, "closed", at - timedelta(hours=30), P5)))
    email, _ = one(q, at)
    assert email.alert_ids == (2,)  # the older one stays on the bell


@pytest.mark.parametrize(("tz", "before", "after"), [
    ("Asia/Kolkata", datetime(2026, 10, 2, 2, 29, tzinfo=UTC),
     datetime(2026, 10, 2, 2, 30, tzinfo=UTC)),
    # New York: daylight time (UTC-4) in October, standard time (UTC-5) after 1 November.
    ("America/New_York", datetime(2026, 10, 2, 11, 59, tzinfo=UTC),
     datetime(2026, 10, 2, 12, 0, tzinfo=UTC)),
    ("America/New_York", datetime(2026, 11, 2, 12, 59, tzinfo=UTC),
     datetime(2026, 11, 2, 13, 0, tzinfo=UTC)),
    # London: summer time (UTC+1) until 25 October, then UTC.
    ("Europe/London", datetime(2026, 10, 2, 6, 59, tzinfo=UTC),
     datetime(2026, 10, 2, 7, 0, tzinfo=UTC)),
    ("Europe/London", datetime(2026, 10, 26, 7, 59, tzinfo=UTC),
     datetime(2026, 10, 26, 8, 0, tzinfo=UTC)),
])
def test_8_oclock_is_the_users_own(tz, before, after):
    q = Queue(prefs(tz=tz, last_daily_on=None), (alert(1, "merged", before - timedelta(hours=5)),))
    assert one(q, before) == (None, None)
    email, _ = one(q, after)
    assert email.kind == "daily" and email.local_date == after.date()


def test_an_unknown_time_zone_falls_back_to_utc():
    q = Queue(prefs(tz="Mars/Olympus", last_daily_on=None),
              (alert(1, "merged", datetime(2026, 10, 2, 3, tzinfo=UTC)),))
    assert one(q, datetime(2026, 10, 2, 7, 59, tzinfo=UTC)) == (None, None)
    assert one(q, datetime(2026, 10, 2, 8, 0, tzinfo=UTC))[0].kind == "daily"


# --- the provider's daily limit ---------------------------------------------------------------


def test_your_turn_goes_first_when_the_daily_limit_is_near():
    at = ist(8, 5, day=2)
    waiting = Queue(prefs(user_id="daily", last_daily_on=date(2026, 10, 1)),
                    (alert(1, "merged", at - timedelta(hours=3)),))
    turn = Queue(prefs(user_id="turn", last_daily_on=date(2026, 10, 2)),
                 (alert(2, "changes", at - timedelta(minutes=10), P5),))
    empty = Queue(prefs(user_id="empty", last_daily_on=date(2026, 10, 1)))
    got = mailer.plan([waiting, turn, empty], at, budget=5)
    assert [(e.user_id, e.kind) for e in got.emails] == [("turn", "now"), ("daily", "daily")]
    assert got.daily_empty == (("empty", date(2026, 10, 2)),) and got.held == 0
    tight = mailer.plan([waiting, turn, empty], at, budget=1)
    assert [(e.user_id, e.kind) for e in tight.emails] == [("turn", "now")]
    assert tight.held == 1  # the daily email waits; it isn't marked done
    assert mailer.plan([waiting, turn], at, budget=-3).emails == ()


# --- the two emails -----------------------------------------------------------------------


FRAME = alert_email.EmailFrame(
    to="you@example.com", status="Alerts until 14 Oct. Your turn right away, the rest at 8:00.",
    prs_url="https://githolt.com/me/contributions",
    settings_url="https://githolt.com/settings/alerts",
    unsubscribe_url="https://githolt.com/alerts/unsubscribe?t=abc&x=1",
    home_url="https://githolt.com")


def item(kind: str, pr: str, title: str, **facts) -> alert_email.EmailAlert:
    repo, number = pr.split(" #")
    return alert_email.EmailAlert(kind, repo, int(number), title,
                                  f"https://github.com/{repo}/pull/{number}",
                                  f"https://githolt.com/{repo}", facts)


TURN = [
    item("changes", "pallets/click #2811", 'Fix <b>shell</b> completion & "nested" groups',
         who="mkoval"),
    item("reply", "processing/p5.js #7120", "Add describe() to the textToPoints reference",
         who="lead"),
]
DAILY = [
    item("late_reply", "processing/p5.js #7120", "Add describe() to the textToPoints reference",
         days=6, slow_hours=96),
    item("stale_soon", "EbookFoundation/free-programming-books #11020",
         "Add Rust books in Hindi", quiet=25, close=30),
    item("approved", "dotnet/efcore #3310", "Translate DateOnly.DayNumber on SQLite",
         who="jrios"),
    item("closed", "moment/moment #6120", "Add an Odia locale"),
]


def test_the_emails_are_built_from_the_shared_template():
    """Both come from email_kit.py: the band with the wordmark, the tone's
    rule, a card per alert, and the footer."""
    one = alert_email.your_turn_email(TURN[:1], FRAME).html
    two = alert_email.your_turn_email(TURN, FRAME).html
    daily = alert_email.daily_email(DAILY, FRAME, "Wednesday 1 October").html
    for html in (one, two, daily):
        assert html.startswith("<!doctype html>") and "(=^•ω•^=)" in html
        assert "<img" not in html and "<script" not in html
        assert 'href="https://githolt.com/settings/alerts"' in html
        assert "Sent to you@example.com by Holt, githolt.com" in html
    # One solid button an email: the pull request's when there is one alert,
    # "see all" when there are several (theirs are outlined).
    assert one.count('class="h-btn"') == 1 and "see all your pull requests" not in one
    assert two.count('class="h-btn"') == 1 and two.count('class="h-ghost"') == 2
    assert daily.count('class="h-ghost"') == 4 and "Wednesday 1 October" in daily
    # The rule under the band takes the email's tone, each card its alert's.
    assert "h-tone-turn" in one and "h-tone-late" in daily
    for tone in ("late", "stale", "good", "done"):
        assert f"h-rule-{tone}" in daily.split("</head>")[1]


def test_pull_request_titles_are_escaped():
    html = alert_email.your_turn_email(TURN[:1], FRAME).html
    assert "<b>shell</b>" not in html
    assert "Fix &lt;b&gt;shell&lt;/b&gt; completion &amp; &quot;nested&quot; groups" in html
    assert 'href="https://githolt.com/alerts/unsubscribe?t=abc&amp;x=1"' in html
    hostile = item("reply", "a/b #1", '"><script>alert(1)</script><img src=x onerror=alert(2)>',
                   who="x")
    html = alert_email.your_turn_email([hostile], FRAME).html
    assert "<script>" not in html and "<img" not in html


def test_your_turn_on_one_pull_request():
    one = alert_email.your_turn_email(TURN[:1], FRAME)
    # The news is the subject; the heading says it without the pull request,
    # which the card under it shows.
    assert one.subject == "@mkoval asked for changes on click #2811"
    assert one.preheader == 'Your turn. Fix <b>shell</b> completion & "nested" groups'
    assert one.text.startswith(
        "@mkoval asked for changes on your PR.\n\nLooks like it's your turn:\n"
        'pallets/click #2811 · Fix <b>shell</b> completion & "nested" groups\n\n'
        "Open the PR: https://github.com/pallets/click/pull/2811\n")
    for said in ("@mkoval asked for changes on your PR.", "Looks like it's your turn:"):
        assert said in one.html
    reply = alert_email.your_turn_email(TURN[1:], FRAME)
    assert reply.subject == "@lead replied on p5.js #7120"
    assert reply.text.startswith("@lead replied on your PR.\n\nLooks like it's your turn:\n")
    unnamed = alert_email.your_turn_email([item("reply", "a/b #1", "T")], FRAME)
    assert unnamed.subject == "A reviewer replied on b #1"
    assert unnamed.text.startswith("A reviewer replied on your PR.\n")


def test_your_turn_on_two_pull_requests():
    two = alert_email.your_turn_email(TURN, FRAME)
    assert two.subject == "2 of your PRs need a look"
    assert two.preheader == (
        "Two maintainers replied. One asked for changes, and one left a reply.")
    assert two.text.startswith(
        "Two maintainers replied to your pull requests.\n\n"
        "First up, @mkoval asked for changes:\n"
        'pallets/click #2811 · Fix <b>shell</b> completion & "nested" groups\n'
        "Open the PR: https://github.com/pallets/click/pull/2811\n"
        "Holt's report: https://githolt.com/pallets/click\n\n"
        "And @lead replied here:\n"
        "processing/p5.js #7120 · Add describe() to the textToPoints reference\n")
    for said in ("Two maintainers replied to your pull requests.",
                 "First up, @mkoval asked for changes:", "And @lead replied here:"):
        assert said in two.html
    assert "Your turn." not in two.html + two.text.split("--")[0]
    # The other way round, and both the same.
    back = alert_email.your_turn_email(TURN[::-1], FRAME)
    assert back.preheader == (
        "Two maintainers replied. One left a reply, and one asked for changes.")
    assert "First up, @lead replied:" in back.text
    assert "And @mkoval asked for changes here:" in back.text
    both = alert_email.your_turn_email(
        [TURN[0], item("changes", "a/b #1", "T")], FRAME)
    assert both.preheader == "Two maintainers replied. Both asked for changes."
    assert "And a reviewer asked for changes here:" in both.text
    replies = alert_email.your_turn_email([TURN[1], item("reply", "a/b #1", "T")], FRAME)
    assert replies.preheader == "Two maintainers replied. Both left a reply."
    # One person on both isn't "two maintainers".
    same = alert_email.your_turn_email(
        [TURN[0], item("reply", "a/b #1", "T", who="mkoval")], FRAME)
    assert same.text.startswith("@mkoval replied to two of your pull requests.\n")
    assert same.preheader == ("@mkoval replied to two of your pull requests. "
                              "One asked for changes, and one left a reply.")


def test_your_turn_on_three_or_more_pull_requests():
    third = item("changes", "a/b #1", "T")
    three = alert_email.your_turn_email([*TURN, third], FRAME)
    assert three.subject == "3 of your PRs need a look"
    assert three.preheader == ("Maintainers replied to three of your pull requests. "
                               "Two asked for changes, and one left a reply.")
    assert three.text.startswith(
        "Maintainers replied to three of your pull requests.\n\n"
        "@mkoval asked for changes:\npallets/click #2811 · ")
    # A plain list: no "First up" or "And".
    assert "\n\n@lead replied:\nprocessing/p5.js #7120 · " in three.text
    assert "\n\nA reviewer asked for changes:\na/b #1 · T\n" in three.text
    assert "First up" not in three.text + three.html and "replied here" not in three.text
    for said in ("@lead replied:", "A reviewer asked for changes:"):
        assert said in three.html
    assert three.html.count('class="h-ghost"') == 3 and three.html.count('class="h-btn"') == 1
    alike = alert_email.your_turn_email([TURN[0]] + [third] * 3, FRAME)
    assert alike.subject == "4 of your PRs need a look"
    assert alike.preheader == ("Maintainers replied to four of your pull requests. "
                               "All four asked for changes.")
    many = alert_email.your_turn_email(TURN * 6, FRAME)
    assert many.subject == "12 of your PRs need a look"
    assert many.preheader == ("Maintainers replied to 12 of your pull requests. "
                              "Six asked for changes, and six left a reply.")


def test_the_daily_email():
    daily = alert_email.daily_email(DAILY, FRAME, "Thursday 1 October")
    assert daily.subject == "Here's what happened on your PRs today"
    assert daily.preheader == (
        "4 updates: one waiting, one getting close to stale, one approved, and one closed.")
    assert daily.text.startswith(
        "Here's where your pull requests stand, Thursday 1 October.\n\n"
        "p5.js #7120 is on day 6 with no reply yet. Most PRs here get one within 4 days.\n"
        "processing/p5.js #7120 · Add describe() to the textToPoints reference\n"
        "Open the PR: https://github.com/processing/p5.js/pull/7120\n"
        "Holt's report: https://githolt.com/processing/p5.js\n\n"
        "free-programming-books #11020 has been quiet for 25 days. "
        "The bot closes PRs here after 30.\n")
    assert "\nefcore #3310 was approved by @jrios.\n" in daily.text
    assert "\nmoment #6120 was closed without merging.\n" in daily.text
    assert daily.text.endswith(
        "Stop these emails: https://githolt.com/alerts/unsubscribe?t=abc&x=1")
    # The short name leads in bold in the HTML, and plainly in the text.
    assert "*" not in daily.text
    assert ('<strong style="font-weight:600;">p5.js #7120</strong> is on day 6 with no reply '
            "yet. Most PRs here get one within 4 days.") in daily.html
    assert ('<strong style="font-weight:600;">efcore #3310</strong> was approved by @jrios.'
            in daily.html)
    assert "Here's where your pull requests stand</h1>" in daily.html
    one = alert_email.daily_email(DAILY[:1], FRAME, "Thursday 1 October")
    assert one.subject == daily.subject and one.preheader == "1 update: one waiting."


def test_the_daily_email_says_each_kind_its_own_way():
    """Not the bell's line (alerts.line): the pull request's short name leads."""
    def said(kind: str, **facts) -> str:
        email = alert_email.daily_email([item(kind, "a/b #1", "T", **facts)], FRAME, "x")
        return email.text.splitlines()[2]

    assert said("merged") == "b #1 was merged."
    assert said("approved") == "b #1 was approved."
    assert said("late_merge", days=12, slow_hours=168) == (
        "b #1 is on day 12. Most merged PRs here land within 7 days.")
    assert said("late_reply", days=2, slow_hours=24) == (
        "b #1 is on day 2 with no reply yet. Most PRs here get one within a day.")
    assert said("stale_soon", quiet=1, close=6) == (
        "b #1 has been quiet for 1 day. The bot closes PRs here after 6.")
    assert said("changes", who="lead") == "b #1 is waiting on you. @lead asked for changes."
    assert said("reply") == "b #1 is waiting on you. A reviewer replied."
    assert said("new_kind") == "b #1 has an update."


def test_the_daily_preview_line_counts_each_kind():
    def preview(*kinds: str) -> str:
        found = [item(kind, f"a/b #{i}", "T") for i, kind in enumerate(kinds)]
        return alert_email.daily_email(found, FRAME, "x").preheader

    assert preview("merged") == "1 update: one merged."
    assert preview("late_reply", "merged") == "2 updates: one waiting and one merged."
    assert preview("late_reply", "late_reply", "late_reply") == "3 updates: three waiting."
    # Several of one kind are counted once, where the first of them is.
    assert preview("closed", "late_merge", "closed", "merged", "late_merge", "closed") == (
        "6 updates: three closed, two waiting on a merge, and one merged.")
    assert preview("changes", "reply", "approved") == (
        "3 updates: one needing changes, one with a new reply, and one approved.")
    assert preview("stale_soon", "stale_soon") == "2 updates: two getting close to stale."
    assert preview(*["merged"] * 11, "new_kind") == "12 updates: 11 merged and one changed."


def test_the_footer_says_when_alerts_end():
    tz = mailer.zone("Asia/Kolkata")
    at = datetime(2026, 10, 1, 6, tzinfo=UTC)
    ends = datetime(2026, 10, 14, 9, tzinfo=UTC)
    trial = alerts.Access("trial", ends)
    assert mailer.status_line(trial, "turn", at, tz) == (
        "Alerts until 14 Oct. Your turn right away, the rest at 8:00.")
    assert mailer.status_line(trial, "all", ends - timedelta(hours=20), tz) == (
        "Alerts stop on 14 Oct. Everything as it happens.")
    assert mailer.status_line(alerts.Access("pro"), "daily", at, tz) == (
        "One email a day, at 8:00.")


# --- the provider -------------------------------------------------------------------------


MESSAGE = mailer.Message(to="you@example.com", subject="s", html="<p>h</p>", text="t",
                         headers={"List-Unsubscribe": "<https://githolt.com/x>"},
                         idempotency_key="key-1")


def resend(handler) -> mailer.Resend:
    return mailer.Resend(httpx.Client(transport=httpx.MockTransport(handler)), "re_secret",
                         "Holt <alerts@githolt.com>", "hello@githolt.com")


def test_resend_gets_the_message_and_the_key():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "email-123"})

    assert resend(handler).send(MESSAGE) == "email-123"
    [req] = seen
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_secret"
    assert req.headers["idempotency-key"] == "key-1"
    body = json.loads(req.content)
    assert body == {"from": "Holt <alerts@githolt.com>", "to": ["you@example.com"],
                    "subject": "s", "html": "<p>h</p>", "text": "t",
                    "reply_to": "hello@githolt.com",
                    "headers": {"List-Unsubscribe": "<https://githolt.com/x>"}}


def test_resend_trouble_is_retried_and_a_refusal_is_not():
    # Busy, down, or the key or sending domain refused: the setup's problem,
    # not this message's, so it is tried again once that is fixed.
    for status in (503, 429, 401, 403, 409):
        with pytest.raises(mailer.MailLater):
            resend(lambda req, status=status: httpx.Response(status)).send(MESSAGE)

    def down(req):
        raise httpx.ConnectError("no route")
    with pytest.raises(mailer.MailLater):
        resend(down).send(MESSAGE)
    with pytest.raises(mailer.MailRefused) as refused:
        resend(lambda req: httpx.Response(422, json={"message": "bad"})).send(MESSAGE)
    assert refused.value.status == 422


def test_no_mailer_without_the_key(make_harness):
    h = make_harness()
    assert h.svc.mailer is None
    with_key = make_harness(RESEND_API_KEY="re_test", HOLT_PR_WATCH=True)
    assert isinstance(with_key.svc.mailer, mailer.Resend)
    # Unsubscribe links are made with the server's secret: no secret, no email.
    assert mailer.build(make_harness(RESEND_API_KEY="re_test", HOLT_SECRET_KEY="").svc.settings,
                        h.svc.http) is None


# --- a run --------------------------------------------------------------------------------


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[mailer.Message] = []
        self.error: Exception | None = None

    def send(self, message: mailer.Message) -> str:
        if self.error is not None:
            raise self.error
        self.sent.append(message)
        return f"email-{len(self.sent)}"


@pytest.fixture
def hm(make_harness):
    h = make_harness(HOLT_PR_WATCH=True)
    h.svc.mailer = h.outbox = FakeMailer()
    return h


def seed(h, at: datetime, *found: tuple[str, str, int, timedelta], user="u1", mode="turn",
         last_daily=date(2026, 10, 1), trial_days=10, email="you@example.com") -> None:
    """A user with alerts on and the given (kind, repo, number, age) alerts."""
    async def go(s):
        s.add(User(id=user, plan="free", alerts_trial_ends_at=at + timedelta(days=trial_days)))
        row = alerts.new_settings(h.svc, user)
        row.enabled, row.email, row.email_mode = True, email, mode
        row.tz, row.last_daily_on = "Asia/Kolkata", last_daily
        s.add(row)
        for kind, repo, number, age in found:
            p = alerts.Pr(repo=repo, repo_key=repo.lower(), number=number,
                          title=f"Title of {number} <i>", state="open", created_at=at,
                          url=f"https://github.com/{repo}/pull/{number}")
            facts = {"who": "lead"} if kind in alerts.YOUR_TURN else {}
            await alerts.record(s, user, p, [alerts.Found(kind, facts, at - age)], at - age)
    call(h, go)


def run(h, at):
    async def go():
        return await mailer.run(h.svc, at)
    return h.client.portal.call(go)


def stored(h, model):
    async def go(s):
        return (await s.execute(select(model).order_by(model.id))).scalars().all()
    return call(h, go)


def test_a_run_sends_your_turn_and_records_it(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)),
         ("merged", "moment/moment", 6120, timedelta(minutes=10)))
    got = run(hm, at)
    assert (got.sent, got.failed, got.held) == (1, 0, 0)
    [msg] = hm.outbox.sent
    assert msg.to == "you@example.com"
    assert msg.subject == "@lead asked for changes on click #2811"
    assert msg.text.startswith("@lead asked for changes on your PR.\n")
    assert "pallets/click #2811 · " in msg.text
    assert "Title of 2811 &lt;i&gt;" in msg.html and "moment" not in msg.html
    assert "Alerts until 11 Oct. Your turn right away, the rest at 8:00." in msg.text
    # One-click unsubscribe (RFC 8058), and the same token in the footer link.
    token = msg.headers["List-Unsubscribe"].removeprefix(
        "<https://githolt.com/api/alerts/unsubscribe?t=").removesuffix(">")
    assert msg.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert f"https://githolt.com/alerts/unsubscribe?t={token}" in msg.text
    [settings] = call(hm, lambda s: _settings(s))
    assert alerts.token_hash(token) == settings.unsubscribe_hash

    turn, merged = stored(hm, Alert)
    assert (turn.email_via, merged.email_via) == ("now", None)
    [record] = stored(hm, AlertEmail)
    assert (record.kind, record.alert_ids, record.provider_id, record.status) == (
        "now", [turn.id], "email-1", "sent")
    # The next run has nothing left to send right away.
    assert run(hm, at + timedelta(minutes=5)).sent == 0
    assert len(hm.outbox.sent) == 1


async def _settings(s):
    return (await s.execute(select(AlertSettings))).scalars().all()


def test_a_second_your_turn_on_the_same_pull_request_waits_for_the_daily_email(hm):
    at = ist(14)
    seed(hm, at, ("reply", "pallets/click", 2811, timedelta(minutes=10)))
    assert run(hm, at).sent == 1

    async def again(s):
        p = alerts.Pr(repo="pallets/click", repo_key="pallets/click", number=2811, title="t",
                      url="https://github.com/pallets/click/pull/2811", state="open",
                      created_at=at)
        later = at + timedelta(hours=2)
        await alerts.record(s, "u1", p, [alerts.Found("changes", {"who": "lead"}, later)], later)
    call(hm, again)
    assert run(hm, at + timedelta(hours=3)).sent == 0  # one email per pull request a day
    got = run(hm, ist(8, 5, day=2))
    assert got.sent == 1
    assert [a.email_via for a in stored(hm, Alert)] == ["now", "daily"]
    assert [e.kind for e in stored(hm, AlertEmail)] == ["now", "daily"]
    [settings] = call(hm, _settings)
    assert settings.last_daily_on == date(2026, 10, 2)


def test_the_daily_email_carries_the_rest(hm):
    at = ist(8, 5, day=2)
    seed(hm, at, ("late_reply", "processing/p5.js", 7120, timedelta(hours=5)),
         ("merged", "moment/moment", 6120, timedelta(hours=3)))
    assert run(hm, at).sent == 1
    [msg] = hm.outbox.sent
    assert msg.subject == "Here's what happened on your PRs today"
    assert msg.text.startswith("Here's where your pull requests stand, Friday 2 October.\n")
    assert "\nmoment #6120 was merged.\n" in msg.text
    assert all(a.email_via == "daily" for a in stored(hm, Alert))


def test_an_empty_daily_email_is_skipped_and_marked_done(hm):
    at = ist(8, 5, day=2)
    seed(hm, at)
    assert run(hm, at).sent == 0 and hm.outbox.sent == []
    [settings] = call(hm, _settings)
    assert settings.last_daily_on == date(2026, 10, 2)
    assert stored(hm, AlertEmail) == []


def test_without_a_provider_key_nothing_is_sent_and_alerts_stay_on_the_bell(make_harness,
                                                                           caplog, monkeypatch):
    h = make_harness(HOLT_PR_WATCH=True)  # no RESEND_API_KEY
    at = ist(14)
    monkeypatch.setattr(alerts, "now", lambda: at)  # the bell asks if the free days still run
    seed(h, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    mailer._said_off = False
    with caplog.at_level(logging.INFO, logger="holt_server.mailer"):
        assert run(h, at).skipped == "off"
        assert run(h, at + timedelta(minutes=5)).skipped == "off"
    said = [r for r in caplog.records if "alert emails are off" in r.getMessage()]
    assert len(said) == 1  # logged once, not every five minutes
    [alert_] = stored(h, Alert)
    assert alert_.email_via is None and alert_.emailed_at is None
    r = h.get("/v1/me/alerts", user="u1").json()
    assert r["unread"] == 1 and r["items"][0]["text"] == (
        "Your turn. @lead asked for changes on click #2811.")


def test_nothing_is_sent_once_access_has_ended(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)), trial_days=-1)
    assert run(hm, at).sent == 0 and hm.outbox.sent == []


def test_no_address_no_email(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)), email=None)
    assert run(hm, at).sent == 0 and hm.outbox.sent == []


def test_a_busy_provider_is_tried_again_next_run(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    hm.outbox.error = mailer.MailLater("503")
    assert (run(hm, at).sent, run(hm, at).failed) == (0, 1)
    assert stored(hm, AlertEmail) == [] and stored(hm, Alert)[0].emailed_at is None
    hm.outbox.error = None
    assert run(hm, at + timedelta(minutes=5)).sent == 1


def test_one_failing_email_doesnt_block_the_others(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    seed(hm, at, ("reply", "moment/moment", 6120, timedelta(minutes=10)), user="u2",
         email="two@example.com")
    real = hm.outbox.send

    def send(message):
        if message.to == "you@example.com":
            raise RuntimeError("boom")
        return real(message)
    hm.outbox.send = send
    got = run(hm, at)
    assert (got.sent, got.failed) == (1, 1)
    assert [m.to for m in hm.outbox.sent] == ["two@example.com"]


def test_a_rotated_secret_still_gives_a_working_unsubscribe_link(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    hm.svc.settings.secret_key = "a new passphrase"
    assert run(hm, at).sent == 1
    token = hm.outbox.sent[0].headers["List-Unsubscribe"].split("?t=")[1].rstrip(">")
    r = hm.post("/v1/alerts/unsubscribe", {"token": token})
    assert r.status_code == 200 and r.json() == {"email_on": False, "emails": "alerts"}


def test_turning_email_back_on_waits_for_the_next_8_oclock(hm, monkeypatch):
    at = ist(15, day=3)
    monkeypatch.setattr(alerts_api, "now", lambda: at)
    seed(hm, at, ("merged", "moment/moment", 6120, timedelta(hours=4)),
         last_daily=date(2026, 10, 1))  # unsubscribed two days ago

    async def off(s):
        [row] = await _settings(s)
        row.email_on = False
        return alerts.unsubscribe_token(hm.svc.settings.secret_key, "u1",
                                        row.unsubscribe_nonce)
    token = call(hm, off)
    assert hm.post("/v1/alerts/resubscribe", {"token": token}).json() == {
        "email_on": True, "emails": "alerts"}
    [settings] = call(hm, _settings)
    assert settings.last_daily_on == date(2026, 10, 3)
    assert run(hm, at).sent == 0  # not a "daily" email in the middle of the afternoon
    assert run(hm, ist(8, 5, day=4)).sent == 1  # tomorrow's 8:00 brings it


def test_a_move_west_doesnt_skip_a_day():
    from holt_server.db import AlertSettings as Row
    row = Row(user_id="u1", tz="America/Los_Angeles", last_daily_on=date(2026, 10, 2))
    at = datetime(2026, 10, 2, 4, tzinfo=UTC)  # still 1 October in Los Angeles
    mailer.skip_today(row, at, starting=False)
    assert row.last_daily_on == date(2026, 10, 1)
    # Nothing changes for someone who stayed put.
    row = Row(user_id="u1", tz="Asia/Kolkata", last_daily_on=date(2026, 10, 1))
    mailer.skip_today(row, at, starting=False)
    assert row.last_daily_on == date(2026, 10, 1)
    # Turned on after 8:00: the first daily email is tomorrow's.
    row = Row(user_id="u1", tz="Asia/Kolkata", last_daily_on=None)
    mailer.skip_today(row, at, starting=True)
    assert row.last_daily_on == date(2026, 10, 2)
    # Turned on before 8:00: today's 8:00 is the first.
    row = Row(user_id="u1", tz="Asia/Kolkata", last_daily_on=None)
    mailer.skip_today(row, datetime(2026, 10, 2, 1, tzinfo=UTC), starting=True)
    assert row.last_daily_on is None


def test_a_refused_email_is_not_sent_again(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    hm.outbox.error = mailer.MailRefused(422)
    got = run(hm, at)
    assert (got.sent, got.failed) == (0, 1)
    [alert_] = stored(hm, Alert)
    assert alert_.email_via == "failed"
    [record] = stored(hm, AlertEmail)
    assert (record.status, record.provider_id) == ("failed", "422")
    hm.outbox.error = None
    assert run(hm, at + timedelta(minutes=5)).sent == 0  # still on the bell, never emailed


def test_the_daily_limit_holds_emails_back(make_harness):
    h = make_harness(HOLT_PR_WATCH=True, HOLT_ALERT_EMAIL_DAILY_LIMIT=6)  # 6 - 5 in hand = 1
    h.svc.mailer = h.outbox = FakeMailer()
    at = ist(14)
    seed(h, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))
    seed(h, at, ("reply", "moment/moment", 6120, timedelta(minutes=10)), user="u2",
         email="two@example.com")
    got = run(h, at)
    assert (got.sent, got.held) == (1, 1)
    # Inside the same 24 hours the second one stays held; it is still on the bell.
    assert run(h, at + timedelta(hours=1)).sent == 0
    assert len(h.outbox.sent) == 1


def test_a_muted_pull_request_is_left_out_of_email(hm):
    at = ist(14)
    seed(hm, at, ("changes", "pallets/click", 2811, timedelta(minutes=10)))

    async def mute(s):
        from holt_server.db import WatchMute
        s.add(WatchMute(user_id="u1", repo_key="pallets/click", number=2811))
    call(hm, mute)
    assert run(hm, at).sent == 0
