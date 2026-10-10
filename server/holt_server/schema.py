"""The response bodies in API.md, as pydantic models.

These are the contract with `web/` and the browser extension: the OpenAPI
document FastAPI builds from them is turned into `web/src/lib/api-schema.ts`
(`server/scripts/api_types.sh`), and CI fails when that file is stale.

What a reader sees at the top of a report (the headline and its tone, then
three lines: the reason, the numbers with their dates, what to do next) and
"How this was counted" are derived here, once, from the verdict, the counts
and the rules. Every surface renders these fields instead of working them out
again, so they cannot disagree with each other or with the verdict. They are
computed fields, so reports cached before a wording change get the new wording.

Adding a field: give it a default (reports already in the cache were stored
without it), add it to API.md, and regenerate the TypeScript types.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from holt.agent.verdict import headline as verdict_headline
from holt.agent.rates import SETTLE_DAYS
from holt.agent.verdict import (
    LONG_SHOT_FIRST_PR_RATE,
    LONG_SHOT_MERGE_RATE,
    LONG_SHOT_MIN_PEOPLE,
    LONG_SHOT_REPLY_DAYS,
    MERGE_RATE_FLOOR,
    MIN_ATTEMPTS_FOR_RATE,
    MIN_DISTINCT_AUTHORS,
    MIN_MERGES,
    hours_phrase,
)
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_serializer

# Bound here, not looked up per call: tests swap `holt.starter` for a fake.
from holt.starter import is_beginner_issue, issue_areas, on_it_text

Verdict = Literal["viable", "long_shot", "not_viable", "insufficient_evidence", "personal",
                  "catalogue"]
Mode = Literal["rules", "ai"]
ContributionType = Literal["code", "docs", "tests", "design", "translations"]
Level = Literal["newcomer", "experienced"]
Tone = Literal["good", "bad", "warn", "neutral"]
OddsLevel = Literal["good", "fair", "long"]
JobState = Literal["queued", "running", "done", "error"]

# Amber is Long shot's: a caution, not a no. "Not enough evidence",
# "Personal project" and "A list, not code" say nothing either way about
# whether your code would get in, so they are neutral.
TONES: dict[str, Tone] = {"viable": "good", "long_shot": "warn", "not_viable": "bad",
                          "insufficient_evidence": "neutral", "personal": "neutral",
                          "catalogue": "neutral"}


class Model(BaseModel):
    # Stored reports may carry keys a model no longer declares (the old
    # `headline`, now computed): ignore them. Fields with defaults are still
    # always present in responses, and the generated types say so.
    model_config = ConfigDict(extra="ignore", json_schema_serialization_defaults_required=True)


# --- errors ------------------------------------------------------------------------

ErrorCode = Literal["unauthorized", "not_found", "invalid_repo", "invalid_request",
                    "rate_limited", "quota_exceeded", "needs_plan", "needs_key", "claim_not_ready",
                    "ai_unavailable", "upstream", "internal", "not_implemented",
                    "payments_off", "payment_unconfirmed"]


class Error(Model):
    # `retry_after` and `reason` are left out, not null, unless they apply (errors.py).
    model_config = ConfigDict(json_schema_serialization_defaults_required=False)

    code: ErrorCode
    message: str
    retry_after: int | None = None
    # `ai_budget_used_up`: an `ai_unavailable` because this environment's AI
    # budget is spent, not because AI is switched off.
    reason: Literal["ai_budget_used_up"] | None = None


class ErrorBody(Model):
    error: Error


# --- the report --------------------------------------------------------------------


class Timing(Model):
    """How long it takes here (engine 7, agent/timing.py). Facts, never read
    by the verdict. Each is null under its minimum."""

    # The waits by which half, and 8 in 10, of settled outside pull requests
    # had an answer: a reply from the team, or a merge. Null when fewer than
    # that ever get one (a pull request closed unanswered stopped waiting and
    # isn't counted past its close).
    first_reply_half_hours: float | None = None
    first_reply_slow_hours: float | None = None
    # Share of outside pull requests opened 60-240 days before the report
    # that were merged within 3, 7, 14, 30 and 60 days of opening.
    merged_within_3_days: float | None = None
    merged_within_7_days: float | None = None
    merged_within_14_days: float | None = None
    merged_within_30_days: float | None = None
    merged_within_60_days: float | None = None
    # Days to merge among those merged: the median, and the 90th percentile.
    merge_typical_days: float | None = None
    merge_slow_days: float | None = None
    # The wait by which half of them were merged (null when fewer were).
    merge_half_days: float | None = None
    # The outside pull requests those are over, and when the first and last
    # were opened (dates).
    merge_cohort_prs: int | None = None
    merge_cohort_merged: int | None = None
    merge_cohort_from: str | None = None
    merge_cohort_to: str | None = None
    # Outside merges came in bursts over the last 26 weeks; null when that
    # can't be read (a short sample, too few merges, work landed elsewhere).
    merges_in_bursts: bool | None = None
    # When the newest outside pull request was merged (a date).
    last_outside_merge: str | None = None
    # A bot closes quiet pull requests, and after how many quiet days (null
    # when only its closes were seen, not its config).
    stale_bot: bool | None = None
    stale_close_days: int | None = None


class Stats(Model):
    # Decided attempts only (opened more than the 14-day settle window ago):
    # the denominator of every rate here. `still_open` were opened within the
    # window, too recently to count, whatever has happened to them so far;
    # `closed_silently` were closed with no reply, which is not `no_reply`.
    outsider_attempts: int
    outsider_merged: int
    distinct_outsiders: int
    first_time_merged_authors: int
    no_reply: int
    median_first_response_hours: float | None
    bot_share: float
    still_open: int = 0
    closed_silently: int = 0
    # Closed with no reply by a bot, or by the person who opened it: not
    # "without a word", and not `no_reply` either. Absent (0) on reports
    # cached before engine 6, where they are inside `closed_silently`.
    closed_by_bot: int = 0
    withdrawn: int = 0
    # Opened more than a year ago: read, and in no count.
    too_old: int = 0
    # How long it takes here (engine 7): null on reports from before it, and
    # on readings of the frozen benchmark.
    timing: Timing | None = None


class PartialStats(Model):
    """The counts a find result carries: whichever the finder had. Counts it
    didn't have are left out, not null (a null reply time means "no replies")."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=False)

    outsider_attempts: int | None = None
    outsider_merged: int | None = None
    distinct_outsiders: int | None = None
    first_time_merged_authors: int | None = None
    no_reply: int | None = None
    median_first_response_hours: float | None = None
    bot_share: float | None = None
    # What became of the rest, when a report has counted them (as on Discover).
    still_open: int | None = None
    closed_silently: int | None = None
    closed_by_bot: int | None = None
    withdrawn: int | None = None

    @model_serializer(mode="wrap")
    def _only_known(self, handler):
        return {k: v for k, v in handler(self).items() if k in self.model_fields_set}


class LandingPath(Model):
    path: str
    merged: int
    attempted: int
    # One file rather than a folder (a path cut to two segments can be either).
    is_file: bool = False


class NeverLanded(Model):
    path: str
    attempted: int
    is_file: bool = False


class EvidenceItem(Model):
    id: str
    url: str
    kind: str
    value: str | None = None
    text: str
    quote: str | None = None


class Cost(Model):
    # Which model ran is internal (the database keeps it), so it isn't here.
    input_tokens: int
    output_tokens: int
    # What the model calls cost in US dollars, and how long the whole run took.
    # Null on reports cached before these were recorded.
    usd: float | None = None
    seconds: float | None = None


class Odds(Model):
    """A newcomer's chances, for a report whose verdict is `viable` only.
    ("Long shot" is already the odds, so it has none.)"""

    level: OddsLevel
    tone: Tone
    text: str


AskCode = Literal["ticket_first", "no_ai_prs", "ok_to_test", "sig_team", "cla", "dco",
                  "issue_first", "ai_disclosure", "duplicates", "stale_bot"]


