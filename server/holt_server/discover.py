"""Discover: browse the repositories Holt has checked, and the "most
welcoming <language> repos" boards.

    GET /v1/discover?language=python&topic=cli&sort=welcoming|stars|trending&hacktoberfest=true
        &limit=24&cursor=<next>

Everything here comes from the latest 7-day **rules** report of each
repository, never from a model, and ranks repositories, never people:

* `welcoming` (the boards): only repos whose verdict is "Worth your time",
  best odds first (good, fair, long), then the share of outside pull
  requests merged (a small sample counts for less, see `merged_share`), the
  reply time and how many outsiders tried.
* `stars`: GitHub stars, every verdict.
* `trending`: how many people checked the repo on Holt in the last 7 days
  (`usage_events`: one per person per day, see usage.py). Only repos with at
  least `TRENDING_MIN` are shown, so a handful of visits (or one person) can't
  put a repo on the list.

`hacktoberfest=true` keeps only repos tagged with the `hacktoberfest` topic
(how a project opts in to Hacktoberfest, and what a Hacktoberfest find searches
for) that aren't archived, under any sort. The language chips then count those
repos only.

A board is sent in parts: `limit` repos, the board's `total`, and `next`, the
`cursor` that asks for the part after it (null at the end). The ranked board
of one sort and filter is kept whole (`boards`), so a part is a slice of it.

Language, stars, topics and descriptions live in `repo_meta`: read right
after a repo's report is stored (meta_refresh.py), and daily by the warm pass
(`warm_meta`), one GraphQL query per hundred repositories, for every reported
repo and every repo a find returned in the last day. Find results take their
description, language and stars from it too (`with_meta`).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal, NamedTuple
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, Query, Request, Response
from holt.about import MAX_README
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from holt_server import cache, repos, schema, starter
from holt_server.db import (
    FindCache, RepoMeta, Report, StarterCache, Usage, current_engine, iso, now, utc,
)
from holt_server.deps import internal, services
from holt_server.errors import ApiError
from holt_server.github import DETAILS_BATCH
from holt_server.schema import (
    WELCOMING_LINE, Model, StarterIssue, Stats, VerdictView, _date, odds_for,
    verdict_line, wait_phrase,
)
from holt_server.services import Services

log = logging.getLogger("holt_server.discover")

router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})

Sort = Literal["welcoming", "stars", "trending"]
DAYS = 7
# People (per day) who checked a repo in the last week before it counts as
# trending, and before the count is shown at all.
TRENDING_MIN = 5
TRENDING_DAYS = 7
# How long those counts are served before they are counted again (seconds).
VIEWS_KEPT_S = 60.0
# Languages offered as filters: the most common ones among checked repos.
LANGUAGES_SHOWN = 16
# Repository details older than this are read again by the warm pass.
META_MAX_AGE_HOURS = 24
# The GitHub topic a project adds to take part in Hacktoberfest.
HACKTOBERFEST_TOPIC = "hacktoberfest"
# GitHub allows a repository 20 topics; all are kept so a late one still counts.
MAX_TOPICS = 20
ODDS_RANK = {"good": 0, "fair": 1, "long": 2}
# Welcoming order: small samples are pulled toward a typical merged share.
PRIOR_PRS, PRIOR_RATE = 10, 0.2
# Personal projects aren't set up for outside contributors, so Discover never
# lists them, under any sort.
VERDICTS = set(schema.TONES) - {"personal"}
# Starter issues this old may be closed by now; older ones aren't shown.
STARTER_MAX_HOURS = 72
# Starter issues a card carries, as on a find result: the card shows the
# first and counts them, the focus view lists them.
CARD_ISSUES = 5


class DiscoverRepo(VerdictView):
    repo: str
    description: str | None = None
    language: str | None = None
    # The main languages, primary first; a second only when it is a real
    # share of the code. Empty until the details are read.
    languages: list[str] = Field(default_factory=list)
    stars: int | None = None
    # The whole repository, not Holt's sample: open issues, pull requests ever
    # opened, how many of those are open, and people who committed. Null until
    # the details are read again (and contributors when GitHub wouldn't say).
    open_issues: int | None = None
    pull_requests: int | None = None
    open_pull_requests: int | None = None
    contributors: int | None = None
    topics: list[str] = Field(default_factory=list)
    # When someone last pushed to the repository, per GitHub.
    pushed_at: str | None = None
    # The report's one-line reason (the same sentence the report shows).
    reason: str
    # What this repo does best among the repos on its board, in one sentence
    # (`standouts`). Only where `reason` is the sentence every "Worth your
    # time" repo shares, and only on a board; null otherwise.
    standout: str | None = None
    stats: Stats
    # People who checked it on Holt in the last 7 days; null below TRENDING_MIN.
    checked_this_week: int | None = None
    generated_at: str | None = None
    # Open issues to start with, from the starter-issue cache (what the
    # starter-issues endpoint or the warm pass last read, within
    # STARTER_MAX_HOURS). Empty when none are cached; Discover never reads
    # GitHub for them.
    issues: list[StarterIssue] = Field(default_factory=list)


class LanguageCount(Model):
    name: str
    repos: int


class DiscoverOut(Model):
    sort: Sort
    language: str | None
    topic: str | None
    hacktoberfest: bool = False
    repos: list[DiscoverRepo]
    # The languages to offer as filters, most repos first (ignores the
    # language and topic filters, so the chips don't vanish once one is picked;
    # with `hacktoberfest` they count Hacktoberfest repos only).
    languages: list[LanguageCount]
    trending_min: int
    # How many repos the whole board has, under this sort and these filters.
    total: int = 0
    # The `cursor` that asks for the part after this one; null at the end.
    next: str | None = None


def _norm(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value or None


# What a card reads from `repo_meta`. The README and the report page's other
# long columns stay in the database.
CARD_META = (RepoMeta.repo_key, RepoMeta.repo, RepoMeta.description, RepoMeta.language,
             RepoMeta.languages, RepoMeta.stars, RepoMeta.topics, RepoMeta.pushed_at,
             RepoMeta.archived, RepoMeta.fork, RepoMeta.open_issues, RepoMeta.pull_requests,
             RepoMeta.open_pull_requests, RepoMeta.contributors, RepoMeta.fetched_at)
# Rows read per query when the copies below are filled, so no one read holds
# a database connection for long.
FILL_BATCH = 200
# The whole board is read again this often even when nothing looks changed
# (seconds): `_mark` can't see details written with an older `fetched_at`
# than another writer's, which two overlapping writers can do.
BOARD_KEPT_S = 60.0
# A finished answer (one sort, language, topic and size, as it is sent) is
# served for this long at most, and only until this process writes something
# it was built from (`stamp`). At most this many, and this many bytes of them.
ANSWER_KEPT_S = 60.0
ANSWERS_KEPT = 256
ANSWERS_KEPT_BYTES = 16 * 1024 * 1024
# A ranked board (one sort, language and topic: every repo on it, in order) is
# kept as long, so each part of it is a slice. At most this many boards.
BOARDS_KEPT = 64


class _Kept:
    """This process's copies of what `_latest` hands out, so a request reads
    only what changed since the last one.

    A stored report never changes, so the fields a card takes from its JSON
    are read once and kept by report id. Asking Postgres for them on every
    request made it parse every latest report five times per request: seconds
    with a pool connection held, for each visitor and each crawler. A repo's
    details are kept until `repo_meta.fetched_at` moves, and the whole board
    until a report is stored or details are read (`_mark`), BOARD_KEPT_S at
    most."""

    def __init__(self) -> None:
        self.fields: dict[int, tuple] = {}
        self.meta: dict[str, RepoMeta] = {}
        # (mark, good until, rows): `_latest`'s answer for every repo, what
        # the tables looked like when it was read, and when to read it again
        # anyway (the monotonic clock).
        self.board: tuple[tuple, float, list[tuple]] | None = None
        # repo_key -> (the stats and meta its card was built from, the card).
        self.cards: dict[str, tuple[Any, Any, DiscoverRepo | None]] = {}
        # (good until, on the monotonic clock; `checked_this_week`'s answer).
        self.views: tuple[float, dict[str, int]] | None = None
        # One read of what changed at a time: the requests behind it wait
        # here, holding no connection, and each sees the copies whole.
        self.reading = asyncio.Lock()


_kept: WeakKeyDictionary[Services, _Kept] = WeakKeyDictionary()


def _kept_for(svc: Services) -> _Kept:
    if (kept := _kept.get(svc)) is None:
        kept = _kept[svc] = _Kept()
    return kept


async def _fill(svc: Services, kept: _Kept, ids: list[int], stamps: dict[str, datetime]) -> None:
    """Read the report fields of `ids` and the details of the `stamps` repos
    that aren't kept yet, or whose details were read again since. The caller
    holds `kept.reading`."""
    for batch in batches([i for i in ids if i not in kept.fields], FILL_BATCH):
        async with svc.db.session() as s:
            rows = (await s.execute(
                select(Report.id, Report.report["verdict"].as_string(),
                       Report.report["generated_at"].as_string(),
                       Report.report["stats"], Report.report["decided_by"],
                       Report.report["rule_codes"])
                .where(Report.id.in_(batch)))).all()
        kept.fields.update((row[0], tuple(row[1:])) for row in rows)
    stale = [key for key, at in stamps.items()
             if (have := kept.meta.get(key)) is None or have.fetched_at != at]
    for batch in batches(stale, FILL_BATCH):
        async with svc.db.session() as s:
            metas = (await s.execute(
                select(RepoMeta).options(load_only(*CARD_META, raiseload=True))
                .where(RepoMeta.repo_key.in_(batch)))).scalars().all()
        kept.meta.update((m.repo_key, m) for m in metas)


async def _mark(svc: Services) -> tuple:
    """Changes whenever a report is stored or a repo's details are read."""
    async with svc.db.session() as s:
        return (*(await s.execute(select(func.max(Report.id), func.count(Report.id)))).one(),
                *(await s.execute(select(func.max(RepoMeta.fetched_at),
                                         func.count(RepoMeta.repo_key)))).one())


