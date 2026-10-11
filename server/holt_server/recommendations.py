"""Recommendations for you: `GET /v1/me/recommendations` (API.md).

A short list of repositories, with starter issues, picked for one signed-in
user. Every step is a rule over data Holt already has; no model is asked and
GitHub is never called while the page is served:

* **Candidates** are the repositories whose latest 7-day **rules** report says
  "Worth your time" (checked within `REPORT_MAX_DAYS`), plus viable results of
  recent finds (`find_cache`) Holt has no report for; reports and finds from an
  older engine version don't count. Maintainers must still
  be answering: a median first reply within `REPLY_MAX_HOURS` and at most
  `SILENT_MAX` of outside pull requests left without one. Archived repos and
  forks are left out, and so is every repository the user already sent a pull
  request to (My Contributions) or owns.
* **Matching** uses what the user told us (profile languages and topics) and
  what they did (the languages of repositories where their pull requests were
  merged, for connected users). A repository must match at least one of them.
  With none of that to go on (a new account), the picks are repositories in
  `POPULAR_LANGUAGES`, the best of each language first, and no reason claims
  to know the user.
* **Ranking** adds up fixed points (`POINTS`): a stated language, a language
  they've been merged in, each shared topic, the odds, first-timers merged
  (for a newcomer) and fitting starter issues. Ties go to the Discover order
  (merged share, reply time, sample).
* **Issues** come from `starter_cache` (or the find result): a newcomer sees
  only issues labelled for first-timers, and a repository whose known issues
  have none is dropped; issues matching the user's contribution types first.

The inputs are refreshed elsewhere: reports and starter issues by the warm
pass, repository details daily (discover.py), a connected user's pull
requests daily (contributions.py). So the list is computed per request, from
the database only, and moves as those do.

Recommendations are free: every signed-in user gets every pick, up to
`MAX_PICKS`, a part at a time (`limit` and `offset`; `next` is the offset of the
part after, or null at the end). The order is the same on every request while
the data behind it is, so parts don't repeat or skip a repository; when the
data moves between two requests they can, and a reader drops the repeats.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import load_only

from holt_server import repos, schema
from holt_server.db import (
    Contribution,
    FindCache,
    GitHubConnection,
    Profile,
    RepoMeta,
    iso,
    now,
    utc,
)
from holt_server.deps import Caller, caller, services, signed_in
from holt_server.discover import (
    CARD_META, _latest, counts, merged_share, standouts, starter_issues,
)
from holt_server.schema import Stats, StarterIssue, odds_for, verdict_line
from holt_server.services import Services

router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})

# The most picks ranked for one person: what "all picks" means.
MAX_PICKS = 60
# One request's part of them.
PART = 10
PART_MAX = 30
# What a new account's picks are drawn from, until a profile or merged pull
# requests say more (lower-case, as languages are matched).
POPULAR_LANGUAGES = ("python", "javascript", "typescript", "java", "go", "rust", "c++")
ISSUES_PER_PICK = 3
REPORT_MAX_DAYS = 14
FIND_MAX_DAYS = 7
# "Recent maintainer replies": the typical first reply within a week, and at
# most half of outside pull requests left without one.
REPLY_MAX_HOURS = 7 * 24
SILENT_MAX = 0.5
POINTS = {
    "language": 4,          # a language from the profile
    "history": 3,           # a language their merged pull requests are in
    "both": 1,              # extra when it is both
    "topic": 2,             # per shared topic, at most MAX_TOPICS
    "odds_good": 3, "odds_fair": 1,
    "first_timers": 2,      # newcomers: first-timers were merged recently
    "issues": 2,            # fitting starter issues are known
    "area": 1,              # one of them is the kind of work they picked
}
MAX_TOPICS = 2
AREA_WORDS = {"code": "code", "docs": "docs", "tests": "testing", "design": "design",
              "translations": "translation"}


@dataclass
class Candidate:
    repo: str
    key: str
    stats: Stats
    decided_by: list[str] = field(default_factory=list)
    rule_codes: list[str] = field(default_factory=list)
    description: str | None = None
    language: str | None = None
    languages: list[str] = field(default_factory=list)
    stars: int | None = None
    # discover.counts: open issues, pull requests, contributors.
    counts: dict[str, int | None] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    checked_at: str | None = None
    # Starter issues from a find result; `starter_cache` wins when fresh.
    issues: list[dict] | None = None


@dataclass
class Basis:
    languages: list[str]
    topics: list[str]
    level: str
    contributions: list[str]
    # lower-case language -> merged pull requests in it
    history: Counter
    history_names: list[str]
    excluded: set[str]
    login: str | None
    has_profile: bool

    @property
    def unknown(self) -> bool:
        """Nothing to match on: no profile languages or topics, nothing merged."""
        return not (self.languages or self.topics or self.history)


def hours_phrase(hours: float) -> str:
    """Like the web's humanHours, for a sentence."""
    if hours < 1.5:
        return "about an hour"
    if hours < 24:
        return f"{round(hours)} hours"
    days = hours / 24
    return "about a day" if days < 1.5 else f"{round(days)} days"