class Ask(Model):
    """Something the project asks of a contributor before a pull request, and
    where Holt read it (a bot's comment, a pull request, CONTRIBUTING or an AI
    policy). `link` is a link the source gives, such as the tracker a bot
    names, which `next_step` quotes."""

    code: AskCode
    url: str
    link: str | None = None
    # `stale_bot` only: quiet days before the bot closes a pull request, when
    # its config says (null when only its closes were seen).
    days: int | None = None


class Sample(Model):
    """What the counts were read from: the newest pull requests, and who was
    left out of them before counting."""

    # Every pull request read, and when the oldest and newest were opened.
    pull_requests: int
    first_opened: str | None
    last_opened: str | None
    # Opened by the project's own team, or by bots: in no count.
    team_pull_requests: int
    team_people: int
    bot_pull_requests: int


class Counted(Model):
    """One entry of "How this was counted"."""

    topic: str
    text: str


# Thresholds for the odds. web/src/lib/format.ts colours the stat tiles with
# the same numbers, so a tile and the odds line never pull different ways.
MERGE_GOOD, MERGE_FAIR = 0.12, 0.05
NO_REPLY_GOOD, NO_REPLY_FAIR = 0.25, 0.50

ODDS_TEXT: dict[str, str] = {
    "good": "most outside pull requests get a reply, and plenty get merged",
    "fair": "some outside pull requests land; a well-chosen starter issue helps",
    "long": "most outside pull requests here don't land, so pick your first one carefully",
}
# Long odds because of silence, while merges are fine: say that instead.
LONG_SILENT_TEXT = ("many outside pull requests here never get a reply, "
                    "so pick your first one carefully")
ODDS_TONE: dict[str, Tone] = {"good": "good", "fair": "warn", "long": "bad"}


def _band(share: float, good: float, fair: float, higher_is_better: bool) -> int:
    """0 good, 1 fair, 2 long."""
    if higher_is_better:
        return 0 if share >= good else 1 if share >= fair else 2
    return 0 if share <= good else 1 if share <= fair else 2


def odds_for(verdict: str, s: Stats) -> Odds | None:
    """The worse of the merge rate and the reply rate. Only a `viable` report
    has odds: "Not worth your time" and "Not enough evidence" already are the
    answer, and odds next to them could only repeat or contradict it."""
    if verdict != "viable" or not s.outsider_attempts:
        return None
    # Whole percentages, as the stat tiles show them.
    merged = int(100 * s.outsider_merged / s.outsider_attempts + 0.5) / 100
    silent = int(100 * s.no_reply / s.outsider_attempts + 0.5) / 100
    merge_band = _band(merged, MERGE_GOOD, MERGE_FAIR, True)
    band = max(merge_band, _band(silent, NO_REPLY_GOOD, NO_REPLY_FAIR, False))
    level: OddsLevel = ("good", "fair", "long")[band]
    text = LONG_SILENT_TEXT if level == "long" and merge_band < 2 else ODDS_TEXT[level]
    return Odds(level=level, tone=ODDS_TONE[level], text=text)


def _silent_phrase(share: float) -> str:
    if 0.45 <= share <= 0.6:
        return "about half"
    if 0.6 < share < 0.72:
        return "about two in three"
    if share >= 0.72:
        return "most"
    return f"about {round(share * 100)}%"


RUBBER_STAMP_LINE = ("Outside pull requests here get merged without anyone reviewing "
                     "them, so you wouldn't get feedback on yours.")


# Rule codes that say something about the sample and never decide (API.md).
# The reason under the headline is the last rule that is not one of these.
INFO_CODES = frozenset({
    "awaiting_reply", "landed_off_button", "package_updates", "kind_contested",
    "kind_uncited", "sample_period", "dormant", "excluded", "still_open",
    "closed_silently", "closed_by_bot", "closed_stale", "withdrawn", "slow_note", "too_old",
})

# The reasons a project that merges outside work is still a long shot, in the
# order the engine gives them (verdict.py). The first is the headline's reason.
LONG_SHOT_CODES = ("few_newcomers_merged", "few_merged", "mostly_silent", "slow_replies",
                   "one_merge", "one_person")


def deciding_rule(decided_by: list[str], rule_codes: list[str]) -> tuple[str, str]:
    """The sentence and code of the rule that decided the verdict. Reports
    cached before `rule_codes` existed have no codes: their last line."""
    codes = rule_codes if len(rule_codes) == len(decided_by) else [""] * len(decided_by)
    for text, code in zip(reversed(decided_by), reversed(codes)):
        if code not in INFO_CODES:
            return text, code
    return (decided_by[-1], "") if decided_by else ("", "")


def _with_slow_note(line: str, decided_by: list[str], rule_codes: list[str]) -> str:
    """"Worth your time", and replies take longer than the reader's budget:
    the engine's note goes right under the reason, not only in the details."""
    note = next((t for t, c in zip(decided_by, rule_codes) if c == "slow_note"), None)
    return f"{line} {note}" if note else line


def verdict_line(verdict: str, s: Stats, decided_by: list[str], rule_codes: list[str]) -> str:
    """The first line of the report: the reason for the verdict, in one
    sentence. It never oversells: "Worth your time" with a low merge rate or
    many ignored pull requests says so plainly. The counts themselves are the
    next line (`numbers_line`), so a "Worth your time" reason doesn't repeat
    them."""
    n = s.outsider_attempts
    if verdict == "viable":
        rate = s.outsider_merged / n if n else 0.0
        silent = s.no_reply / n if n else 0.0
        low_merge, many_silent = rate < 0.1, silent > 0.4
        if low_merge or many_silent:
            buts = [b for b in (
                "most of their pull requests don't land" if low_merge else "",
                f"{_silent_phrase(silent)} get no reply" if many_silent else "",
            ) if b]
            return _with_slow_note(
                f"Outside contributors do get merged here, but {' and '.join(buts)}, "
                "so choose your first change carefully.", decided_by, rule_codes)
        return _with_slow_note(
            "Outside contributors get real replies here, and their work gets merged."
            if silent < 0.3 else
            "Outside contributors get merged here, though some wait a while for a reply.",
            decided_by, rule_codes)
    if verdict == "long_shot":
        codes = rule_codes if len(rule_codes) == len(decided_by) else [""] * len(decided_by)
        first = next((t for t, c in zip(decided_by, codes) if c in LONG_SHOT_CODES), None)
        return first or deciding_rule(decided_by, rule_codes)[0]
    if verdict == "not_viable":
        # Rubber-stamping reads as a "but" after the merge count, so it gets
        # its own sentence. Reports cached before `rule_codes` existed are
        # recognised by that "But".
        last, code = deciding_rule(decided_by, rule_codes)
        if code == "rubber_stamp" or (not rule_codes and last.startswith("But only")):
            return RUBBER_STAMP_LINE
        if last:
            return last
        if s.outsider_merged == 0:
            return f"None of the last {n} pull requests from outside contributors were merged."
        return (f"Only {s.outsider_merged} of {n} pull requests from outside contributors "
                "were merged, and most never got a useful reply.")
    # "Not enough evidence", "Personal project" and "A list, not code": the
    # rule that decided,
    # in its own words (verdict.py has one line per rule).
    return (deciding_rule(decided_by, rule_codes)[0]
            or "Too few outside contributors have tried recently for Holt to say either way.")


def _pct(part: int, whole: int) -> int:
    # Whole percentages, rounded half up, as the web's stat tiles show them.
    return int(100 * part / whole + 0.5) if whole else 0


def _date(iso: str) -> tuple[int, str, int] | None:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d.day, d.strftime("%b"), d.year


def period(sample: Sample | None) -> str | None:
    """ "3 Jun – 26 Sep 2026": when the pull requests read were opened."""
    if sample is None or not sample.first_opened or not sample.last_opened:
        return None
    a, b = _date(sample.first_opened), _date(sample.last_opened)
    if a is None or b is None:
        return None
    end = f"{b[0]} {b[1]} {b[2]}"
    if a == b:
        return end
    start = f"{a[0]} {a[1]}" + (f" {a[2]}" if a[2] != b[2] else "")
    return f"{start} – {end}"