def stamp(svc: Services) -> tuple:
    """Changes whenever this process writes anything a board or Find's index
    is built from: a report, a repo's details, the starter issues a card
    carries. No database read (cache.py), so a kept answer costs none."""
    return cache.writes(svc).table(
        Report.__tablename__, RepoMeta.__tablename__, StarterCache.__tablename__)


def _board(kept: _Kept, mark: tuple) -> list[tuple] | None:
    """The kept board, if the tables still look as they did and it is young."""
    if kept.board is not None and kept.board[0] == mark and time.monotonic() < kept.board[1]:
        return kept.board[2]
    return None


async def _latest(svc: Services, keys: list[str] | None = None) -> list[tuple]:
    """(repo, report fields..., meta) for the latest 7-day rules report of each
    repo (only those in `keys`, when given). Only the fields a card needs come
    out of the report JSON, not whole bodies, and only the first time a report
    is seen (`_Kept`). `meta` has the `CARD_META` columns only. Reports from an
    older engine are left out until the warm pass redoes them. The rows are
    shared between requests: read them, never change them."""
    kept = _kept_for(svc)
    mark = None
    if keys is None:
        mark = await _mark(svc)
        if (rows := _board(kept, mark)) is not None:
            return rows
    latest = (select(func.max(Report.id).label("id"))
              .where(Report.mode == "rules", Report.days == DAYS, current_engine()))
    stamps = select(RepoMeta.repo_key, RepoMeta.fetched_at)
    if keys is not None:
        latest = latest.where(Report.repo_key.in_(keys))
        stamps = stamps.where(RepoMeta.repo_key.in_(keys))
    latest = latest.group_by(Report.repo_key).subquery()
    # From reading what is current to keeping it, one request at a time: a
    # slower one must not let go of what a newer read just kept.
    async with kept.reading:
        if mark is not None and (rows := _board(kept, mark)) is not None:
            return rows  # the request ahead read it while this one waited
        async with svc.db.session() as s:
            heads = (await s.execute(
                select(Report.id, Report.repo, Report.repo_key, Report.created_at)
                .join(latest, Report.id == latest.c.id))).all()
            fetched = dict((await s.execute(stamps)).all())
        await _fill(svc, kept, [h[0] for h in heads], fetched)
        rows = [(repo, key, created, *kept.fields[id_],
                 kept.meta.get(key) if key in fetched else None)
                for id_, repo, key, created in heads if id_ in kept.fields]
        if keys is None:
            # Everything current was just read: let go of replaced reports
            # and of repos whose details are gone.
            current = {h[0] for h in heads}
            kept.fields = {i: f for i, f in kept.fields.items() if i in current}
            kept.meta = {k: m for k, m in kept.meta.items() if k in fetched}
            kept.cards = {k: c for k, c in kept.cards.items() if k in fetched}
            kept.board = (mark, time.monotonic() + BOARD_KEPT_S, rows)
    return rows


