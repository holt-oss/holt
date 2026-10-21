"""Find answers from Holt's own index first, then from a GitHub search.

    POST /v1/find {"languages": [...], "topics": [...], "hacktoberfest": true, "days": 7}

The **index** is every repository with a current-engine 7-day **rules**
report (what Discover reads, discover.py): those whose verdict is "Worth your
time", matching the filters through `repo_meta`, ranked like Discover's
welcoming board. It is read from the database only, so it answers at once
and costs nothing:

* languages: the repo's main language, or its second when that is a real
  share of the code (`repo_meta.languages`); any one of the picked languages.
* topics: any one of the picked topics; `hacktoberfest` adds the
  `hacktoberfest` topic as a requirement, as the search does.
* archived repos and forks are left out (the search leaves them out too); a
  repo closed to outside pull requests already is by its verdict.
* the maintainers' typical first reply must fit in the time picked (`days`),
  the same line the verdict draws for "too slow for the time you have".
* it must have starter issues Holt knows about (`starter_cache`, at most
  `discover.STARTER_MAX_HOURS` old): a repo whose known issues are none, or
  unknown yet, isn't listed. They are the ones a Discover card carries.
  Repos with an issue nobody is on come before those whose issues are all
  taken.

The **search** is the GitHub search `holt.starter.find` runs (jobs.py, cached
6 h per search in `find_cache`). A search job also reads the starter issues
of the first `FILL_ISSUES` index matches that have none known yet, so they
join the list when it finishes, and reads again those of the first
`REREAD_ISSUES` listed whose issues were read more than `REREAD_HOURS` ago:
in October an issue is taken or closed within hours, and these are the ones
people are shown first.

Results are the index first, then the search's repos that aren't already
there. While a search runs, `/v1/find` answers 202 with the index part in
`results`; its `done` event, and a cached search, carry both. When the caller
is over their work limit the index part is the answer, marked `complete:
false`.

The index part is the same for everyone who picks the same filters, so it is
built once and kept (cache.py) until this process writes a report, a repo's
details or its starter issues, `INDEX_KEPT_S` at most. Who is asking, their
limits and the search itself are never kept here.

    POST /v1/find/index {"languages": [...], ..., "limit": 24, "cursor": <next>}

The rest of the index part, for a list that loads more as it is scrolled: the
same matches in the same order, `limit` at a time, with `total` and `next`
(discover.py's cursor). It reads the kept index only: it never starts a
search, calls GitHub or counts against anyone's limit.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from holt_server import cache, repos, schema, starter
from holt_server.db import StarterCache, now
from holt_server.deps import internal, services
from holt_server.discover import (
    BREAKDOWN, COUNTS, _latest, card_issues, cursor_for, kept_card, read_cursor, stamp, start_of,
    starter_issues, welcoming_key,
)
from holt_server.errors import ApiError
from holt_server.services import Services

log = logging.getLogger("holt_server.find")

router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})

# Index matches with no known starter issues whose issues one search reads
# (the web's first page), and how many at a time.
FILL_ISSUES = 12
FILL_AT_ONCE = 4
# The first listed repos (the web's first page) whose issues one search reads
# again, when they were read longer ago than this. A search runs at most once
# per `find_cache_hours` for the same filters, so this is at most
# REREAD_ISSUES one-query reads in that time.
REREAD_ISSUES = 12
REREAD_HOURS = 6.0
# How long a search waits for those reads after its own part is done.
FILL_WAIT_SECONDS = 20.0
# The index part of one set of filters is served for this long at most (see
# the module docstring): at most this many sets, and this many results in all.
INDEX_KEPT_S = 60.0
INDEXES_KEPT = 128
INDEX_RESULTS_KEPT = 20_000


def _matches(meta, params: dict[str, Any]) -> bool:
    languages = set(params.get("languages") or [])
    topics = set(params.get("topics") or [])
    hacktoberfest = bool(params.get("hacktoberfest"))
    if meta is None:
        # Without details nothing is known about language, topics or archiving.
        return not (languages or topics or hacktoberfest)
    if meta.archived or meta.fork:
        return False
    if languages:
        langs = {x.lower() for x in [meta.language or "", *(meta.languages or [])] if x}
        if not languages & langs:
            return False
    tags = {t.lower() for t in meta.topics or []}
    if hacktoberfest and "hacktoberfest" not in tags:
        return False
    return not topics or bool(topics & tags)


def _fits_time(card, days: int) -> bool:
    reply = card.stats.median_first_response_hours
    return reply is None or reply <= days * 24


async def matches(svc: Services, params: dict[str, Any]) -> list:
    """Index cards ("Worth your time") matching the filters, best first."""
    days = int(params.get("days") or 7)
    cards = [c for row in await _latest(svc)  # row[-1] is the repo's RepoMeta
             if row[3] == "viable" and _matches(row[-1], params)
             and (c := kept_card(svc, row)) is not None and _fits_time(c, days)]
    return sorted(cards, key=welcoming_key)


def _result(card, issues: list[dict]) -> dict[str, Any]:
    stats = card.stats.model_dump()
    return schema.FindResult.model_validate({
        "repo": card.repo, "verdict": card.verdict, "description": card.description,
        "language": card.language, "languages": card.languages, "stars": card.stars,
        **{k: getattr(card, k) for k in COUNTS},
        # The report counted what became of the rest, so the odds bar is whole.
        "stats": {k: stats[k] for k in (*starter.STAT_KEYS, *BREAKDOWN) if k in stats},
        "issues": card_issues(issues),
    }).model_dump(mode="json")


def indexes(svc: Services) -> cache.Kept[list[dict[str, Any]]]:
    """This process's index parts, one per set of filters."""
    return cache.store(svc, "find-index", lambda: cache.Kept(
        INDEX_KEPT_S, INDEXES_KEPT, INDEX_RESULTS_KEPT))