def numbers_line(s: Stats, sample: Sample | None) -> str:
    """The second line: what happened to outside contributors, with the dates
    it covers. The same counts as the stat tiles and the verdict's rules:
    rates are over decided pull requests, and the ones still too new to judge
    are said apart."""
    n = s.outsider_attempts
    when = period(sample)
    when = f" ({when})" if when else ""
    if not n and not s.still_open:
        return f"Nobody outside the project's team opened a pull request{when}."
    if not n:
        return (f"Outside contributors opened {s.still_open} pull "
                f"request{'' if s.still_open == 1 else 's'}{when}, all in the last "
                f"{SETTLE_DAYS} days, too recently to judge.")
    decided = " that have had time for an answer" if s.still_open else ""
    out = [f"Of {n} pull request{'' if n == 1 else 's'} from outside contributors{when}"
           f"{decided}, {s.outsider_merged} {'was' if s.outsider_merged == 1 else 'were'} "
           f"merged ({_pct(s.outsider_merged, n)}%)."]
    if s.median_first_response_hours is not None:
        # The median is over the ones that got a reply; say so, or a fast
        # median hides a silent majority (the next sentences give its size).
        # The engine's phrasing, so it reads the same as the rule that decided.
        out.append("When a maintainer replied, it was typically within "
                   f"{hours_phrase(s.median_first_response_hours)}.")
    else:
        out.append("No maintainer replied to any of them.")
    if s.closed_silently:
        out.append(f"{_pct(s.closed_silently, n)}% were closed without a word.")
    if s.closed_by_bot:
        out.append(f"{_pct(s.closed_by_bot, n)}% were closed by a bot.")
    if s.withdrawn:
        out.append(f"{_pct(s.withdrawn, n)}% were closed by their authors.")
    if s.no_reply:
        out.append(f"{_pct(s.no_reply, n)}% sat open with no reply.")
    if s.still_open:
        out.append(f"Another {s.still_open} {'was' if s.still_open == 1 else 'were'} opened "
                   f"in the last {SETTLE_DAYS} days, too recently to count.")
    if s.too_old:
        out.append(f"{s.too_old} older than a year {'isn' if s.too_old == 1 else 'aren'}'t "
                   "counted.")
    return " ".join(out)


def stat_line(s: Stats) -> str | None:
    """The short count the browser extension's chip shows next to the headline."""
    n = s.outsider_attempts
    if not n:
        return None
    return f"{s.outsider_merged} of {n} outside PR{'' if n == 1 else 's'} merged"


def first_timer_line(s: Stats) -> str | None:
    if not s.outsider_attempts:
        return None
    k = s.first_time_merged_authors
    if not k:
        return "Nobody got their first pull request merged here in this period."
    return (f"{k} {'person' if k == 1 else 'people'} got their first pull request "
            "merged here.")


# --- how long it takes here (engine 7) ------------------------------------------


def wait_phrase(hours: float) -> str:
    """A wait in plain words, rounded up so "within" stays true: "6 hours",
    "a day", "3 days", "2 weeks", "2 months"."""
    days = hours / 24
    if hours <= 1:
        return "an hour"
    if hours < 22:
        return f"{math.ceil(hours)} hours"
    if days <= 1:
        return "a day"
    if days <= 13:
        return f"{math.ceil(days)} days"
    if days <= 7 * 8:
        weeks = math.ceil(days / 7)
        return f"{weeks} weeks"
    return f"{math.ceil(days / 30)} months"


def share_phrase(share: float) -> str:
    """0.83 -> "most", 0.5 -> "about half", 0.27 -> "about 3 in 10"."""
    if share >= 0.95:
        return "nearly all"
    if share >= 0.75:
        return "most"
    if 0.45 <= share <= 0.55:
        return "about half"
    if share < 0.05:
        return "hardly any"
    return f"about {max(1, round(share * 10))} in 10"


def how_long(s: Stats) -> list[Counted]:
    """ "How long it takes here": first reply, merged within a week and a
    month, bursts, and the stale bot. Only what cleared its minimum."""
    t = s.timing
    if t is None:
        return []
    out: list[Counted] = []
    if t.first_reply_slow_hours is not None:
        typical = s.median_first_response_hours
        out.append(Counted(topic="first reply", text=(
            (f"Typically {wait_phrase(typical)}. " if typical is not None else "")
            + f"Most get one within {wait_phrase(t.first_reply_slow_hours)}.")))
    elif t.first_reply_half_hours is not None:
        out.append(Counted(topic="first reply", text=(
            f"About half get one within {wait_phrase(t.first_reply_half_hours)}.")))
    if t.merged_within_7_days is not None and t.merged_within_30_days is not None:
        week, month = share_phrase(t.merged_within_7_days), share_phrase(t.merged_within_30_days)
        text = (f"{week} within a week." if week == month
                else f"{week} within a week, {month} within a month.")
        out.append(Counted(topic="merged", text=text[:1].upper() + text[1:]))
    if t.merges_in_bursts and t.last_outside_merge and (d := _date(t.last_outside_merge)):
        out.append(Counted(topic="rhythm", text=(
            f"In bursts. The last outside merge was on {d[0]} {d[1]} {d[2]}.")))
    if t.stale_bot:
        out.append(Counted(topic="closed if quiet", text=(
            f"A bot closes pull requests after {t.stale_close_days} quiet days."
            if t.stale_close_days else "A bot closes quiet pull requests.")))
    return out


# The best place to start needs this many merged outside pull requests in it;
# fewer is luck, not a pattern. A folder where this many tried and none landed
# is worth a warning.
BEST_AREA_MIN_MERGED = 3
AVOID_AREA_MIN_TRIED = 5

ASK_STEP: dict[str, str] = {
    "ticket_first": "Get an accepted ticket first.",
    "no_ai_prs": "AI-written pull requests get closed here.",
    "ok_to_test": "A maintainer has to approve tests first.",
    "sig_team": "Find the team (SIG) for your area.",
    "cla": "Sign the CLA (Contributor License Agreement) when the bot asks.",
    "dco": "Sign off every commit (git commit -s): the project asks for a DCO sign-off.",
    "issue_first": "Open an issue before you write code: CONTRIBUTING asks for that.",
    "ai_disclosure": "Say whether you used AI: the project asks for that.",
    "duplicates": "Search open pull requests first: duplicates get closed.",
    "stale_bot": "Keep yours active: a bot closes quiet pull requests.",
}


def ask_text(code: str, link: str | None = None, days: int | None = None) -> str:
    """The sentence for one ask. A ticket names the tracker the bot linked;
    the stale bot, its quiet days."""
    if code == "ticket_first" and link:
        host = link.split("://", 1)[-1].split("/", 1)[0]
        return f"Get an accepted ticket at {host} first."
    if code == "stale_bot" and days:
        return f"Keep yours active: a bot closes pull requests after {days} quiet days."
    return ASK_STEP[code]
NOT_VIABLE_STEP: dict[str, str] = {
    "archived": "Don't send a pull request here. Look for an active fork or a similar "
                "project that's still maintained.",
    "prs_closed": "Pick a project that takes outside pull requests; Holt's Find page "
                  "lists some.",
    "elsewhere": "Contribute where the project is really developed, not here.",
    "closed_kind": "Contribute where the project is really developed, not here.",
    "non_software_kind": "Adding an entry is fine if that's what you want. For experience "
                         "with real code, pick a different project.",
    "catalogue_shape": "Adding an entry is fine if that's what you want. For experience "
                       "with real code, pick a different project.",
    "rubber_stamp": "Your change would probably be merged, but nobody would review it. "
                    "For feedback on your code, pick a project that reviews.",
}
NOT_VIABLE_STEP["replies_no_merges"] = (
    "Talk ideas over in an issue if you like, but put your code into a project "
    "that merges outside work.")
NOT_VIABLE_DEFAULT_STEP = ("Put your time into a project that answers outside "
                           "contributors; Holt's Find page lists some.")
LONG_SHOT_STEP: dict[str, str] = {
    "few_newcomers_merged": "Pick an issue a maintainer has asked for help with, say on it "
                            "that you'd like to work on it, and keep the change small.",
    "mostly_silent": "Before you write code, ask on an issue whether a pull request "
                     "would be welcome, and start only if a maintainer answers.",
    "slow_replies": "Start here only if you can wait a month or more for a first reply.",
    "few_merged": "Pick an issue a maintainer has asked for help with, and keep the "
                  "change small.",
    "one_merge": "Pick an issue a maintainer has asked for help with, and keep the "
                 "change small.",
    "one_person": "Pick an issue a maintainer has asked for help with, and keep the "
                  "change small.",
}
CATALOGUE_STEP = ("Adding an entry is fine if that's what you want. For experience "
                  "with real code, pick a different project.")