async def starter_issues(svc: Services, keys: list[str]) -> dict[str, list[dict]]:
    """repo_key -> its cached starter issues, for those cached recently by
    the current rules. Reads only the database."""
    if not keys:
        return {}
    since = now() - timedelta(hours=STARTER_MAX_HOURS)
    async with svc.db.session() as s:
        rows = (await s.execute(select(StarterCache.repo_key, StarterCache.issues,
                                       StarterCache.rules_version)
                                .where(StarterCache.repo_key.in_(keys),
                                       StarterCache.created_at >= since))).all()
    return {key: list(issues or []) for key, issues, version in rows
            if starter.current(issues or [], version)}


def card_issues(raw: list[dict]) -> list[StarterIssue]:
    """The first CARD_ISSUES that parse, nobody-on-it first (stable); taken
    ones only when few are free (`starter.offered`)."""
    issues = []
    for i in raw:
        try:
            issues.append(StarterIssue.model_validate(i))
        except ValueError:
            continue
    return starter.offered(issues)[:CARD_ISSUES]


async def checked_this_week(svc: Services) -> dict[str, int]:
    """repo_key -> people who asked for its report in the last 7 days. `who`
    changes every UTC day, so this counts each person once per day. Counted
    at most every VIEWS_KEPT_S: it reads a week of `usage_events`, which
    grows with every visitor."""
    kept = _kept_for(svc)
    if kept.views is not None and time.monotonic() < kept.views[0]:
        return kept.views[1]
    since = (now() - timedelta(days=TRENDING_DAYS - 1)).strftime("%Y-%m-%d")
    people = func.count(func.distinct(Usage.day + ":" + Usage.who))
    async with svc.db.session() as s:
        rows = (await s.execute(
            select(Usage.repo_key, people)
            .where(Usage.kind == "analysis", Usage.day >= since, Usage.repo_key.is_not(None))
            .group_by(Usage.repo_key)
            .having(people >= TRENDING_MIN))).all()
    kept.views = (time.monotonic() + VIEWS_KEPT_S, {key: n for key, n in rows})
    return kept.views[1]