async def index_results(svc: Services, params: dict[str, Any]) -> list[dict[str, Any]]:
    """The index part of a find: matches with starter issues, best first.
    Shared between requests: read it, never change it."""
    key = (tuple(sorted(params.get("languages") or [])), tuple(sorted(params.get("topics") or [])),
           bool(params.get("hacktoberfest")), int(params.get("days") or 7))

    async def build() -> list[dict[str, Any]]:
        cards = await matches(svc, params)
        known = await starter_issues(svc, [repos.key(c.repo) for c in cards])
        results = [_result(c, issues) for c in cards
                   if (issues := known.get(repos.key(c.repo)))]
        # Stable: a repo with an issue nobody is on before one with none.
        return sorted(results, key=lambda r: all(starter.taken(i) for i in r["issues"]))

    return await indexes(svc).load(key, stamp(svc), build, lambda r: max(len(r), 1))


class FindIndexIn(BaseModel):
    """A find's filters (as `POST /v1/find` takes them) and which part."""

    model_config = ConfigDict(extra="ignore")

    languages: list[str] = Field(default_factory=list, max_length=10)
    topics: list[str] = Field(default_factory=list, max_length=10)
    days: int = Field(7, ge=1, le=90)
    hacktoberfest: bool = False
    limit: int = Field(24, ge=1, le=100)
    cursor: str | None = Field(None, max_length=400)


class FindIndexPart(schema.Model):
    results: list[schema.FindResult]
    # How many repos the index has for these filters.
    total: int
    # The `cursor` that asks for the part after this one; null at the end.
    next: str | None