PERSONAL_STEP = ("Read it or fork it, but for a contribution pick a project that "
                 "takes outside pull requests; Holt's Find page lists some.")
INSUFFICIENT_STEP = ("There's too little to go on. Before writing code, open an issue "
                     "and ask whether a pull request would be welcome.")


def next_step(verdict: str, decided_by: list[str], rule_codes: list[str],
              landing: list[LandingPath], never_landed: list[NeverLanded],
              asks: list[Ask]) -> str:
    """The third line: what to do next, from where outside work landed and
    what the project asks of contributors. Advice only; it never decides."""
    if verdict == "not_viable":
        _, code = deciding_rule(decided_by, rule_codes)
        return NOT_VIABLE_STEP.get(code, NOT_VIABLE_DEFAULT_STEP)
    if verdict == "personal":
        return PERSONAL_STEP
    if verdict == "catalogue":
        return CATALOGUE_STEP
    if verdict == "long_shot":
        first = next((c for c in rule_codes if c in LONG_SHOT_CODES), "few_merged")
        return " ".join([LONG_SHOT_STEP[first]] + [ask_text(a.code, a.link, a.days) for a in asks])
    if verdict != "viable":
        return " ".join([INSUFFICIENT_STEP] + [ask_text(a.code, a.link, a.days) for a in asks])
    areas = [a for a in landing if a.path != "(root)" and a.merged >= BEST_AREA_MIN_MERGED]
    best = max(areas, key=lambda a: (a.merged, a.merged / a.attempted), default=None)
    if best is not None:
        out = [f"Best bet: a small change in {best.path}, where {best.merged} of "
               f"{best.attempted} outside pull requests were merged."]
    else:
        out = ["Best bet: a small, focused change; a starter issue is a good place to find one."]
    avoid = next((a for a in never_landed if a.attempted >= AVOID_AREA_MIN_TRIED), None)
    if avoid is not None:
        out.append(f"Nothing from outside landed in {avoid.path} ({avoid.attempted} tried).")
    out += [ask_text(a.code, a.link, a.days) for a in asks]
    return " ".join(out)


# `decided_by` lines that inform, shown in "How this was counted" under these.
INFO_TOPICS: dict[str, str] = {
    "awaiting_reply": "Too new to judge",
    "still_open": "Too recent to count",
    "slow_note": "Reply time",
    "closed_silently": "Closed without a word",
    "closed_by_bot": "Closed by a bot",
    "closed_stale": "Closed by a bot",
    "withdrawn": "Closed by their authors",
    "excluded": "Drafts and spam",
    "dormant": "Recent activity",
    "landed_off_button": "Merges GitHub shows as closed",
    "package_updates": "What the work is",
    "kind_contested": "What kind of project this is",
    "kind_uncited": "What kind of project this is",
    "too_old": "Older than a year",
}


def verdict_rule_text(days: int) -> str:
    """"The rule" on every report, written from the thresholds the engine
    reads, so it can't go stale. `days` is kept for callers; the answer no
    longer depends on the reader's budget."""
    return (
        f"Only pull requests from outside contributors opened between {SETTLE_DAYS} days "
        "and a year ago count, so each has had time for an answer and reflects how the "
        "project works now. "
        f"“{verdict_headline('viable')}” needs at least {MIN_MERGES} of them merged, from "
        f"at least {MIN_DISTINCT_AUTHORS} different people, with at least "
        f"{round(10 * LONG_SHOT_FIRST_PR_RATE)} in 10 people getting their first pull "
        f"request merged (once {LONG_SHOT_MIN_PEOPLE} or more have tried), at least 1 in "
        f"{round(1 / LONG_SHOT_MERGE_RATE)} merged, no more than half left without any "
        f"reply, a typical first reply within {LONG_SHOT_REPLY_DAYS // 7} weeks, and people "
        "actually reviewing what gets merged. "
        f"“{verdict_headline('long_shot')}” is a project that merges some outside work "
        f"but misses one of those: fewer than {round(10 * LONG_SHOT_FIRST_PR_RATE)} in 10 "
        f"newcomers getting in, fewer than 1 in {round(1 / LONG_SHOT_MERGE_RATE)} "
        "merged, most left unanswered, very slow first replies, or only one person's "
        "work getting in. "
        f"“{verdict_headline('not_viable')}” is an archived repository, a mirror, a "
        "project with nothing merged or pushed in 90 days, "
        f"merges nobody reviews, fewer than 1 in {round(1 / MERGE_RATE_FLOOR)} outside pull "
        f"requests merged once at least {MIN_ATTEMPTS_FOR_RATE} have been decided, or "
        "outside pull requests that are almost all ignored. "
        f"“{verdict_headline('personal')}” is someone's own project or a small team's, "
        "like a hackathon entry, with nothing from outside ever merged. "
        f"“{verdict_headline('catalogue')}” is a list or a catalogue of entries, like "
        "links or package listings, where a merged entry isn't code work. "
        f"Anything in between is “{verdict_headline('insufficient_evidence')}”. "
        "These rules are fixed; no AI chooses the verdict."
    )


def counted(r: Report) -> list[Counted]:
    """ "How this was counted": the sample, who was left out and why, and the
    rule that decided it. Every number here is one the report already shows."""
    out: list[Counted] = []
    smp = r.sample
    when = period(smp)
    if smp is not None:
        # Not "the newest": a busy project's sample reaches further back too.
        text = f"{smp.pull_requests} pull requests on GitHub"
        text += f", opened {when}." if when else "."
        out.append(Counted(topic="What we read", text=text))
        team = smp.team_pull_requests
        out.append(Counted(topic="The team and outside contributors", text=(
            f"{team} of them came from {smp.team_people} "
            f"{'person' if smp.team_people == 1 else 'people'} on the project's team and "
            f"{'is' if team == 1 else 'are'} left out. The team is everyone GitHub shows as an "
            "owner, member or collaborator, plus anyone the history shows merging, "
            "closing or formally reviewing other people's pull requests. Everyone else "
            "is an outside contributor, including people who come back.")))
        bots = smp.bot_pull_requests
        left = ("No pull requests were opened by bots." if not bots else
                f"{bots} pull request{'' if bots == 1 else 's'} opened by bots (dependency "
                f"updates and the like) {'is' if bots == 1 else 'are'} left out.")
        out.append(Counted(topic="Bots", text=(
            f"{left} Only a maintainer's reply counts as a reply: not a bot, a CLA "
            "check, the author, or a passer-by.")))
    elif r.evidence_until and (d := _date(r.evidence_until)):
        out.append(Counted(topic="What we read", text=(
            f"The newest pull requests on GitHub, up to {d[0]} {d[1]} {d[2]}.")))
    codes = r.rule_codes if len(r.rule_codes) == len(r.decided_by) else [""] * len(r.decided_by)
    for text, code in zip(r.decided_by, codes):
        if code in INFO_TOPICS:
            out.append(Counted(topic=INFO_TOPICS[code], text=text))
    # Every rule that weighed in, in order: a rubber-stamp "But only..." reads
    # after the merge count it qualifies.
    deciding = [t for t, c in zip(r.decided_by, codes) if c not in INFO_CODES]
    if deciding:
        out.append(Counted(topic="What decided it", text=" ".join(deciding)))
    out.append(Counted(topic="The rule", text=verdict_rule_text(r.days)))
    return out


class VerdictView(Model):
    """The headline and its colour, for anything that shows a verdict."""

    verdict: Verdict

    @computed_field
    @property
    def headline(self) -> str:
        return verdict_headline(self.verdict)

    @computed_field
    @property
    def tone(self) -> Tone:
        return TONES[self.verdict]