def _card(row: tuple, views: dict[str, int]) -> DiscoverRepo | None:
    repo, key, created, verdict, generated, stats, decided_by, rule_codes, meta = row
    if verdict not in VERDICTS or not isinstance(stats, dict):
        return None
    try:
        st = Stats.model_validate(stats)
    except ValueError:
        return None
    decided_by, rule_codes = decided_by or [], rule_codes or []
    return DiscoverRepo(
        repo=meta.repo if meta else repo, verdict=verdict,
        description=meta.description if meta else None,
        language=meta.language if meta else None,
        languages=list(meta.languages or []) if meta else [],
        stars=meta.stars if meta else None,
        **counts(meta),
        topics=list(meta.topics or []) if meta else [],
        pushed_at=iso(meta.pushed_at) if meta else None,
        reason=verdict_line(verdict, st, decided_by, rule_codes), stats=st,
        checked_this_week=views.get(key), generated_at=generated or iso(created))


def kept_card(svc: Services, row: tuple) -> DiscoverRepo | None:
    """`_card(row, {})`, built once per report and details instead of once
    per request: a board is a thousand of them. Shared between requests, so
    copy it (`model_copy`) to change it."""
    kept = _kept_for(svc)
    key, stats, meta = row[1], row[5], row[-1]
    have = kept.cards.get(key)
    if have is None or have[0] is not stats or have[1] is not meta:
        have = kept.cards[key] = (stats, meta, _card(row, {}))
    return have[2]


async def cards(svc: Services, keys: list[str]) -> dict[str, DiscoverRepo]:
    """repo_key -> the card for each of `keys` that has a current report."""
    if not keys:
        return {}
    return {row[1]: c for row in await _latest(svc, keys)
            if (c := kept_card(svc, row)) is not None}


def is_hacktoberfest(meta: RepoMeta | None) -> bool:
    """Tagged for Hacktoberfest and not archived (archived repos can't take
    pull requests). Repos whose details haven't been read yet aren't."""
    return (meta is not None and not meta.archived
            and HACKTOBERFEST_TOPIC in {t.lower() for t in meta.topics or []})


def merged_share(s: Stats) -> float:
    """The share of outside pull requests merged, as if `PRIOR_PRS` more at a
    typical `PRIOR_RATE` had been seen too: 6 of 8 merged is less sure than
    60 of 105, so it shouldn't top the board."""
    return (s.outsider_merged + PRIOR_RATE * PRIOR_PRS) / (s.outsider_attempts + PRIOR_PRS)


def welcoming_key(card: DiscoverRepo) -> tuple:
    """Best first. Only rules numbers: odds, merged share, reply time, sample size."""
    s = card.stats
    odds = odds_for(card.verdict, s)
    reply = s.median_first_response_hours
    return (ODDS_RANK[odds.level] if odds else 3, -round(merged_share(s), 3),
            reply if reply is not None else float("inf"), -s.outsider_attempts,
            card.repo.lower())


def rank(cards: list[DiscoverRepo], sort: Sort) -> list[DiscoverRepo]:
    if sort == "welcoming":
        return sorted((c for c in cards if c.verdict == "viable"), key=welcoming_key)
    if sort == "trending":
        return sorted((c for c in cards if c.checked_this_week),
                      key=lambda c: (-(c.checked_this_week or 0), -(c.stars or 0),
                                     c.repo.lower()))
    return sorted(cards, key=lambda c: (-(c.stars or 0), c.repo.lower()))


def _pr_days(days: float) -> str:
    return wait_phrase(days * 24)


def _first_timers(n: int) -> str:
    return (f"{n} {'person' if n == 1 else 'people'} got their first pull request "
            "merged here.")


