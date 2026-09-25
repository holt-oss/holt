"""Where to start: open issues a newcomer can pick up, in repositories that merge
newcomers' work.

Label lists like goodfirstissue.dev answer "which issues are tagged for
beginners?" They cannot answer the question underneath it: will anyone review
the pull request? Holt can, because it reads the contribution history. So this
module does two things and keeps them apart:

* **The repository screen decides who is listed.** `find` keeps a repository
  only when the rules in `verdict.py` call it worth a newcomer's time. The
  default screen is `discover`'s free pass (one page of pull-request threads,
  arithmetic only, no model); the web server can pass its cached full verdict
  instead.
* **The issue score only orders.** It is a transparent sum over labels,
  recency, discussion size and where outsider work has landed, and every point
  it adds comes with a plain-English line in `why`. It makes no claim beyond
  that list.

Holt is read-only toward GitHub: everything here is a query.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from holt.agent import landing as landing_mod
from holt.agent.landing import Area
from holt.agent.verdict import DEFAULT_CONTRIBUTOR_DAYS, headline
from holt.evidence.errors import RateLimited, RepoNotFound
from holt.evidence.github_graphql import GitHubGraphQL
from holt.reponame import normalise
from holt.report import Verdict

# Re-exported: callers of this module catch these without importing the
# evidence layer.
__all__ = ["FindResult", "GitHub", "RateLimited", "RepoNotFound", "RepoScreen",
           "StarterIssue", "find", "rules_screen", "starter_issues"]

# ---------------------------------------------------------------------------
# Results


@dataclass(slots=True)
class StarterIssue:
    number: int
    title: str
    url: str
    labels: list[str]
    created_at: str
    comments: int
    why: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "title": self.title, "url": self.url,
                "labels": list(self.labels), "created_at": self.created_at,
                "comments": self.comments, "why": list(self.why)}


@dataclass(slots=True)
class FindResult:
    repo: str
    headline: str
    verdict: str
    stats: dict[str, Any]
    issues: list[StarterIssue]

    def as_dict(self) -> dict[str, Any]:
        return {"repo": self.repo, "headline": self.headline, "verdict": self.verdict,
                "stats": dict(self.stats), "issues": [i.as_dict() for i in self.issues]}


@dataclass(slots=True)
class RepoScreen:
    """What `find` needs to know about a repository before listing it.

    `verdict` is a `Verdict` or its string value. `landing` is the directories
    where outsider work merged, used to boost issues that name them; the web
    server can build it from a cached report's `landing` list.
    """

    verdict: Verdict | str
    stats: dict[str, Any] = field(default_factory=dict)
    landing: list[Area] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Transport


def query_key(document: str, variables: dict[str, Any]) -> str:
    """Stable identity of one GraphQL call, for recording and replaying it."""
    raw = document + "\n" + json.dumps(variables, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class GitHub(GitHubGraphQL):
    """`GitHubGraphQL` that can write down what it was told.

    Retries, rate limits and typed errors are the base class's. With
    `recorder`, every answer is appended to it, keyed by `query_key`, so a run
    can be replayed in tests. The token is in a header and is never recorded.
    """

    def __init__(self, token: str | None = None, client: httpx.Client | None = None,
                 recorder: list[dict[str, Any]] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(token=token, client=client, sleep=sleep)
        self.recorder = recorder
        self._lock = threading.Lock()

    def query(self, document: str, *, timeout: float | None = None,
              **variables: object) -> dict[str, Any]:
        data = super().query(document, timeout=timeout, **variables)
        if self.recorder is not None:
            with self._lock:
                self.recorder.append({"key": query_key(document, dict(variables)),
                                      "variables": dict(variables),
                                      "response": {"data": data}})
        return data


def _transport(token: str | None, transport: GitHubGraphQL | None) -> GitHubGraphQL:
    return transport or GitHub(token=token)


# ---------------------------------------------------------------------------
# Queries

ISSUE_FIELDS = """
fragment StarterFields on Issue {
  number title url createdAt updatedAt body locked
  repository { nameWithOwner isArchived }
  labels(first:15) { nodes { name } }
  assignees { totalCount }
  comments { totalCount }
  recent: comments(last:3) { nodes { createdAt body author { login } } }
  closedByPullRequestsReferences(first:5, includeClosedPrs:false) { nodes { state } }
  timelineItems(last:10, itemTypes:[CROSS_REFERENCED_EVENT, CONNECTED_EVENT]) {
    nodes {
      ... on CrossReferencedEvent { source { ... on PullRequest { state } } }
      ... on ConnectedEvent { subject { ... on PullRequest { state } } }
    }
  }
}
"""

# Two views of one repository in one call: issues carrying a beginner label
# (search, so label spelling is case-insensitive), and the most recently active
# open issues, where unlabelled small fixes and odd label spellings turn up.
REPO_ISSUES = ISSUE_FIELDS + """
query($owner:String!, $name:String!, $q:String!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    nameWithOwner isArchived
    issues(states:OPEN, first:40, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { ...StarterFields }
    }
  }
  labelled: search(query:$q, type:ISSUE, first:50) {
    nodes { ...StarterFields }
  }
}
"""

# Sourcing for `find`: just enough to group by repository.
ISSUE_SOURCE = """
query($q:String!) {
  rateLimit { remaining resetAt }
  search(query:$q, type:ISSUE, first:100) {
    nodes {
      ... on Issue {
        number
        repository { nameWithOwner isArchived isFork stargazerCount }
      }
    }
  }
}
"""

REPO_SOURCE = """
query($q:String!) {
  rateLimit { remaining resetAt }
  search(query:$q, type:REPOSITORY, first:30) {
    nodes {
      ... on Repository {
        nameWithOwner isArchived isFork stargazerCount
        goodFirstIssues: issues(states:OPEN, labels:["good first issue",
          "good-first-issue", "beginner", "first-timers-only", "easy"]) { totalCount }
      }
    }
  }
}
"""

# Label names GitHub search is asked for (matched case-insensitively there).
SEARCH_LABELS = ('"good first issue"', '"good-first-issue"', '"good first bug"',
                 '"first-timers-only"', "beginner", '"beginner friendly"', "easy",
                 '"E-easy"', '"help wanted"', '"up-for-grabs"', "hacktoberfest")
SOURCE_LABELS = ('"good first issue"', '"good-first-issue"', '"first-timers-only"',
                 "beginner", "easy")


# ---------------------------------------------------------------------------
# Scoring

# Only issues touched this recently count as alive.
ACTIVE_DAYS = 180
# Discussion past this size usually means the problem is not a first issue,
# whatever the label says.
LONG_DISCUSSION = 12
# A claim ("can I work on this?") older than this is probably abandoned.
CLAIM_FRESH_DAYS = 45
MAX_BODY = 20000


def _norm(label: str) -> str:
    label = re.sub(r":[a-z0-9_+-]+:", " ", label.lower())  # :emoji: codes
    label = re.sub(r"[^a-z0-9]+", " ", label)
    return " ".join(label.split())


_BEGINNER = re.compile(r"\b(good first (issue|bug|pr|contribution)|first timers? only|"
                       r"beginners?( friendly)?|good for (beginners|newcomers)|"
                       r"newcomers?|starter|first contribution)\b")
_EASY = re.compile(r"\b(easy|trivial|low hanging fruit|size (xs|s|small)|small)\b")
_HELP = re.compile(r"\b(help wanted|up for grabs|contributions? welcome|prs? welcome)\b")
_HACK = re.compile(r"^hacktoberfest$")
# Labels saying the issue is not ready for anyone, let alone a newcomer.
_NOT_READY = re.compile(r"\b(wontfix|won t fix|invalid|duplicate|question|discussion|"
                        r"blocked|on hold|needs design|needs decision|rfc|proposal|stale)\b")
_SMALL_TITLE = re.compile(r"\b(typos?|spelling|misspel\w*|docs?|documentation|readme|"
                          r"docstrings?|broken links?|dead links?|grammar|wording|"
                          r"examples?|translation)\b", re.I)
_CLAIM = re.compile(r"\b(i('d| would) (like|love) to (work on|take|tackle)|"
                    r"can i (work on|take|pick|tackle)|may i (work on|take)|"
                    r"i('ll| will) (work on|take|pick)|assign (this|it) to me|"
                    r"i('m| am) (working on|on) (this|it))\b", re.I)

# Directory names too generic to count as a mention on their own.
_GENERIC_SEGMENTS = {"src", "lib", "libs", "source", "main", "core", "app", "apps",
                     "pkg", "pkgs", "packages", "internal", "(root)", "java", "python",
                     "js", "go", "rust", "include", "common", "utils", "util", "crates",
                     "modules", "cmd", "server", "client", "frontend", "backend"}
# Top-level areas an issue names in words rather than as a path ("fix the docs").
_AREA_WORDS = {"docs", "doc", "documentation", "examples", "example", "tests", "test",
               "website", "tutorials", "tutorial", "translations", "i18n"}
# Only boost for an area where outsider work actually tends to land.
MIN_AREA_LANDED = 2
MIN_AREA_RATE = 0.25


def label_kinds(labels: Iterable[str]) -> set[str]:
    kinds: set[str] = set()
    for raw in labels:
        label = _norm(raw)
        if _BEGINNER.search(label):
            kinds.add("beginner")
        if _EASY.search(label):
            kinds.add("easy")
        if _HELP.search(label):
            kinds.add("help")
        if _HACK.search(label):
            kinds.add("hacktoberfest")
        if _NOT_READY.search(label):
            kinds.add("not_ready")
    return kinds


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _has_open_pr(node: dict[str, Any]) -> bool:
    for pr in (node.get("closedByPullRequestsReferences") or {}).get("nodes") or []:
        if pr and pr.get("state") == "OPEN":
            return True
    for item in (node.get("timelineItems") or {}).get("nodes") or []:
        pr = (item or {}).get("source") or (item or {}).get("subject") or {}
        if pr.get("state") == "OPEN":
            return True
    return False


def _mentioned_area(text: str, landing: Sequence[Area], repo: str = "") -> Area | None:
    """The first landing area this issue names, if any.

    A path counts when written out (`docs/`, `src/flask/cli`). A single name
    counts when it is distinctive: not generic (`src`), and not the project's
    own name, which nearly every issue mentions.
    """
    low = text.lower()
    own = {part.lower() for part in repo.split("/") if part}
    for area in landing:
        if area.path == "(root)" or area.landed < MIN_AREA_LANDED or area.rate < MIN_AREA_RATE:
            continue
        path = area.path.lower()
        last = path.rsplit("/", 1)[-1]
        if "/" not in path and path in _GENERIC_SEGMENTS:
            continue  # "src/" is in half of all issues; it says nothing
        if "/" in path and path in low:
            return area
        if re.search(rf"(?<![\w./-]){re.escape(path)}/", low):
            return area
        if last in own or last in _GENERIC_SEGMENTS:
            continue
        distinctive = last in _AREA_WORDS if "/" not in path else len(last) >= 4
        if distinctive and re.search(rf"(?<![\w-]){re.escape(last)}(?![\w-])", low):
            return area
    return None


def _ago(days: float) -> str:
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    return f"{int(days)} days ago"


def score_issue(node: dict[str, Any], as_of: datetime, *,
                landing: Sequence[Area] = (), hacktoberfest: bool = False
                ) -> tuple[float, StarterIssue] | None:
    """Score one open issue for a newcomer, or None if it is not a starter issue.

    Every point comes with a sentence in `why`, positives first.
    """
    if (node.get("assignees") or {}).get("totalCount"):
        return None
    if node.get("locked") or (node.get("repository") or {}).get("isArchived"):
        return None
    if _has_open_pr(node):
        return None
    updated = _ts(node.get("updatedAt") or node["createdAt"])
    idle = (as_of - updated).total_seconds() / 86400
    if idle > ACTIVE_DAYS:
        return None

    labels = [n["name"] for n in (node.get("labels") or {}).get("nodes") or [] if n]
    kinds = label_kinds(labels)
    if "not_ready" in kinds:
        return None
    title = node.get("title") or ""
    body = (node.get("body") or "")[:MAX_BODY]
    comments = (node.get("comments") or {}).get("totalCount") or 0

    score = 0.0
    why: list[str] = []
    cautions: list[str] = []

    def label_named(pattern: re.Pattern) -> str:
        return next(label for label in labels if pattern.search(_norm(label)))

    if "beginner" in kinds:
        score += 4
        why.append(f"Labelled “{label_named(_BEGINNER)}” by the maintainers")
    if "easy" in kinds:
        score += 2.5
        why.append(f"Marked as easy (“{label_named(_EASY)}”)")
    if "help" in kinds:
        score += 1.5
        why.append("Maintainers asked for outside help")
    if "hacktoberfest" in kinds:
        score += 2 if hacktoberfest else 1
        why.append("Counts for Hacktoberfest")
    if not kinds & {"beginner", "easy", "help", "hacktoberfest"}:
        # Unlabelled: only a clearly small fix qualifies.
        match = _SMALL_TITLE.search(title)
        if not match or len(body) > 1500 or comments > 5:
            return None
        score += 1.5
        why.append(f"Looks like a small fix (about {match.group(0).lower()})")

    repo = (node.get("repository") or {}).get("nameWithOwner", "")
    if landing and (area := _mentioned_area(f"{title}\n{body}", landing, repo)):
        score += 2
        why.append(f"Mentions {area.path}/, where {area.landed} of {area.attempted} "
                   "pull requests from first-time contributors were merged")

    if idle <= 14:
        score += 1.5
        why.append(f"Active recently (last update {_ago(idle)})")
    elif idle <= 60:
        score += 0.5
        why.append(f"Updated {_ago(idle)}")

    if len(body) >= 200:
        score += 0.5
        why.append("Has a detailed description")
    elif not body.strip():
        score -= 0.5
        cautions.append("No description yet, so you may need to ask what is wanted")

    if 1 <= comments <= 5:
        score += 0.5
        why.append(f"{comments} comment{'s' if comments != 1 else ''} to give you context")
    elif comments > LONG_DISCUSSION:
        score -= 1.5
        cautions.append(f"Long discussion ({comments} comments): it may be harder than "
                        "it looks")

    for c in (node.get("recent") or {}).get("nodes") or []:
        if not c or not _CLAIM.search(c.get("body") or ""):
            continue
        age = (as_of - _ts(c["createdAt"])).total_seconds() / 86400
        if age <= CLAIM_FRESH_DAYS:
            score -= 3
            cautions.append(f"Someone asked to work on this {_ago(age)}; comment "
                            "before you start")
            break

    number = node["number"]
    issue = StarterIssue(
        number=number,
        title=title,
        url=node.get("url") or f"https://github.com/{repo}/issues/{number}",
        labels=labels,
        created_at=node["createdAt"],
        comments=comments,
        why=why + cautions,
    )
    return round(score, 2), issue


def rank(nodes: Iterable[dict[str, Any]], as_of: datetime, *,
         landing: Sequence[Area] = (), hacktoberfest: bool = False,
         limit: int = 20) -> list[tuple[float, StarterIssue]]:
    """Deduplicate, score and sort. Ties go to the newer issue, then the number."""
    seen: set[int] = set()
    scored: list[tuple[float, StarterIssue]] = []
    for node in nodes:
        if not node or "number" not in node or node["number"] in seen:
            continue
        seen.add(node["number"])
        if result := score_issue(node, as_of, landing=landing, hacktoberfest=hacktoberfest):
            scored.append(result)
    scored.sort(key=lambda pair: (-pair[0], -_ts(pair[1].created_at).timestamp(),
                                  pair[1].number))
    return scored[:limit]


# ---------------------------------------------------------------------------
# One repository


def _scored_issues(repo: str, transport: GitHubGraphQL, as_of: datetime, limit: int,
                   landing: Sequence[Area], hacktoberfest: bool
                   ) -> list[tuple[float, StarterIssue]]:
    owner, _, name = normalise(repo).partition("/")
    labels = ",".join(SEARCH_LABELS)
    q = f"repo:{owner}/{name} is:issue is:open no:assignee label:{labels}"
    data = transport.query(REPO_ISSUES, owner=owner, name=name, q=q)
    repository = data.get("repository")
    if repository is None:  # the search half answered, so the base class did not raise
        raise RepoNotFound(f"{owner}/{name}")
    if repository.get("isArchived"):
        return []
    nodes = [*((data.get("labelled") or {}).get("nodes") or []),
             *((repository.get("issues") or {}).get("nodes") or [])]
    return rank(nodes, as_of, landing=landing, hacktoberfest=hacktoberfest, limit=limit)


def starter_issues(repo: str, token: str | None, limit: int = 20,
                   as_of: datetime | None = None, *,
                   landing: Sequence[Area] = (), hacktoberfest: bool = False,
                   transport: GitHubGraphQL | None = None) -> list[StarterIssue]:
    """Open, unassigned issues in `repo` that suit a newcomer, best first.

    One GraphQL call. `landing` (directories where outsider work merged) boosts
    issues that name them; pass it when you already have it.
    """
    as_of = as_of or datetime.now(UTC)
    scored = _scored_issues(repo, _transport(token, transport), as_of, limit,
                            landing, hacktoberfest)
    return [issue for _, issue in scored]


# ---------------------------------------------------------------------------
# Many repositories


def _stats_subset(signals) -> dict[str, Any]:
    """The API's `stats` names, for the numbers a screen actually measured."""
    return {
        "outsider_attempts": signals.outsider_threads,
        "outsider_merged": signals.outsider_merged,
        "distinct_outsiders": signals.distinct_outsider_authors,
        "first_time_merged_authors": signals.distinct_merged_authors,
        "no_reply": signals.outsider_ignored,
        "median_first_response_hours": signals.median_first_response_hours,
    }