class HoltUsers(Model):
    """Pull requests that connected Holt users sent to this repository in the
    last `window_days`: counts only. Present only when at least 5 people who
    didn't opt out of statistics make up the numbers (repo_stats.py)."""

    people: int
    pull_requests: int
    merged: int
    # Closed without being merged.
    closed: int
    # Still open.
    waiting: int
    window_days: int
    computed_at: str


class Language(Model):
    name: str
    # Share of the repository's code, 0..1.
    share: float


LinkKind = Literal["contributing", "discussions", "docs", "discord", "slack", "gitter",
                   "matrix", "zulip"]
LINK_KINDS: tuple[str, ...] = LinkKind.__args__


class RepoLink(Model):
    """Where a newcomer finds the rules or help."""

    kind: LinkKind
    url: str


class Release(Model):
    tag: str
    published_at: str | None = None
    url: str


class Contributor(Model):
    """One of the repository's most active committers, as GitHub lists them."""

    login: str
    # The GitHub profile's name; null when the person hasn't set one.
    name: str | None = None
    url: str
    avatar_url: str | None = None
    # Commits to the default branch, GitHub's count.
    contributions: int | None = None


class RepoAbout(Model):
    """What the repository is and how big and alive it is: GitHub's own fields
    and the README's first sentence, read daily into `repo_meta` (never on the
    request path). Nothing here feeds the verdict. Fields a repo hasn't been
    read for yet are null."""

    description: str | None = None
    # The README's first real sentence, plain text.
    readme_line: str | None = None
    # The top of the README as Markdown (at most about 6,000 characters), for the
    # report's README section; null when it has none or isn't Markdown.
    readme: str | None = None
    homepage: str | None = None
    stars: int
    forks: int | None = None
    open_issues: int | None = None
    # Pull requests ever opened, how many are open now, and people who committed.
    pull_requests: int | None = None
    open_pull_requests: int | None = None
    contributors: int | None = None
    # SPDX id ("MIT") or GitHub's name for it; null when there is none.
    license: str | None = None
    topics: list[str] = Field(default_factory=list)
    # Up to three, biggest first.
    languages: list[Language] = Field(default_factory=list)
    created_at: str | None = None
    pushed_at: str | None = None
    default_branch: str | None = None
    archived: bool = False
    fork: bool = False
    # The repository this one is a fork of, when GitHub says.
    fork_of: str | None = None
    # The contributing guide, Discussions, then the README's docs and chat
    # links; one per kind, in that order. Empty until read.
    links: list[RepoLink] = Field(default_factory=list)
    # GitHub's latest release; null when there is none (or not read yet).
    latest_release: Release | None = None
    # The most active committers, most commits first, bots left out (at most
    # ten). Empty until read.
    top_contributors: list[Contributor] = Field(default_factory=list)
    fetched_at: str


class Report(VerdictView):
    repo: str
    mode: Mode
    days: int
    # AI mode only: at most two model-written sentences, the lead of the AI
    # explanation. Null in rules mode and on reports cached before it existed.
    bottom_line: str | None = None
    summary: str | None = None
    stats: Stats
    decided_by: list[str] = Field(default_factory=list)
    # Stable codes of the rules in `decided_by`, same order (`archived`,
    # `ignored`, `merges`, `rubber_stamp`, ...). Empty on reports cached before
    # this field existed.
    rule_codes: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    landing: list[LandingPath] = Field(default_factory=list)
    never_landed: list[NeverLanded] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_until: str | None = None
    generated_at: str
    cost: Cost | None = None
    # What the counts were read from. Null on reports cached before it existed.
    sample: Sample | None = None
    # What the project asks of a contributor (a CLA, a DCO sign-off, an issue
    # first), where Holt could read it. Empty means none found, not none asked.
    asks: list[Ask] = Field(default_factory=list)
    # True when the verdict is the same for every time budget and only the
    # reply-time note reads `days` (rules reports since ticket 08). The server
    # then answers another `days` from this report without reading GitHub
    # again (`report.retime`). False on AI reports and older cached ones.
    budget_independent: bool = False
    # Filled when the report is served (GET /v1/reports/{owner}/{repo}), never
    # stored with it; null when too few Holt users sent pull requests here.
    holt_users: HoltUsers | None = None
    # Filled when served, never stored: what the repository is (`RepoAbout`);
    # null until its details have been read.
    about: RepoAbout | None = None
    # Filled when served by GET /v1/reports/{owner}/{repo}, never stored: true
    # when an older version of Holt's rules made this report. The web runs a
    # fresh check instead of showing it (and shows it only if that fails).
    outdated: bool = False

    # The top of the report, in order: `headline` and `verdict_line` (the
    # verdict and its reason), `numbers_line` (what happened, with dates),
    # `first_timer_line`, and `next_step` (what to do).
    @computed_field
    @property
    def verdict_line(self) -> str:
        return verdict_line(self.verdict, self.stats, self.decided_by, self.rule_codes)

    @computed_field
    @property
    def numbers_line(self) -> str:
        return numbers_line(self.stats, self.sample)

    @computed_field
    @property
    def first_timer_line(self) -> str | None:
        return first_timer_line(self.stats)

    @computed_field
    @property
    def next_step(self) -> str:
        return next_step(self.verdict, self.decided_by, self.rule_codes,
                         self.landing, self.never_landed, self.asks)

    @computed_field
    @property
    def stat_line(self) -> str | None:
        return stat_line(self.stats)

    @computed_field
    @property
    def counted(self) -> list[Counted]:
        return counted(self)

    @computed_field
    @property
    def odds(self) -> Odds | None:
        return odds_for(self.verdict, self.stats)

    @computed_field
    @property
    def how_long(self) -> list[Counted]:
        return how_long(self.stats)


# --- starter issues and find ------------------------------------------------------


class StarterIssue(Model):
    number: int
    title: str
    url: str
    labels: list[str] = Field(default_factory=list)
    created_at: str | None = None
    comments: int = 0
    why: list[str] = Field(default_factory=list)
    # Distinct people already on it (open pull requests, recent claims, quiet
    # assignees) and its open pull requests. Null from an engine that didn't
    # count them.
    people: int | None = None
    open_prs: int | None = None

    @computed_field
    @property
    def on_it(self) -> str | None:
        """"Nobody on it yet", "1 open pull request", "2 people already on it"."""
        if self.people is None:
            return None
        return on_it_text(self.people, self.open_prs or 0)

    # Derived from the labels and title, so cached issues get them too. The
    # web uses them with a profile: a newcomer sees only `beginner` issues,
    # and issues matching their contribution types come first.
    @computed_field
    @property
    def beginner(self) -> bool:
        return is_beginner_issue(self.labels)

    @computed_field
    @property
    def areas(self) -> list[ContributionType]:
        return issue_areas(self.labels, self.title)


class StarterIssues(Model):
    repo: str
    issues: list[StarterIssue]


class RepoHit(Model):
    repo: str
    description: str | None = None
    stars: int = 0


class RepoSearch(Model):
    """Public repositories whose name matches `query`, most starred first."""

    query: str
    results: list[RepoHit]


class FindResult(VerdictView):
    repo: str
    description: str | None = None
    language: str | None = None
    # As on a Discover card: primary first, a second when it's a real share.
    languages: list[str] = Field(default_factory=list)
    stars: int | None = None
    # As on a Discover card; null until the repo's details are read (find only
    # screens repos, so most are null on a first search).
    open_issues: int | None = None
    pull_requests: int | None = None
    open_pull_requests: int | None = None
    contributors: int | None = None
    stats: PartialStats = Field(default_factory=PartialStats)
    issues: list[StarterIssue] = Field(default_factory=list)


class FindQuery(Model):
    languages: list[str]
    topics: list[str]
    days: int
    hacktoberfest: bool
    limit: int


# --- jobs ---------------------------------------------------------------------------


class Queued(Model):
    status: Literal["queued"] = "queued"
    job_id: str


class AnalysisDone(Model):
    status: Literal["done"] = "done"
    report: Report


class FindDone(Model):
    status: Literal["done"] = "done"
    results: list[FindResult]
    # False when only Holt's index answered: the caller is over their work
    # limit, so no GitHub search ran for them.
    complete: bool = True


class FindQueued(Queued):
    """A search under way: `results` is what Holt's index has meanwhile."""

    results: list[FindResult] = Field(default_factory=list)