@router.post("/find/index", dependencies=[Depends(internal)], response_model=FindIndexPart)
async def find_index(body: FindIndexIn, request: Request) -> dict[str, Any]:
    """One part of a find's index matches (see the module docstring). Reads
    only the kept index: no search, no GitHub call, no rate limit."""
    try:
        offset, last = read_cursor(body.cursor)
    except ValueError:
        raise ApiError("invalid_request", "That isn't a cursor Find gave out.") from None
    params = {
        "languages": sorted({x.strip().lower()[:40] for x in body.languages if x.strip()}),
        "topics": sorted({x.strip().lower()[:60] for x in body.topics if x.strip()}),
        "days": body.days, "hacktoberfest": body.hacktoberfest}
    index = await index_results(services(request), params)
    start = start_of(index, offset, last, lambda r: r["repo"])
    part = index[start:start + body.limit]
    end = start + len(part)
    return {"results": part, "total": len(index),
            "next": cursor_for(end, part[-1]["repo"].lower()) if part and end < len(index) else None}


async def unlisted(svc: Services, params: dict[str, Any], limit: int = FILL_ISSUES) -> list[str]:
    """The first index matches whose starter issues aren't known, or are too
    old: the ones a search reads issues for. A repo known to have none isn't
    read again until that answer is old."""
    cards = await matches(svc, params)
    known = await starter_issues(svc, [repos.key(c.repo) for c in cards])
    return [c.repo for c in cards if repos.key(c.repo) not in known][:limit]


async def aged(svc: Services, params: dict[str, Any], limit: int = REREAD_ISSUES) -> list[str]:
    """Of the first `limit` listed repos, those whose starter issues were read
    more than `REREAD_HOURS` ago: the ones a search reads again."""
    first = [r["repo"] for r in (await index_results(svc, params))[:limit]]
    if not first:
        return []
    async with svc.db.session() as s:
        old = set((await s.execute(
            select(StarterCache.repo_key)
            .where(StarterCache.repo_key.in_([repos.key(r) for r in first]),
                   StarterCache.created_at < now() - timedelta(hours=REREAD_HOURS)))).scalars())
    return [r for r in first if repos.key(r) in old]


async def fill_issues(svc: Services, params: dict[str, Any]) -> int:
    """Read and cache the starter issues of the first index matches that have
    none known, and of the first listed whose issues have aged. Returns how
    many were read; a failure is skipped."""
    from holt_server.api import fetch_starter_issues

    # The aged ones first: they are on the page already.
    names = [*await aged(svc, params), *await unlisted(svc, params)]
    gate = asyncio.Semaphore(FILL_AT_ONCE)

    async def one(repo: str) -> bool:
        try:
            async with gate:
                await fetch_starter_issues(svc, repo)
            return True
        except Exception as exc:  # noqa: BLE001 -- one repo must not sink the search
            log.info("starter issues for %s: %s", repo, exc)
            return False

    return sum(await asyncio.gather(*(one(r) for r in names)))


def merge(index: list[dict], search: list[dict]) -> list[dict]:
    """The index first, then the search's repos that aren't in it."""
    seen = {repos.key(r["repo"]) for r in index}
    extra = [r for r in search if isinstance(r, dict) and r.get("repo")
             and repos.key(r["repo"]) not in seen]
    return [*index, *extra]


def run(svc: Services, params: dict[str, Any], days: int, emit, loop, cached) -> dict[str, Any]:
    """A find job, on a worker thread: the GitHub search, while the starter
    issues of unlisted index matches are read on the loop. Returns the
    search's results only; `_finish` stores them and adds the index."""
    fill = None
    if getattr(starter.module(), "starter_issues", None) is not None:
        fill = asyncio.run_coroutine_threadsafe(
            fill_issues(svc, {**params, "days": days}), loop)
    try:
        return starter.run_find(
            languages=params.get("languages") or [], topics=params.get("topics") or [],
            hacktoberfest=bool(params.get("hacktoberfest")), days=days,
            limit=int(params.get("limit") or 20), token=svc.pool.next(), emit=emit,
            cached=cached, http=getattr(svc, "http", None),
        )
    finally:
        if fill is not None:
            try:
                fill.result(timeout=FILL_WAIT_SECONDS)
            except Exception:  # noqa: BLE001 -- the search's own results still count
                fill.cancel()
                log.info("reading starter issues for index matches didn't finish")