def rules_screen(transport: GitHubGraphQL, as_of: datetime,
                 days: int = DEFAULT_CONTRIBUTOR_DAYS) -> Callable[[str], RepoScreen]:
    """`discover`'s free screen as a `find` screen: one page of pull-request
    threads, arithmetic only, plus where outsider work landed in that page."""
    from holt import discover
    from holt.agent.signals import build_threads

    def screen(repo: str) -> RepoScreen:
        screened, records = discover.screen_slug(repo, transport, as_of, days)
        landing = landing_mod.compute(build_threads(records))
        return RepoScreen(verdict=screened.verdict, stats=_stats_subset(screened.signals),
                          landing=list(landing.landed))

    return screen


def issue_source_queries(languages: Sequence[str], hacktoberfest: bool,
                         as_of: datetime) -> list[str]:
    """Issue search, one query per language (GitHub ANDs `language:`)."""
    since = (as_of - timedelta(days=ACTIVE_DAYS // 2)).date().isoformat()
    label = "hacktoberfest" if hacktoberfest else ",".join(SOURCE_LABELS)
    base = f"is:issue is:open no:assignee -linked:pr archived:false label:{label} updated:>{since}"
    return [f"{base} language:{lang}" for lang in languages] or [base]


def repo_source_queries(languages: Sequence[str], topics: Sequence[str],
                        hacktoberfest: bool, as_of: datetime) -> list[str]:
    """Repository search, one query per language and topic (qualifiers AND)."""
    pushed = (as_of - timedelta(days=30)).date().isoformat()
    tail = ["good-first-issues:>=2", f"pushed:>{pushed}", "archived:false",
            "fork:false", "stars:>=20"]
    topic_list = list(topics)
    if hacktoberfest and "hacktoberfest" not in topic_list:
        # With topics given, "hacktoberfest" is an extra requirement on each;
        # without, it is the topic.
        if topic_list:
            tail.insert(0, "topic:hacktoberfest")
        else:
            topic_list = ["hacktoberfest"]
    langs = [f"language:{lang}" for lang in languages] or [None]
    tops = [f"topic:{t}" for t in topic_list] or [None]
    return [" ".join(p for p in (lang, top, *tail) if p) for lang in langs for top in tops]


# Stars below this in issue-search results are usually personal projects whose
# screen would fail anyway; skipping them saves screening slots.
MIN_ISSUE_SOURCE_STARS = 20


def source_candidates(transport: GitHubGraphQL, languages: Sequence[str],
                      topics: Sequence[str], hacktoberfest: bool, as_of: datetime,
                      max_repos: int) -> list[str]:
    """Candidate repositories, most promising first.

    Weight: two per matching issue from issue search (capped), plus the
    repository's open beginner-labelled issue count from repository search
    (capped). Issue search cannot filter by topic, so it is skipped when topics
    are given.
    """
    weight: dict[str, float] = {}
    order: list[str] = []

    def add(slug: str, w: float) -> None:
        if slug not in weight:
            weight[slug] = 0.0
            order.append(slug)
        weight[slug] += w

    # Every search at once: they are independent, and sourcing sits in front of
    # everything else the caller waits for.
    calls = [(REPO_SOURCE, q) for q in repo_source_queries(languages, topics,
                                                           hacktoberfest, as_of)]
    if not topics:
        calls = [(ISSUE_SOURCE, q) for q in issue_source_queries(
            languages, hacktoberfest, as_of)] + calls
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pages = list(pool.map(lambda c: transport.query(c[0], q=c[1])["search"]["nodes"]
                              or [], calls))
    issue_pages = [p for (doc, _), p in zip(calls, pages) if doc is ISSUE_SOURCE]
    repo_pages = [p for (doc, _), p in zip(calls, pages) if doc is REPO_SOURCE]

    if issue_pages:
        hits: dict[str, int] = {}
        for node in (n for page in issue_pages for n in page):
            repo = (node or {}).get("repository") or {}
            if (not repo or repo.get("isArchived") or repo.get("isFork")
                    or (repo.get("stargazerCount") or 0) < MIN_ISSUE_SOURCE_STARS):
                continue
            hits[repo["nameWithOwner"]] = hits.get(repo["nameWithOwner"], 0) + 1
        for slug, n in hits.items():
            add(slug, 2 * min(n, 5))
    for node in (n for page in repo_pages for n in page):
        if not node or node.get("isArchived") or node.get("isFork"):
            continue
        add(node["nameWithOwner"],
            min((node.get("goodFirstIssues") or {}).get("totalCount") or 0, 10))
    ranked = sorted(order, key=lambda s: -weight[s])  # stable: first seen wins ties
    return ranked[:max_repos]


def _is_viable(verdict: Verdict | str) -> bool:
    return Verdict(verdict) is Verdict.VIABLE


# `find` stops screening new repositories after this long and returns what it
# has, so one request stays well under half a minute.
FIND_BUDGET_SECONDS = 20.0
WORKERS = 6


def find(languages: Sequence[str], topics: Sequence[str], hacktoberfest: bool,
         token: str | None, limit: int = 20,
         screen: Callable[[str], RepoScreen] | None = None,
         progress: Callable[[str], None] | None = None, *,
         as_of: datetime | None = None, days: int = DEFAULT_CONTRIBUTOR_DAYS,
         per_repo: int = 3, max_repos: int = 10,
         budget_seconds: float = FIND_BUDGET_SECONDS,
         transport: GitHubGraphQL | None = None) -> list[FindResult]:
    """Repositories that merge newcomers' work, each with its best starter issues.

    Only repositories whose screen says `viable` are returned, ordered by the
    quality of their starter issues. `screen` defaults to the free rules-only
    screen; the web server passes one that serves a cached verdict.
    """
    say = progress or (lambda _msg: None)
    # The budget covers sourcing too: it is the caller's wait that matters.
    deadline = time.monotonic() + budget_seconds
    as_of = as_of or datetime.now(UTC)
    transport = _transport(token, transport)
    screen = screen or rules_screen(transport, as_of, days)
    languages = [lang.strip().lower() for lang in languages if lang.strip()]
    topics = [t.strip().lower() for t in topics if t.strip()]

    say("Searching GitHub for beginner-friendly issues")
    candidates = source_candidates(transport, languages, topics, hacktoberfest, as_of,
                                   max_repos)
    say(f"Found {len(candidates)} repositories to check")
    if not candidates:
        return []

    stop = threading.Event()

    def check(slug: str) -> tuple[float, FindResult] | None:
        if stop.is_set():
            return None
        result = screen(slug)
        if not _is_viable(result.verdict):
            return None
        if stop.is_set():
            return None
        scored = _scored_issues(slug, transport, as_of, per_repo, result.landing,
                                hacktoberfest)
        if not scored:
            return None
        verdict = Verdict(result.verdict)
        # Best issue counts most; more good options still help.
        quality = sum(s * w for (s, _), w in zip(scored, (1.0, 0.5, 0.25)))
        return quality, FindResult(repo=slug, headline=headline(verdict),
                                   verdict=verdict.value, stats=dict(result.stats),
                                   issues=[issue for _, issue in scored])

    found: list[tuple[float, FindResult]] = []
    rate_limited: RateLimited | None = None
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        futures: dict[Future, str] = {pool.submit(check, slug): slug for slug in candidates}
        pending = set(futures)
        while pending:
            left = deadline - time.monotonic()
            if left <= 0:
                say(f"Stopped after {budget_seconds:.0f}s; "
                    f"{len(pending)} repositories not checked")
                break
            done, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
            for fut in done:
                slug = futures[fut]
                try:
                    outcome = fut.result()
                except RateLimited as err:
                    rate_limited = err
                    say(f"{slug}: GitHub rate limit reached")
                    stop.set()
                    continue
                except Exception as err:  # one bad repository must not sink the rest
                    say(f"{slug}: could not check ({err})")
                    continue
                if outcome is None:
                    say(f"{slug}: skipped")
                else:
                    found.append(outcome)
                    say(f"{slug}: {len(outcome[1].issues)} starter issues")
    finally:
        stop.set()
        pool.shutdown(wait=False, cancel_futures=True)

    if rate_limited and not found:
        raise rate_limited
    found.sort(key=lambda pair: (-pair[0], pair[1].repo.lower()))
    return [result for _, result in found[:limit]]


# ---------------------------------------------------------------------------
# Plain-text rendering, for `holt start`


def _stats_line(stats: dict[str, Any]) -> str:
    parts = []
    tried, merged = stats.get("outsider_attempts"), stats.get("outsider_merged")
    if tried:
        parts.append(f"{merged} of {tried} recent pull requests from first-time "
                     "contributors were merged")
    hours = stats.get("median_first_response_hours")
    if hours is not None:
        parts.append("first reply usually within an hour" if hours < 1 else
                     f"first reply usually within {math.ceil(hours)} hours" if hours < 48
                     else f"first reply usually within {math.ceil(hours / 24)} days")
    return "; ".join(parts)


def render_issues(issues: Sequence[StarterIssue], indent: str = "") -> list[str]:
    lines = []
    for issue in issues:
        lines.append(f"{indent}- #{issue.number} {issue.title}")
        lines.append(f"{indent}  {issue.url}")
        if issue.why:
            lines.append(f"{indent}  " + " · ".join(issue.why))
    return lines


def render_find(results: Sequence[FindResult], describe: str) -> str:
    lines = [f"# Where to start: {describe}", ""]
    if not results:
        lines += ["No repository matched that both merges newcomers' work and has an "
                  "open starter issue right now. Try another language or topic, or "
                  "drop --hacktoberfest.", ""]
        return "\n".join(lines)
    lines += ["Each repository below merges pull requests from first-time contributors "
              "(checked from its recent history). Issues are listed best first.", ""]
    for i, result in enumerate(results, 1):
        lines.append(f"{i}. {result.repo}: {result.headline}")
        if stats := _stats_line(result.stats):
            lines.append(f"   {stats}")
        lines += render_issues(result.issues, indent="   ")
        lines.append("")
    lines.append("Run `holt analyze <repo> --live` for the full evidence on any repository.")
    return "\n".join(lines) + "\n"


def render_repo(repo: str, issues: Sequence[StarterIssue]) -> str:
    lines = [f"# Where to start in {repo}", ""]
    if not issues:
        lines += ["No open, unassigned issue here looks like a good first one right now.",
                  f"Run `holt analyze {repo} --live` to see whether newcomers' pull "
                  "requests get merged at all.", ""]
        return "\n".join(lines)
    lines += render_issues(issues)
    lines += ["", f"Before you start, check `holt analyze {repo} --live` to see whether "
              "newcomers' pull requests get merged here."]
    return "\n".join(lines) + "\n"