class JobStatus(Model):
    status: JobState
    stage: str | None = None
    progress: float
    report: Report | None
    error: Error | None


class FindJobStatus(Model):
    status: JobState
    stage: str | None = None
    progress: float
    results: list[FindResult] | None
    error: Error | None


class ReportListItem(Model):
    repo: str
    mode: Mode
    generated_at: str | None
    verdict: Verdict | None


class ReportList(Model):
    reports: list[ReportListItem]


# --- PR pre-flight (preflight.py) ------------------------------------------------------

PreflightVerdict = Literal["ok", "worth_fixing", "unknown"]


class PreflightQuote(Model):
    """The contributing guide's own line on a check's topic."""

    text: str
    path: str | None
    url: str | None


class PreflightCheck(Model):
    # `ci`, `tests`, `size`, `template`, `issue`, `cla`, `signoff`, `changelog`;
    # more may come. Show `title`, not the id.
    id: str
    title: str
    # Computed by rules, never by a model. Show it in words: "looks fine",
    # "worth fixing", "can't tell yet".
    verdict: PreflightVerdict
    # Plain English; may hold Markdown code spans.
    statement: str
    # Example merged pull requests the check compares with (up to 8).
    links: list[str]
    quote: PreflightQuote | None


class PreflightCounts(Model):
    ok: int
    worth_fixing: int
    unknown: int


class PreflightTarget(Model):
    """What was checked. For a branch, `number`, `state` and `outside` are
    null and `url` is GitHub's compare page."""

    kind: Literal["pull_request", "branch"]
    number: int | None
    url: str
    title: str | None
    author: str | None
    # Whether GitHub gives the author no role in the repository.
    outside: bool | None
    state: str | None
    draft: bool
    head: str | None
    base: str | None
    head_sha: str
    additions: int | None
    deletions: int | None
    lines: int | None
    files: int | None


class PreflightSimilar(Model):
    """The merged pull request most like this one (same files, then folders)."""

    number: int | None
    url: str
    title: str
    author: str | None
    outside: bool
    lines: int | None
    files: int | None
    touched_tests: bool | None
    # Plain English, may hold code spans: "It changed files in the same folders: ...".
    why: str


class PreflightSentence(Model):
    text: str
    # The check ids the sentence is about.
    checks: list[str]


class PreflightSummary(Model):
    """A short model-written summary, checked against the checks. No verdict."""

    sentences: list[PreflightSentence]


class Preflight(Model):
    """One pre-flight check of a pull request or branch. There is no overall verdict."""

    repo: str
    checked_at: str
    # How far back the merged pull requests it compares with go.
    window_days: int | None
    archived: bool
    # Set when the comparison covers everyone's pull requests, not only outsiders'.
    note: str | None
    target: PreflightTarget
    checks: list[PreflightCheck]
    counts: PreflightCounts
    similar: PreflightSimilar | None
    summary: PreflightSummary | None
    # This user had checked the same commit before, so this check was free.
    free_recheck: bool = False


class PreflightFor(Model):
    """The pull request or branch a request named, as parsed."""

    repo: str
    number: int | None
    branch: str | None
    base: str | None


class PreflightJob(Model):
    job_id: str
    status: JobState
    stage: str
    progress: float


class PreflightState(Model):
    """GET /v1/preflight."""

    # False when this server runs without paid features: hide pre-flight.
    available: bool
    # Whether anything that pays for pre-flight can be bought yet.
    on_sale: bool
    # Signed in: whether this user can run a check now and what it costs.
    access: Access | None
    target: PreflightFor | None
    # Signed in: this user's latest check of `target`.
    result: Preflight | None
    # Signed in: a check of `target` still running for this user.
    job: PreflightJob | None


class PreflightJobStatus(Model):
    status: JobState
    stage: str | None = None
    progress: float
    preflight: Preflight | None
    error: Error | None


# --- account ------------------------------------------------------------------------

class Credits(Model):
    """Credits: GET /v1/me/credits, and `credits` in GET /v1/me."""

    # Every credit this user can spend: free + purchased.
    balance: int
    # Welcome, weekly and gifted credits.
    free: int
    # Credits from packs (none until payments are switched on).
    purchased: int
    can_claim: bool
    # When the weekly claim opens; null only before the welcome grant.
    next_claim_at: str | None
    claim_every_days: float
    # False while the server has no model key: AI reports can't run at all.
    ai_available: bool


class Me(Model):
    # The plan in force: "free" once a paid plan has lapsed.
    plan: str
    # When that plan lapses; null for free or until changed.
    plan_expires_at: str | None
    credits: Credits


class Access(Model):
    """Whether this user can use one feature now, and what it would cost."""

    feature: str
    # The feature's name, for people.
    name: str
    allowed: bool
    # How a use is paid for now: "plan" (covered) or "credits". Null when not allowed.
    via: Literal["plan", "credits"] | None
    # Credits one use takes (0 when the plan covers it or credits can't pay for it).
    cost: int
    # The plan's monthly allowance left; null when unlimited or the plan has none.
    left_this_month: int | None
    # When not allowed: the error the request would get.
    code: str | None
    message: str | None
    # The plan's allowance left, monthly or in all (the free merge plans);
    # null when unlimited or the plan has none.
    left: int | None = None


class Entitlements(Model):
    """GET /v1/me/entitlements."""

    plan: str
    plan_expires_at: str | None
    features: list[Access]


# --- passes and orders (payments.py) --------------------------------------------------

OrderStatus = Literal["created", "paid", "failed", "held"]


class PassFeature(Model):
    id: str
    # The feature's name, for people.
    name: str
    # Uses per calendar month (UTC); null when unlimited.
    per_month: int | None
    unlimited: bool


class PassPrice(Model):
    # "INR" (paid through Razorpay) or "USD" (through Dodo Payments).
    currency: str
    # Minor units: paise, cents.
    amount: int


class PassOffer(Model):
    id: str
    name: str
    # Days of Pro one payment gives. It never renews.
    days: int
    # The first of `prices`.
    amount: int
    currency: str
    # Every currency this pass can be bought in now, INR first.
    prices: list[PassPrice]


class Passes(Model):
    """GET /v1/passes. `on_sale` is false, and both lists empty, while payments are off."""

    on_sale: bool
    passes: list[PassOffer]
    # What Pro unlocks (every pass gives the same Pro).
    features: list[PassFeature]


class Checkout(Model):
    """POST /v1/me/orders: what Razorpay Checkout needs to take the payment
    (INR), or the page on Dodo Payments to send the buyer to (USD)."""

    order_id: str
    provider: Literal["razorpay", "dodo"]
    # Razorpay's public key id (safe to show the browser); null for Dodo.
    key_id: str | None
    # Razorpay's order id, or Dodo's checkout session id.
    provider_order_id: str
    # Dodo's hosted checkout; null for Razorpay.
    checkout_url: str | None = None
    amount: int
    currency: str
    # What the payment page shows.
    name: str
    description: str
    # The pass bought, and the days of Pro it gives.
    item: str
    days: int


class Order(Model):
    """One purchase, for the buyer's purchase history."""

    id: str
    # The pass id (or, for a purchase from before passes, the credit pack's).
    item: str
    # What was bought, for people.
    name: str
    # Days of Pro it gave; null for a credit pack.
    days: int | None
    amount: int
    currency: str
    # Who took the payment: "razorpay" or "dodo".
    provider: str
    status: OrderStatus
    created_at: str
    paid_at: str | None


class Orders(Model):
    orders: list[Order]


class OrderConfirmed(Model):
    """POST /v1/me/orders/confirm and /v1/me/orders/{id}/check: the order
    (paid, or still being confirmed) and the plan in force."""

    order: Order
    plan: str
    plan_expires_at: str | None


class AdminLot(Model):
    id: int
    origin: str
    pack_id: str | None
    reference: str | None
    granted: int
    remaining: int
    expires_at: str | None
    created_at: str


class AdminCreditEvent(Model):
    id: int
    kind: str
    source: str
    amount: int
    lot_id: int | None
    feature: str | None
    job_id: str | None
    reason: str | None
    actor: str | None
    created_at: str