def _merged_on(day: str) -> str | None:
    d = _date(day)
    return f"The last outside pull request was merged on {d[0]} {d[1]} {d[2]}." if d else None


def _days_ago(day: str | None) -> int | None:
    """Smaller for a later date."""
    at = _parse_ts(day)
    return -at.toordinal() if at else None


# What a card can lead with: (the number, smaller is better; its sentence).
# Reply time is first: it wins a tie, and it is what a card says when the repo
# is in the better half of the board on nothing. The share merged isn't one:
# the card's bar marks it and the welcoming board is in its order, so every
# card at the top would lead with it. Only numbers the report counted, never
# a model.
STANDOUTS: tuple[tuple[Callable[[Stats], Any], Callable[[Stats], str | None]], ...] = (
    (lambda s: s.median_first_response_hours,
     lambda s: f"A first reply typically comes within {wait_phrase(s.median_first_response_hours)}."),
    (lambda s: -s.first_time_merged_authors or None,
     lambda s: _first_timers(s.first_time_merged_authors)),
    (lambda s: s.timing.merge_typical_days if s.timing else None,
     lambda s: f"Merges typically land within {_pr_days(s.timing.merge_typical_days)}."),
    (lambda s: _days_ago(s.timing.last_outside_merge) if s.timing else None,
     lambda s: _merged_on(s.timing.last_outside_merge)),
)


def _places(values: list[Any]) -> list[float | None]:
    """Where each value stands among the ones that aren't None, from 0 (the
    smallest) towards 1. Equal values share the middle of their places, so a
    number half the board has is nobody's strong point."""
    have = sorted(v for v in values if v is not None)
    return [None if v is None
            else (bisect_left(have, v) + bisect_right(have, v) - 1) / 2 / len(have)
            for v in values]


def standouts(cards: list[tuple[str, Stats]]) -> list[str | None]:
    """For each (reason, stats) on one board, in order: the number where the
    repo stands best among them, as a sentence. None for a repo whose reason
    already says something of its own, or with none of the numbers."""
    places = [_places([value(s) for _, s in cards]) for value, _ in STANDOUTS]
    out: list[str | None] = []
    for n, (reason, s) in enumerate(cards):
        best = min(((p[n], i) for i, p in enumerate(places) if p[n] is not None), default=None)
        if reason != WELCOMING_LINE or best is None:
            out.append(None)
            continue
        lead = 0 if best[0] >= 0.5 and places[0][n] is not None else best[1]
        out.append(STANDOUTS[lead][1](s))
    return out


class Board(NamedTuple):
    """One sort and filter's whole board, in order. Shared between requests:
    read it, never change it."""

    repos: list[DiscoverRepo]  # without their starter issues
    language: str | None  # as GitHub spells it, when a repo has it
    languages: list[LanguageCount]


def cursor_for(offset: int, last: str) -> str:
    """The cursor for the part after the first `offset` repos, the last of
    which is `last`."""
    return base64.urlsafe_b64encode(f"{offset}:{last}".encode()).decode().rstrip("=")


def read_cursor(cursor: str | None) -> tuple[int, str | None]:
    """(offset, the repo before it) from `cursor_for`'s cursor; the start of
    the board for none. Raises ValueError for anything else."""
    if not cursor:
        return 0, None
    try:
        text = base64.b64decode(cursor + "=" * (-len(cursor) % 4), b"-_", validate=True).decode()
        offset, _, last = text.partition(":")
        if not last or not offset.isascii() or not offset.isdigit():
            raise ValueError(cursor)
        return int(offset), last
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(cursor) from exc


def start_of(ranked: list, offset: int, last: str | None,
             name: Callable[[Any], str] = lambda card: card.repo) -> int:
    """Where the part after `last` starts in `ranked` (`name` gives an item's
    repo). Normally `offset`; when the list changed between two parts, right
    after `last` wherever it is now, so the reader sees no repo twice and
    misses none below it. A `last` that left the list falls back to `offset`."""
    if last is None:
        return 0
    if 0 < offset <= len(ranked) and name(ranked[offset - 1]).lower() == last:
        return offset
    at = next((i for i, item in enumerate(ranked) if name(item).lower() == last), None)
    return at + 1 if at is not None else min(offset, len(ranked))