def answering(s: Stats) -> bool:
    n = s.outsider_attempts
    return (n > 0 and s.median_first_response_hours is not None
            and s.median_first_response_hours <= REPLY_MAX_HOURS
            and s.no_reply / n <= SILENT_MAX)


# --- reading what Holt already has ----------------------------------------------------


async def basis(svc: Services, user_id: str) -> Basis:
    async with svc.db.session() as s:
        profile = await s.get(Profile, user_id)
        conn = await s.get(GitHubConnection, user_id)
        prs = (await s.execute(select(Contribution.repo_key, Contribution.state)
                               .where(Contribution.user_id == user_id))).all() if conn else []
        merged_keys = Counter(key for key, state in prs if state == "merged")
        langs = dict((await s.execute(
            select(RepoMeta.repo_key, RepoMeta.language)
            .where(RepoMeta.repo_key.in_(list(merged_keys))))).all()) if merged_keys else {}
    history: Counter = Counter()
    spelled: dict[str, str] = {}
    for key, n in merged_keys.items():
        if lang := langs.get(key):
            history[lang.lower()] += n
            spelled.setdefault(lang.lower(), lang)
    return Basis(
        languages=list(profile.languages or []) if profile else [],
        topics=list(profile.topics or []) if profile else [],
        level=profile.level if profile else "newcomer",
        contributions=list(profile.contributions or []) if profile else [],
        history=history,
        history_names=[spelled[k] for k, _ in sorted(history.items(), key=lambda x: (-x[1], x[0]))],
        excluded={key for key, _ in prs},
        login=conn.login if conn else None,
        has_profile=profile is not None)


async def candidates(svc: Services) -> dict[str, Candidate]:
    """Every repository that could be recommended to anyone, by repo_key."""
    out: dict[str, Candidate] = {}
    cutoff = now() - timedelta(days=REPORT_MAX_DAYS)
    for (repo, key, created, verdict, generated, stats, decided_by, rule_codes,
         meta) in await _latest(svc):
        if verdict != "viable" or utc(created) < cutoff or not isinstance(stats, dict):
            continue
        if meta is not None and (meta.archived or meta.fork):
            continue
        try:
            st = Stats.model_validate(stats)
        except ValueError:
            continue
        out[key] = Candidate(
            repo=meta.repo if meta else repo, key=key, stats=st,
            decided_by=decided_by or [], rule_codes=rule_codes or [],
            description=meta.description if meta else None,
            language=meta.language if meta else None,
            languages=list(meta.languages or []) if meta else [],
            stars=meta.stars if meta else None, counts=counts(meta),
            topics=list(meta.topics or []) if meta else [],
            checked_at=generated or iso(created))
    # Find results fill in repositories Holt has no recent report for.
    since = now() - timedelta(days=FIND_MAX_DAYS)
    async with svc.db.session() as s:
        finds = [(row.results, row.created_at) for row in (await s.execute(
            select(FindCache).where(FindCache.created_at >= since)
            .order_by(FindCache.created_at.desc()))).scalars() if not row.outdated]
        # Not the READMEs: a card's columns only, for every repo there is.
        metas = {m.repo_key: m for m in (await s.execute(
            select(RepoMeta).options(load_only(*CARD_META, raiseload=True)))).scalars()}
    for results, created in finds:
        for r in results or []:
            c = _from_find(r, created, metas)
            if c is not None and c.key not in out:
                out[c.key] = c
    return out