class AdminPlanEvent(Model):
    id: int
    plan: str
    expires_at: str | None
    reason: str | None
    actor: str | None
    reference: str | None
    created_at: str


class AdminPlanUsage(Model):
    feature: str
    period: str
    used: int


class AdminUserSummary(Model):
    id: str
    # As stored, and the one in force (free once lapsed).
    plan: str
    effective_plan: str
    plan_expires_at: str | None
    free: int
    purchased: int
    created_at: str


class AdminUser(AdminUserSummary):
    """GET /v1/admin/users/{user_id}: everything about one user's money."""

    lots: list[AdminLot]
    ledger: list[AdminCreditEvent]
    plan_history: list[AdminPlanEvent]
    plan_usage: list[AdminPlanUsage]
    access: list[Access]


class AdminUsers(Model):
    users: list[AdminUserSummary]


class AdminAiSpend(Model):
    """GET /v1/admin/ai-spend: this environment's AI spend against its budget."""

    budget_usd: float = Field(description="The cap in force; 0 means AI is off.")
    spent_usd: float = Field(description="What finished AI runs cost (a run whose cost "
                             "isn't known counts at the most it could cost).")
    held_usd: float = Field(description="What running AI jobs hold until they finish.")
    runs: int = Field(description="Finished AI runs.")
    running: int = Field(description="AI jobs holding part of the budget.")
    line: str = Field(description="`AI spend: $x of $y`, for people.")


class HistoryItem(Model):
    job_id: str
    status: JobState
    repo: str
    mode: Mode
    days: int
    verdict: Verdict | None
    created_at: str

    @computed_field
    @property
    def headline(self) -> str | None:
        return verdict_headline(self.verdict) if self.verdict else None

    @computed_field
    @property
    def tone(self) -> Tone | None:
        return TONES[self.verdict] if self.verdict else None


class Health(Model):
    ok: bool
    version: str
    database: bool | None = None


class GitHubAccount(Model):
    id: int
    login: str
    connected_at: str
    adult_confirmed_at: str
    # True when they chose "Don't include me in statistics".
    stats_opt_out: bool


class GitHubConnection(Model):
    connected: bool
    account: GitHubAccount | None


# --- Profile ---------------------------------------------------------------------------

class ProfilePrefs(Model):
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    days: int = 7
    contributions: list[ContributionType] = Field(default_factory=list)
    level: Level = "newcomer"
    updated_at: str | None = None


class ProfileOut(Model):
    # Null until they save one.
    profile: ProfilePrefs | None
    # True when they've confirmed they're 18 or older (here or by connecting
    # GitHub): saving then doesn't ask again.
    adult_confirmed: bool


# --- My Contributions ----------------------------------------------------------------

PullState = Literal["open", "merged", "closed"]
# Whose move it is on an open pull request: "yours" when someone on the
# project's team commented or reviewed after your last push or comment (an
# approval leaves it with them); "theirs" when you acted last; "unknown" when
# Holt couldn't read it, and on merged and closed ones.
Turn = Literal["yours", "theirs", "unknown"]
ReviewDecision = Literal["approved", "changes_requested", "review_required"]
# What the team's last word after your last move was: a review asking for
# changes (it stands until an approval), an approval, or any other comment or
# review.
ReplyKind = Literal["changes", "approved", "reply"]


class RepoVerdict(Model):
    """Holt's latest rules verdict for a repository, from the report cache."""

    verdict: Verdict
    checked_at: str
    # How long an outside pull request there typically waits for its first
    # reply, in hours (the report's median_first_response_hours). Null when
    # the report couldn't tell.
    first_reply_hours: float | None = None
    # How long it takes there (the report's `stats.timing`); null on reports
    # from before engine 7. My PRs' line is worked out from it.
    timing: Timing | None = None

    @computed_field
    @property
    def headline(self) -> str:
        return verdict_headline(self.verdict)

    @computed_field
    @property
    def tone(self) -> Tone:
        return TONES[self.verdict]


class ContributionPullRequest(Model):
    repo: str
    number: int
    title: str
    url: str
    state: PullState
    draft: bool
    created_at: str
    closed_at: str | None
    merged_at: str | None
    # null when Holt has no report for the repository yet.
    verdict: RepoVerdict | None
    # Opened within 30 days after this user looked at the repository on Holt.
    found_via_holt: bool
    # Whether it counts in `summary`. Every pull request to a repository
    # counts, or none does.
    counted: bool = True
    # Why it doesn't count: "you" chose so, or Holt found the repository is
    # the person's own or their team's project ("own_project"). Null when counted.
    not_counted_because: Literal["you", "own_project"] | None = None
    # Open ones only (pr_state.py); refreshed with the list.
    turn: Turn = "unknown"
    # When the turn last changed hands: the team's last word when it's yours,
    # your last push or comment when it's theirs.
    turn_at: str | None = None
    # The first comment or review from the project's team (not bots, not you).
    first_reply_at: str | None = None
    # The newest push, comment or review from a person (bots don't count).
    last_activity_at: str | None = None
    review_decision: ReviewDecision | None = None
    # Who on the team spoke last after your last push or comment, and what
    # that was. Both null when you acted last.
    reply_by: str | None = None
    reply_kind: ReplyKind | None = None
    # PR watch: "on" when Holt alerts on this one, "muted" when its author
    # muted it. Null when the person gets no alerts now, and on merged,
    # closed and uncounted ones.
    watch: Literal["on", "muted"] | None = None
    # It has an alert the person hasn't opened.
    unread_alert: bool = False


class ContributionSummary(Model):
    opened: int
    merged: int
    # Still open: waiting for a decision.
    waiting: int
    # Closed without being merged.
    closed: int
    # merged / (merged + closed); null until any pull request was decided.
    landed_share: float | None
    found_via_holt: int
    # Pull requests left out of the numbers above (see `counted`).
    not_counted: int = 0


class Contributions(Model):
    login: str
    # When GitHub was last read for this user.
    fetched_at: str
    # The refresh button works again from this time; null means now.
    next_refresh_at: str | None
    # How far back the list goes, and whether GitHub had more than we keep.
    window_days: int
    truncated: bool
    summary: ContributionSummary
    pull_requests: list[ContributionPullRequest]


class ContributionChoiceBody(Model):
    """PUT /v1/me/contributions/repos/{owner}/{name}."""

    counted: bool


class ContributionMetric(Model):
    """The product metric: pull requests opened after checking a repo on Holt.
    Counts only, no people."""

    since: str
    window_days: int
    connected_users: int
    users_with_pull_requests: int
    users_with_pr_after_holt: int
    prs_after_holt: int
    prs_after_holt_merged: int


# --- the playbook ("How to get merged here") -----------------------------------------

PlaybookSectionKey = Literal["must_do", "size_and_scope", "reviewers", "closing_reasons",
                             "checklist"]


class PlaybookSource(Model):
    """A counted fact behind a playbook item."""

    statement: str
    # "Seen in `seen` of `of`" pull requests; null for a fact from a document
    # (the contributing guide, CODEOWNERS) rather than a count.
    seen: int | None = None
    of: int | None = None
    # Example pull requests (or the document) on GitHub.
    links: list[str] = Field(default_factory=list)


class PlaybookItem(Model):
    # Plain English; may contain Markdown code spans (check names, paths), never HTML.
    text: str
    sources: list[PlaybookSource] = Field(default_factory=list)


class PlaybookExample(Model):
    """A closed pull request and what someone in the project wrote on it."""

    number: int
    url: str
    title: str = ""
    who: str
    quote: str


class PlaybookClosingReason(Model):
    reason: str
    explanation: str = ""
    # Closed outside pull requests that showed this reason, of those read.
    seen: int
    of: int
    examples: list[PlaybookExample] = Field(default_factory=list)


class PlaybookSections(Model):
    """In display order. Any may be empty: show nothing for an empty one."""

    must_do: list[PlaybookItem] = Field(default_factory=list)
    size_and_scope: list[PlaybookItem] = Field(default_factory=list)
    reviewers: list[PlaybookItem] = Field(default_factory=list)
    closing_reasons: list[PlaybookClosingReason] = Field(default_factory=list)
    checklist: list[PlaybookItem] = Field(default_factory=list)