async def _rank_board(svc: Services, sort: Sort, language: str | None, topic: str | None,
                      hacktoberfest: bool) -> Board:
    views = await checked_this_week(svc)
    cards = [c if (n := views.get(row[1])) is None
             else c.model_copy(update={"checked_this_week": n})
             for row in await _latest(svc)  # row[-1] is the repo's RepoMeta
             if (not hacktoberfest or is_hacktoberfest(row[-1])) and (c := kept_card(svc, row))]
    counts = Counter(c.language for c in cards if c.language)
    chosen = [c for c in cards
              if (language is None or (c.language or "").lower() == language)
              and (topic is None or topic in {t.lower() for t in c.topics})]
    ranked = rank(chosen, sort)
    lines = standouts([(c.reason, c.stats) for c in ranked])
    return Board(
        repos=[c if line is None else c.model_copy(update={"standout": line})
               for c, line in zip(ranked, lines)],
        # The language as GitHub spells it, when a repo has it.
        language=next((name for name in counts if name.lower() == language), language),
        languages=[LanguageCount(name=name, repos=n)
                   for name, n in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
                   [:LANGUAGES_SHOWN]])


def boards(svc: Services) -> cache.Kept[Board]:
    """This process's ranked boards, one per sort and filter."""
    return cache.store(svc, "discover-boards", lambda: cache.Kept(ANSWER_KEPT_S, BOARDS_KEPT))


def _board_stamp(svc: Services) -> tuple:
    """Changes when a board's order or cards may have: a write to what cards
    are built from (`stamp`), or a recount of the trending numbers. Call
    after `checked_this_week`."""
    return stamp(svc), _kept_for(svc).views[0]


async def discover_body(svc: Services, sort: Sort, language: str | None,
                        topic: str | None, limit: int,
                        hacktoberfest: bool = False, cursor: str | None = None) -> DiscoverOut:
    """One part of a board: `limit` repos from `cursor` on (the start, for
    none). Raises ValueError for a cursor this didn't hand out."""
    language, topic = _norm(language), _norm(topic)
    offset, last = read_cursor(cursor)
    await checked_this_week(svc)
    board = await boards(svc).load(
        (sort, language, topic, hacktoberfest), _board_stamp(svc),
        lambda: _rank_board(svc, sort, language, topic, hacktoberfest))
    start = start_of(board.repos, offset, last)
    part = board.repos[start:start + limit]
    end = start + len(part)
    # Only for the cards shown, so a part is one more small read.
    cached = await starter_issues(svc, [repos.key(c.repo) for c in part])
    part = [c.model_copy(update={"issues": card_issues(cached.get(repos.key(c.repo), []))})
            for c in part]
    return DiscoverOut(
        sort=sort, language=board.language, topic=topic, hacktoberfest=hacktoberfest,
        repos=part, languages=board.languages, trending_min=TRENDING_MIN,
        total=len(board.repos),
        next=cursor_for(end, part[-1].repo.lower()) if part and end < len(board.repos) else None)


def answers(svc: Services) -> cache.Kept[cache.Body]:
    """This process's finished Discover answers."""
    return cache.store(svc, "discover", lambda: cache.Kept(
        ANSWER_KEPT_S, ANSWERS_KEPT, ANSWERS_KEPT_BYTES))


@router.get("/discover", dependencies=[Depends(internal)], response_model=DiscoverOut)
async def discover(request: Request,
                   sort: Sort = "welcoming",
                   language: str | None = Query(None, max_length=80),
                   topic: str | None = Query(None, max_length=80),
                   limit: int = Query(24, ge=1, le=100),
                   cursor: str | None = Query(None, max_length=400),
                   hacktoberfest: bool = False) -> Response:
    """Checked repositories, filtered and sorted, one part at a time (see the
    module docstring). Reads only the database: no GitHub call and no rate
    limit. The answer is the same for everyone, so it is built once and kept
    (cache.py) until a report, a repo's details, its starter issues or the
    trending counts change, ANSWER_KEPT_S at most (that long, when another
    process wrote them)."""
    svc = services(request)
    language, topic = _norm(language), _norm(topic)
    try:
        read_cursor(cursor)
    except ValueError:
        raise ApiError("invalid_request", "That isn't a cursor Discover gave out.") from None
    await checked_this_week(svc)

    async def build() -> cache.Body:
        return cache.body_of(
            await discover_body(svc, sort, language, topic, limit, hacktoberfest, cursor))

    body = await answers(svc).load((sort, language, topic, limit, hacktoberfest, cursor or None),
                                   _board_stamp(svc), build, len)
    return cache.respond(request, body)


# --- the warm pass's part -------------------------------------------------------