def _from_find(r: Any, created, metas: dict[str, RepoMeta]) -> Candidate | None:
    if not isinstance(r, dict) or r.get("verdict") != "viable" or not r.get("repo"):
        return None
    try:
        # A find result may carry only some counts; without all of them the
        # reply rule can't be checked, so it isn't a candidate.
        st = Stats.model_validate(r.get("stats") or {})
        key = repos.key(r["repo"])
    except ValueError:
        return None
    meta = metas.get(key)
    if meta is not None and (meta.archived or meta.fork):
        return None
    return Candidate(
        repo=r["repo"], key=key, stats=st,
        description=(meta.description if meta else None) or r.get("description"),
        language=(meta.language if meta else None) or r.get("language"),
        languages=list(meta.languages or []) if meta else [],
        stars=meta.stars if meta else r.get("stars"), counts=counts(meta),
        topics=list(meta.topics or []) if meta else [],
        checked_at=iso(created), issues=list(r.get("issues") or []))


# --- the rules ------------------------------------------------------------------------


@dataclass
class Scored:
    points: int
    why: list[str]
    issues: list[StarterIssue]
    candidate: Candidate


def fitting_issues(raw: list[dict], b: Basis) -> list[StarterIssue]:
    issues = []
    for i in raw:
        try:
            issues.append(StarterIssue.model_validate(i))
        except ValueError:
            continue
    if b.level == "newcomer":
        issues = [i for i in issues if i.beginner]
    wanted = set(b.contributions)
    # Nobody on it first, then the kind of work they want. Stable: the
    # finder's order within each group.
    return sorted(issues, key=lambda i: (bool(i.people or i.open_prs),
                                         not (wanted & set(i.areas))))


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def score(c: Candidate, b: Basis, raw_issues: list[dict] | None) -> Scored | None:
    """Points and plain reasons for one candidate, or None when it doesn't fit."""
    s = c.stats
    if not answering(s) or c.key in b.excluded:
        return None
    if b.login and c.key.split("/")[0] == b.login.lower():
        return None
    odds = odds_for("viable", s)
    if b.level == "newcomer" and odds is not None and odds.level == "long":
        return None
    lang = (c.language or "").lower()
    stated = bool(lang) and lang in b.languages
    merged_in = b.history.get(lang, 0) if lang else 0
    wanted_topics = set(b.topics)
    shared = [t for t in c.topics if t.lower() in wanted_topics][:MAX_TOPICS]
    if b.unknown:
        if lang not in POPULAR_LANGUAGES:
            return None
    elif not (stated or merged_in or shared):
        return None
    issues = None
    if raw_issues is not None:
        issues = fitting_issues(raw_issues, b)
        if b.level == "newcomer" and not issues:
            return None  # we know its open issues, and none are for first-timers

    points, why = 0, []
    if stated and merged_in:
        points += POINTS["language"] + POINTS["history"] + POINTS["both"]
        why.append(f"Written in {c.language}, one of your languages, and "
                   "you've had pull requests merged in it.")
    elif stated:
        points += POINTS["language"]
        why.append(f"Written in {c.language}, one of your languages.")
    elif merged_in:
        points += POINTS["history"]
        prs = "a pull request" if merged_in == 1 else "pull requests"
        why.append(f"Written in {c.language}, where you've had {prs} merged before.")
    if shared:
        points += POINTS["topic"] * len(shared)
        why.append(f"About {_names(shared)}, "
                   f"{'a topic' if len(shared) == 1 else 'topics'} you picked.")
    if odds is not None:
        points += POINTS.get(f"odds_{odds.level}", 0)
    why.append(f"Maintainers usually reply within "
               f"{hours_phrase(s.median_first_response_hours or 0)}.")
    if b.level == "newcomer" and s.first_time_merged_authors > 0:
        points += POINTS["first_timers"]
        n = s.first_time_merged_authors
        why.append(f"{n} {'person' if n == 1 else 'people'} had their first pull request "
                   "merged here recently.")
    if issues:
        points += POINTS["issues"]
        kinds = [a for a in b.contributions if a in issues[0].areas]
        if kinds:
            points += POINTS["area"]
            why.append(f"Has an open {AREA_WORDS[kinds[0]]} issue, the kind of work you "
                       "want to do.")
        elif b.level == "newcomer":
            n = len(issues)
            why.append(f"Has {'an open issue' if n == 1 else f'{n} open issues'} "
                       "labelled for first-timers.")
    return Scored(points, why, (issues or [])[:ISSUES_PER_PICK], c)