class Playbook(Model):
    repo: str
    generated_at: str
    # Say once, near the top, when present (e.g. the counts cover everyone's
    # pull requests because too few outside ones were merged).
    note: str | None = None
    # How far back pull requests were read.
    window_days: int | None = None
    archived: bool = False
    sections: PlaybookSections


class PlaybookTeaserSection(Model):
    key: PlaybookSectionKey
    count: int


class PlaybookTeaser(Model):
    """What anyone sees before paying: which sections this repository's
    playbook has, and its first must-do."""

    sections: list[PlaybookTeaserSection]
    first: PlaybookItem | None
    generated_at: str


class PlaybookJob(Model):
    job_id: str
    status: JobState
    stage: str | None = None
    progress: float


class PlaybookState(Model):
    """GET /v1/playbook/{owner}/{repo}."""

    repo: str
    # False when this server runs without paid features: hide the section.
    available: bool
    # Null until someone has had this repository's playbook written.
    teaser: PlaybookTeaser | None
    # The full playbook, only for a signed-in user who unlocked it.
    playbook: Playbook | None
    unlocked: bool
    # Signed in: whether they can unlock it now and what it costs. Null when signed out.
    access: Access | None
    # Whether any way to pay for a playbook is on sale (a plan or a credit pack).
    on_sale: bool
    # This user's playbook for this repository, while it is being written.
    job: PlaybookJob | None


class PlaybookDone(Model):
    status: Literal["done"] = "done"
    playbook: Playbook


class PlaybookJobStatus(Model):
    status: JobState
    stage: str | None = None
    progress: float
    playbook: Playbook | None
    error: Error | None


# --- Merge plan (merge_plan.py) -----------------------------------------------------
#
# The paid AI report: what to do in one repository, written by the
# paid-features service from this server's report and starter issues. Rules
# build it; a model words the call and the steps, and every claim it makes is
# checked against its sources. The verdict is the report's, never the model's,
# and no field names the model.


class PlanNumber(Model):
    value: str  # "5 of 8", "4.4 h"
    label: str


class PlanVerdict(Model):
    """The report's verdict, with its numbers."""

    verdict: Verdict
    headline: str
    tone: Tone
    line: str
    numbers: list[PlanNumber] = Field(default_factory=list)


class PlanCall(Model):
    """What to do here, in one sentence (may contain Markdown code spans)."""

    text: str
    sources: list[PlaybookSource] = Field(default_factory=list)


class PlanLink(Model):
    label: str
    url: str


class PlanCopy(Model):
    """A comment to post on GitHub, as written."""

    label: str
    text: str


class PlanStep(Model):
    title: str  # may contain Markdown code spans
    detail: str | None = None
    link: PlanLink | None = None
    copy_: PlanCopy | None = Field(None, alias="copy")
    sources: list[PlaybookSource] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore", json_schema_serialization_defaults_required=True,
                              populate_by_name=True, serialize_by_alias=True)


class PlanFact(Model):
    """One thing merged pull requests have in common ("72 lines")."""

    value: str
    unit: str
    label: str  # may contain Markdown code spans
    seen: int | None = None
    of: int | None = None
    sources: list[PlaybookSource] = Field(default_factory=list)


class PlanQuote(Model):
    text: str
    # The project member who wrote it.
    who: str
    url: str
    number: int


class PlanExample(Model):
    number: int
    url: str


class PlanClosing(Model):
    """Why outside pull requests get closed, in the maintainers' words."""

    reason: str
    seen: int
    of: int
    quote: PlanQuote | None = None
    examples: list[PlanExample] = Field(default_factory=list)


class PlanReviewer(Model):
    login: str
    reviewed: int
    of: int
    # The folders they review most.
    areas: list[str] = Field(default_factory=list)


class PlanReviewers(Model):
    people: list[PlanReviewer] = Field(default_factory=list)
    sources: list[PlaybookSource] = Field(default_factory=list)


class PlanSignal(Model):
    kind: str  # outsider_posture | onboarding | repo_kind
    value: str
    headline: str
    text: str
    tone: Tone
    url: str | None = None


class PlanOutcome(Model):
    value: str  # the engine's outcome value, for the web to word
    count: int


class PlanThreadQuote(Model):
    text: str
    url: str
    number: int
    outcome: str


class PlanAi(Model):
    """What the AI found reading the pull request threads (from an AI report)."""

    read_on: str
    threads: int
    signals: list[PlanSignal] = Field(default_factory=list)
    outcomes: list[PlanOutcome] = Field(default_factory=list)
    quotes: list[PlanThreadQuote] = Field(default_factory=list)


class PlanWindow(Model):
    # The window asked for, and the day the oldest pull request the counts
    # read was opened (say "since" with this date, never with `days`).
    days: int
    since: str


class PlanSample(Model):
    merged: int
    closed: int
    merged_outside: int
    closed_outside: int


class MergePlan(Model):
    repo: str
    # When the pull requests were read from GitHub, and when the plan was written.
    recorded_on: str
    generated_at: str
    window: PlanWindow
    sample: PlanSample
    # Say once, near the top, when present.
    note: str | None = None
    verdict: PlanVerdict
    call: PlanCall
    steps: list[PlanStep] = Field(default_factory=list)
    merged: list[PlanFact] = Field(default_factory=list)
    closed: list[PlanClosing] = Field(default_factory=list)
    reviewers: PlanReviewers = Field(default_factory=PlanReviewers)
    # Null unless the plan was written from an AI report.
    ai: PlanAi | None = None


class MergePlanJob(Model):
    job_id: str
    status: JobState
    stage: str
    progress: float


class MergePlanState(Model):
    """GET /v1/merge-plan/{owner}/{repo}."""

    repo: str
    # False when merge plans can't be made here (no paid-features service, or
    # AI switched off): hide them.
    available: bool
    # Signed in: whether this user can have a plan made now, and how it's paid.
    access: Access | None
    # Signed in: this user's latest plan for this repository.
    plan: MergePlan | None
    # Signed in: a plan for this repository still being made for this user.
    job: MergePlanJob | None


class MergePlanJobStatus(Model):
    status: JobState
    stage: str | None = None
    progress: float
    plan: MergePlan | None
    error: Error | None


# --- Recommendations ---------------------------------------------------------------


class Recommendation(VerdictView):
    """One pick: a repository Holt rates "Worth your time" that fits the user."""

    repo: str
    description: str | None = None
    language: str | None = None
    languages: list[str] = Field(default_factory=list)
    stars: int | None = None
    # As on a Discover card: the whole repository, null until its details are read.
    open_issues: int | None = None
    pull_requests: int | None = None
    open_pull_requests: int | None = None
    contributors: int | None = None
    topics: list[str] = Field(default_factory=list)
    # The report's one-line reason (the same sentence Discover shows).
    reason: str
    # Why this pick, for this user: plain sentences, most important first.
    why: list[str]
    stats: Stats
    # Open issues to start with, already filtered for the user's experience
    # and ordered by their contribution types. Empty when none are known.
    issues: list[StarterIssue] = Field(default_factory=list)
    # When Holt last checked the repository (its latest rules report).
    checked_at: str | None = None

    @computed_field
    @property
    def odds(self) -> Odds | None:
        return odds_for(self.verdict, self.stats)

    @computed_field
    @property
    def numbers_line(self) -> str:
        """The report's counts line, without its dates (a pick doesn't carry them)."""
        return numbers_line(self.stats, None)


class RecommendationBasis(Model):
    """What the picks were matched on, so the page can say so."""

    # From the profile.
    languages: list[str]
    topics: list[str]
    level: Level
    contributions: list[ContributionType]
    # Languages of the repositories where the user's pull requests were merged
    # (connected users only), most merged first.
    history_languages: list[str]
    # Repositories left out because the user already sent them a pull request.
    already_contributing: int
    has_profile: bool
    connected: bool


class Recommendations(Model):
    """GET /v1/me/recommendations."""

    picks: list[Recommendation]
    # Every pick there is for this user, not only this part (at most 60).
    total: int
    # The `offset` of the part after this one; null when this is the last.
    next: int | None
    basis: RecommendationBasis
    computed_at: str