async def stale_meta(svc: Services, extra: list[str] = ()) -> list[str]:
    """Repositories with a rules report, in a find stored in the last
    META_MAX_AGE_HOURS, or in `extra`, whose details are missing or older than
    that: the missing first, then the oldest."""
    cutoff = now() - timedelta(hours=META_MAX_AGE_HOURS)
    async with svc.db.session() as s:
        reported = (await s.execute(
            select(Report.repo_key, func.max(Report.repo))
            .where(Report.mode == "rules").group_by(Report.repo_key))).all()
        fetched = dict((await s.execute(
            select(RepoMeta.repo_key, RepoMeta.fetched_at))).all())
        # Read before the README, links and release were kept: read again now,
        # not in a day, so a report shows them as soon as the next pass runs.
        old_shape = set((await s.execute(
            select(RepoMeta.repo_key).where(RepoMeta.links.is_(None)))).scalars())
        finds = (await s.execute(
            select(FindCache.results).where(FindCache.created_at >= cutoff))).scalars()
        found = [r["repo"] for results in finds for r in results or []
                 if isinstance(r, dict) and r.get("repo")]
    names = {key: repo for key, repo in reported}
    for repo in [*found, *extra]:
        names.setdefault(repos.key(repo), repo)
    stale = [(key, repo) for key, repo in names.items()
             if key not in fetched or key in old_shape or utc(fetched[key]) < cutoff]
    missing = [repo for key, repo in stale if key not in fetched or key in old_shape]
    old = sorted(((utc(fetched[key]), repo) for key, repo in stale
                  if key in fetched and key not in old_shape), key=lambda t: t[0])
    return missing + [repo for _, repo in old]