def rank(scored: list[Scored]) -> list[Scored]:
    def key(x: Scored) -> tuple:
        c = x.candidate
        s = c.stats
        reply = s.median_first_response_hours
        return (-x.points, -round(merged_share(s), 3),
                reply if reply is not None else float("inf"), -s.outsider_attempts,
                c.repo.lower())
    return sorted(scored, key=key)


def spread(ranked: list[Scored]) -> list[Scored]:
    """The best of each language first, then each one's second, and so on, so a
    list matched on nothing in particular isn't all one language."""
    seen: Counter = Counter()
    turns = []
    for i, x in enumerate(ranked):
        lang = (x.candidate.language or "").lower()
        turns.append((seen[lang], i, x))
        seen[lang] += 1
    return [x for _, _, x in sorted(turns, key=lambda t: t[:2])]


def pick(x: Scored) -> schema.Recommendation:
    c = x.candidate
    return schema.Recommendation(
        repo=c.repo, verdict="viable", description=c.description, language=c.language,
        languages=c.languages, stars=c.stars, topics=c.topics, **(c.counts or counts(None)),
        reason=verdict_line("viable", c.stats, c.decided_by, c.rule_codes),
        why=x.why, stats=c.stats, issues=x.issues, checked_at=c.checked_at)


async def recommend(svc: Services, user_id: str, limit: int = PART, offset: int = 0,
                    ) -> tuple[list[schema.Recommendation], Basis, int]:
    """One part of the user's picks, what they were matched on, and how many
    picks there are in all (at most `MAX_PICKS`)."""
    b = await basis(svc, user_id)
    b.languages = [x.lower() for x in b.languages]
    b.topics = [x.lower() for x in b.topics]
    # Issues are read only for repositories that fit without them.
    pool = {k: c for k, c in (await candidates(svc)).items() if score(c, b, None)}
    cached = await starter_issues(svc, list(pool))
    scored = [x for c in pool.values()
              if (x := score(c, b, cached.get(c.key, c.issues))) is not None]
    ranked = rank(scored)
    if b.unknown:
        ranked = spread(ranked)
    ranked = ranked[:MAX_PICKS]
    # What each does best among all the picks, so a later part changes no card.
    picks = [pick(x) for x in ranked]
    lines = standouts([(p.reason, p.stats) for p in picks])
    picks = [p.model_copy(update={"standout": line}) for p, line in zip(picks, lines)]
    return picks[offset:offset + limit], b, len(ranked)


# --- the route ------------------------------------------------------------------------


@router.get("/me/recommendations")
async def get_recommendations(request: Request, limit: int = Query(PART, ge=1, le=PART_MAX),
                              offset: int = Query(0, ge=0),
                              who: Caller = Depends(caller)) -> schema.Recommendations:
    """Reads only the database: no GitHub call, no model, no rate limit."""
    svc = services(request)
    user_id = signed_in(who)
    picks, b, total = await recommend(svc, user_id, limit, offset)
    return schema.Recommendations(
        picks=picks, total=total, next=offset + limit if offset + limit < total else None,
        basis=schema.RecommendationBasis(
            languages=b.languages, topics=b.topics, level=b.level,
            contributions=b.contributions, history_languages=b.history_names,
            already_contributing=len(b.excluded), has_profile=b.has_profile,
            connected=b.login is not None),
        computed_at=iso(now()))