async def with_meta(s, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find results with the description, language, stars and counts `repo_meta` has
    for them: the finder screens repos without reading those. A repo with no
    details yet keeps what its result had (null). No GitHub call."""
    keys = {repos.key(r["repo"]) for r in results if isinstance(r, dict) and r.get("repo")}
    if not keys:
        return results
    # The card's columns only: the README and the page's other long ones stay put.
    metas = {m.repo_key: m for m in (await s.execute(
        select(RepoMeta).options(load_only(*CARD_META, raiseload=True))
        .where(RepoMeta.repo_key.in_(keys)))).scalars()}
    breakdowns = await _breakdowns(s, keys)
    out = []
    for r in results:
        if not isinstance(r, dict):
            out.append(r)
            continue
        key = repos.key(r.get("repo") or "")
        m = metas.get(key)
        if m is not None:
            r = {**r, "description": m.description or r.get("description"),
                 "language": m.language or r.get("language"),
                 "languages": list(m.languages or []), "stars": m.stars, **counts(m)}
        if (extra := breakdowns.get(key)) and _same_sample(r.get("stats"), extra):
            r = {**r, "stats": {**r["stats"], **{k: extra[k] for k in BREAKDOWN}}}
        out.append(r)
    return out


# What became of the pull requests that weren't merged: a find screen doesn't
# count these, a report does, and the odds bar draws them.
BREAKDOWN = ("closed_silently", "closed_by_bot", "withdrawn", "still_open")


async def _breakdowns(s, keys: set[str]) -> dict[str, dict[str, Any]]:
    """repo_key -> the latest 7-day rules report's stats, for the repos that have one."""
    latest = (select(func.max(Report.id).label("id"))
              .where(Report.mode == "rules", Report.days == DAYS, current_engine(),
                     Report.repo_key.in_(keys))
              .group_by(Report.repo_key).subquery())
    rows = (await s.execute(
        select(Report.repo_key, Report.report["stats"])
        .join(latest, Report.id == latest.c.id))).all()
    return {key: st for key, st in rows
            if isinstance(st, dict) and all(isinstance(st.get(k), int) for k in BREAKDOWN)}


def _same_sample(stats: Any, report_stats: dict[str, Any]) -> bool:
    """The screen counted the same pull requests as the report, so the report's
    breakdown describes it (a find of another window has other counts)."""
    return (isinstance(stats, dict)
            and stats.get("outsider_attempts") == report_stats.get("outsider_attempts")
            and stats.get("outsider_merged") == report_stats.get("outsider_merged"))


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _homepage(value: Any) -> str | None:
    """A web address only: the page links to it."""
    url = str(value or "").strip()
    if not url or len(url) > 500:
        return None
    scheme = urlsplit(url).scheme.lower()
    if not scheme:
        url, scheme = f"https://{url}", "https"
    return url if scheme in ("http", "https") and "://" in url else None


def _web_url(value: Any) -> str | None:
    """An absolute http(s) address, else None: the page links to it."""
    url = str(value or "").strip()
    parts = urlsplit(url)
    return url if len(url) <= 500 and parts.scheme.lower() in ("http", "https") and parts.netloc else None


def _links(value: Any) -> list[dict[str, str]]:
    out = []
    for link in value or []:
        kind = (link or {}).get("kind") if isinstance(link, dict) else None
        url = _web_url((link or {}).get("url")) if isinstance(link, dict) else None
        if kind in schema.LINK_KINDS and url and all(o["kind"] != kind for o in out):
            out.append({"kind": kind, "url": url})
    return out


def _release(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value.get("tag") or not _web_url(value.get("url")):
        return None
    return {"tag": str(value["tag"])[:100], "published_at": value.get("published_at"), "url": value["url"]}


def _people(value: Any) -> list[dict[str, Any]]:
    """Contributors as stored and served: a login, a GitHub profile and avatar
    address, a commit count and the profile name when there is one. Anything
    else is dropped."""
    out = []
    for p in value or []:
        if not isinstance(p, dict) or not isinstance(p.get("login"), str) or not p["login"]:
            continue
        url = _web_url(p.get("url"))
        if not url or not url.startswith("https://github.com/"):
            continue
        avatar = _web_url(p.get("avatar_url"))
        out.append({"login": p["login"][:100], "name": (str(p.get("name") or "").strip()[:100]) or None,
                    "url": url, "avatar_url": avatar if avatar and avatar.startswith("https://") else None,
                    "contributions": _int(p.get("contributions"))})
    return out


async def store_meta(svc: Services, details: dict[str, dict[str, Any] | None]) -> int:
    """Save what `GitHubLookup.details` returned; missing repos are left alone.
    Returns how many rows were written."""
    written = 0
    async with svc.db.session() as s:
        for requested, d in details.items():
            if d is None:
                continue
            key = repos.key(requested)
            row = await s.get(RepoMeta, key) or RepoMeta(repo_key=key)
            row.repo = d.get("repo") or requested
            row.description = (d.get("description") or "")[:500] or None
            row.language = d.get("language") or None
            row.languages = list(d.get("languages") or [])[:2]
            row.stars = int(d.get("stars") or 0)
            row.topics = list(d.get("topics") or [])[:MAX_TOPICS]
            row.pushed_at = _parse_ts(d.get("pushed_at"))
            row.archived = bool(d.get("archived"))
            row.fork = bool(d.get("fork"))
            row.forks = _int(d.get("forks"))
            row.open_issues = _int(d.get("open_issues"))
            row.pull_requests = _int(d.get("pull_requests"))
            row.open_pull_requests = _int(d.get("open_pull_requests"))
            # A count GitHub wouldn't give this time keeps yesterday's.
            if d.get("contributors") is not None:
                row.contributors = _int(d.get("contributors"))
            row.license = (d.get("license") or "")[:80] or None
            row.homepage = _homepage(d.get("homepage"))
            row.language_shares = list(d.get("language_shares") or [])[:3]
            row.created_at = _parse_ts(d.get("created_at"))
            row.default_branch = (d.get("default_branch") or "")[:200] or None
            row.fork_of = (d.get("fork_of") or "")[:200] or None
            row.readme_line = (d.get("readme_line") or "")[:500] or None
            row.readme = (d.get("readme") or "")[:MAX_README] or None
            row.links = _links(d.get("links"))
            row.latest_release = _release(d.get("latest_release"))
            # A list GitHub wouldn't give this time keeps yesterday's.
            if d.get("top_contributors") is not None:
                row.top_contributors = _people(d.get("top_contributors"))
            row.fetched_at = now()
            s.add(row)
            written += 1
        await s.commit()
    return written


COUNTS = ("open_issues", "pull_requests", "open_pull_requests", "contributors")


def counts(meta: RepoMeta | None) -> dict[str, int | None]:
    """The repository's own counts for a card; all None until its details are read."""
    return {name: getattr(meta, name, None) if meta else None for name in COUNTS}


def about_view(meta: RepoMeta) -> schema.RepoAbout:
    return schema.RepoAbout(
        description=meta.description, readme_line=meta.readme_line, readme=meta.readme, homepage=meta.homepage,
        stars=meta.stars, forks=meta.forks, open_issues=meta.open_issues,
        pull_requests=meta.pull_requests, open_pull_requests=meta.open_pull_requests,
        contributors=meta.contributors,
        license=meta.license, topics=list(meta.topics or []),
        languages=[lang for lang in meta.language_shares or []
                   if isinstance(lang, dict) and lang.get("name")],
        created_at=iso(meta.created_at),
        pushed_at=iso(meta.pushed_at),
        default_branch=meta.default_branch, archived=bool(meta.archived),
        fork=bool(meta.fork), fork_of=meta.fork_of,
        links=_links(meta.links), latest_release=_release(meta.latest_release),
        top_contributors=_people(meta.top_contributors),
        fetched_at=iso(meta.fetched_at))


async def about(svc: Services, repo: str) -> schema.RepoAbout | None:
    """The report's "About this repo", from `repo_meta` (one database read, no
    GitHub call). None until the repo's details have been read."""
    async with svc.db.session() as s:
        meta = await s.get(RepoMeta, repos.key(repo))
    return about_view(meta) if meta is not None else None


def batches(items: list, size: int = DETAILS_BATCH) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]
