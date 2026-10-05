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
* **Some issues are never listed**: ones already solved (a linked pull request
  was merged, even if the issue stayed open), ones someone has taken (an
  assignee who is active on it, or a "taken" or "in progress" label), things
  that aren't tasks ("looking for co-maintainers", tracking and meta issues,
  epics), ones opened more than a year ago, and batches one account filed from
  a template or a script (the "add a Japanese idiom" pattern). `find` also
  skips repositories that are both brand new and tiny.
* **Every listed issue says who is already on it**: distinct people with an
  open pull request, a recent "can I work on this?", or an assignment that
  went quiet (`on_it_text`). Issues nobody is on come first; an issue with
  `CROWDED` people on it is not listed.
* **The issue score only orders.** It is a transparent sum over labels,
  recency, docs or tests work, special setup (Windows, a GPU, a cloud
  account, compiler internals), discussion size and where outsider work has
  landed, and every point it adds comes with a plain-English line in `why`. It
  makes no claim beyond that list.

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
from difflib import SequenceMatcher
from itertools import pairwise
from typing import Any

import httpx

from holt.agent import landing as landing_mod
from holt.agent.landing import Area
from holt.agent.people import MAINTAINER_ASSOCIATIONS
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
    # Who is already on it: distinct people with an open pull request, a
    # recent "can I work on this?", or an assignment gone quiet.
    people: int = 0
    open_prs: int = 0

    @property
    def on_it(self) -> str:
        return on_it_text(self.people, self.open_prs)

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "title": self.title, "url": self.url,
                "labels": list(self.labels), "created_at": self.created_at,
                "comments": self.comments, "why": list(self.why),
                "people": self.people, "open_prs": self.open_prs, "on_it": self.on_it}


def on_it_text(people: int, open_prs: int) -> str:
    """How many are already on an issue, in words: "Nobody on it yet", "1 open
    pull request", "2 people already on it, 1 open pull request". The web and
    the CLI both show this line."""
    if not people and not open_prs:
        return "Nobody on it yet"
    prs = f"{open_prs} open pull request{'s' if open_prs != 1 else ''}"
    if people <= open_prs:
        return prs
    who = f"{people} {'person' if people == 1 else 'people'} already on it"
    return f"{who}, {prs}" if open_prs else who


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
    # Logins the pull request history shows are on the team, for those whose
    # association on an issue hides it (private org members read CONTRIBUTOR).
    team: frozenset[str] = frozenset()


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
  author { login } authorAssociation
  repository { nameWithOwner isArchived }
  labels(first:15) { nodes { name } }
  assignees(first:5) { totalCount nodes { login } }
  comments { totalCount }
  recent: comments(last:10) { nodes { createdAt body author { login } } }
  closedByPullRequestsReferences(first:5, includeClosedPrs:true) { nodes { ...LinkedPR } }
  timelineItems(last:15, itemTypes:[CROSS_REFERENCED_EVENT, CONNECTED_EVENT, ASSIGNED_EVENT]) {
    nodes {
      ... on CrossReferencedEvent { source { ... on PullRequest { ...LinkedPR } } }
      ... on ConnectedEvent { subject { ... on PullRequest { ...LinkedPR } } }
      ... on AssignedEvent { createdAt assignee { ... on User { login } } }
    }
  }
}
fragment LinkedPR on PullRequest {
  number state author { login } repository { nameWithOwner }
}
"""

# Two views of one repository in one call: issues carrying a beginner label
# (search, so label spelling is case-insensitive), and the most recently active
# open issues, where unlabelled small fixes and odd label spellings turn up.
# `mergers` is who merged recent pull requests: the team, even members whose
# association reads CONTRIBUTOR to a token outside a private org. `assigned` is
# the open issues search says are assigned: GraphQL leaves an assignee whose
# account GitHub hides out of `assignees`, but search still counts them. It
# must be `assignee:*`: search ignores `-no:assignee` and `has:assignee` and
# answers every open issue.
REPO_ISSUES = ISSUE_FIELDS + """
query($owner:String!, $name:String!, $q:String!, $assigned:String!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    nameWithOwner isArchived
    issues(states:OPEN, first:40, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { ...StarterFields }
    }
    mergers: pullRequests(states:MERGED, last:30) {
      nodes { mergedBy { login __typename } }
    }
  }
  labelled: search(query:$q, type:ISSUE, first:50) {
    nodes { ...StarterFields }
  }
  assigned: search(query:$assigned, type:ISSUE, first:100) {
    nodes { ... on Issue { number } }
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
        repository { nameWithOwner isArchived isFork stargazerCount createdAt }
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
        nameWithOwner isArchived isFork stargazerCount createdAt
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

# Bump when a change alters which issues are listed, or their order, for the
# same GitHub answer. The server stores it with every cached list and fetches
# lists from older rules again instead of serving them.
RULES_VERSION = 3

# Only issues touched this recently count as alive.
ACTIVE_DAYS = 180
# Discussion past this size usually means the problem is not a first issue,
# whatever the label says.
LONG_DISCUSSION = 12
# A claim ("can I work on this?") younger than this means the issue is taken;
# older, it is probably abandoned.
CLAIM_FRESH_DAYS = 45
# This many people already on an issue is a stampede: another newcomer joining
# it will likely waste their time, so it is not listed.
CROWDED = 3
# An issue opened longer ago than this has usually been passed over for a
# reason, whatever its label says.
MAX_ISSUE_AGE_DAYS = 365
# This many issues from one account, near-identical or filed seconds apart, are
# a template or a script, not a maintainer picking out starter work.
FARM_MIN_ISSUES = 4
FARM_TITLE_SIMILARITY = 0.6
FARM_BURST_SECONDS = 120
MAX_BODY = 20000


def _norm(label: str) -> str:
    label = re.sub(r":[a-z0-9_+-]+:", " ", label.lower())  # :emoji: codes
    label = re.sub(r"[^a-z0-9]+", " ", label)
    return " ".join(label.split())


_BEGINNER = re.compile(r"\b(good first (issue|bug|pr|contribution|task|feature)|first timers? only|"
                       r"beginners?( friendly)?|good for (beginners|newcomers)|"
                       r"newcomers?|starter|first contribution)\b")
_EASY = re.compile(r"\b(easy|trivial|low hanging fruit|size (xs|s|small)|small)\b")
_HELP = re.compile(r"\b(help wanted|up for grabs|contributions? welcome|prs? welcome)\b")
_HACK = re.compile(r"^hacktoberfest$")
# Labels saying someone already has it, e.g. React's "good first issue (taken)".
_TAKEN = re.compile(r"(?<!not )(?<!un )\b(taken|claimed|assigned|in progress|"
                    r"work in progress|wip|being worked on|working on it|has (a )?pr|"
                    r"pr (open|opened|exists|submitted|pending|in progress)|linked pr)\b")
# Labels saying the issue is not ready for anyone, let alone a newcomer.
_NOT_READY = re.compile(r"\b(wontfix|won t fix|invalid|duplicate|question|discussion|"
                        r"blocked|on hold|needs design|needs decision|rfc|proposal|stale)\b")
_SMALL_TITLE = re.compile(r"\b(typos?|spelling|misspel\w*|docs?|documentation|readme|"
                          r"docstrings?|broken links?|dead links?|grammar|wording|"
                          r"examples?|translation)\b", re.I)
# "take", "pick" and "tackle" need an object: "I'll take another look" is no claim.
_TAKE = r"(take|pick|tackle) (this|it|up|on)"
_CLAIM = re.compile(rf"\b(i(['’]d| would) (like|love) to (work on|{_TAKE})|"
                    rf"can i (work on|try|{_TAKE})|may i (work on|take (this|it|up|on))|"
                    rf"i(['’]ll| will) (work on|{_TAKE})|"
                    r"(assign|allot) (this|it|the issue) to me|(please )?assign me|"
                    r"i(['’]m| am) (working on|on|taking|picking up) (this|it))\b", re.I)
# A later comment handing the issue back ("I'm no longer working on this").
_RELEASE = re.compile(r"\b(no longer (working|able|have time)|not working on (this|it)|"
                      r"(un-?assign|unassigning)|feel free to (take|pick|work)|"
                      r"(free|open|available|up for grabs) (again|for anyone)|"
                      r"anyone (can|is welcome to) (take|pick|work))\b", re.I)

# Not a task at all: calls for maintainers, tracking and meta issues, epics.
_NON_TASK_TITLE = re.compile(
    r"\b(looking for|seeking|searching for|call for|recruiting|need(ing)?)"
    r"( a| new| more| additional)* (co-?)?maintainers?\b|"
    r"\b(co-?)?maintainers? (wanted|needed)\b|\btracking issue\b|\bumbrella issue\b|"
    r"\bmeta[- ]issue\b|^\W*(meta|epic|tracking|umbrella|roadmap)\b", re.I)
_NON_TASK_LABEL = re.compile(r"\b(meta|tracking( issue)?|tracker|epic|umbrella|roadmap|"
                             r"announcement)\b")
# Labels saying it is harder than a first issue.
_HARD = re.compile(r"\b(hard|difficult|complex|advanced|expert|difficulty (medium|high)|"
                   r"complexity (medium|high)|size (l|xl|large)|e medium|effort (high|large))\b")
# Setup a beginner usually doesn't have, spotted in the title or a label. Each
# is (the line shown, title pattern, label pattern).
_SETUP = [
    ("Needs Windows",
     re.compile(r"\b(on|in|under|for) windows\b|^\W*windows\s*[:\]]|\bwindows[ -]?(1[01]|7|8|xp|"
                r"only|specific|terminal|registry|defender)\b|\bwin(32|64)\b|\bwsl2?\b|"
                r"\bpowershell\b", re.I),
     re.compile(r"\b(windows|win32|wsl)\b")),
    ("Needs a Mac",
     re.compile(r"\b(macos|mac os|os x|osx|xcode|on (a )?mac|ios|ipados|swiftui)\b", re.I),
     re.compile(r"\b(macos|mac|osx|darwin|ios)\b")),
    ("Needs a GPU",
     re.compile(r"\b(gpus?|cuda|rocm|nvidia|vulkan|directx|opengl|tpus?)\b", re.I),
     re.compile(r"\b(gpu|cuda|rocm|nvidia)\b")),
    ("Needs special hardware",
     re.compile(r"\b(hardware|firmware|bluetooth|usb|serial port|raspberry pi|arduino|"
                r"printers?|microcontrollers?|fpga|sonos|chromecast|zigbee|z-wave)\b", re.I),
     re.compile(r"\b(hardware|firmware|bluetooth|usb)\b")),
    ("Needs a cloud account",
     re.compile(r"\b(aws|s3|gcp|google cloud|azure|ec2|bigquery|dynamodb)\b", re.I),
     re.compile(r"\b(aws|s3|gcp|azure)\b")),
    ("Needs a Kubernetes cluster",
     re.compile(r"\b(kubernetes|k8s|kubectl|openshift|eks|gke|aks)\b", re.I),
     re.compile(r"\b(kubernetes|k8s)\b")),
    ("Deep compiler work",
     re.compile(r"\b(compiler|type ?checker|typecheck\w*|codegen|code generation|llvm|"
                r"borrow checker|ambient|declaration emit|type inference|bytecode|jit|"
                r"monomorphi[sz]ation|register allocation)\b", re.I),
     re.compile(r"\b(compiler|codegen|type checker|typechecker|llvm)\b")),
]

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
        if _TAKEN.search(label):
            kinds.add("taken")
    return kinds


# The kinds of contribution a profile can ask for, and how to spot each on an
# issue from its labels and title. "code" is everything that isn't one of the
# others, plus issues labelled as a bug, feature or refactor.
CONTRIBUTION_TYPES = ("code", "docs", "tests", "design", "translations")
_AREA_LABELS = {
    "docs": re.compile(r"\b(docs?|documentation|readme|docstrings?|tutorials?|examples?)\b"),
    "tests": re.compile(r"\b(tests?|testing|coverage|unit tests?|e2e)\b"),
    "design": re.compile(r"\b(design|ui|ux|ui ux|css|styling|a11y|accessibility|icons?|logo)\b"),
    "translations": re.compile(r"\b(translations?|i18n|l10n|locali[sz]ation)\b"),
}
_AREA_TITLES = {
    "docs": re.compile(r"\b(docs?|document\w*|readme|docstrings?|typos?|tutorial)\b", re.I),
    "tests": re.compile(r"\b(tests?|testing|test coverage|unit tests?)\b", re.I),
    "design": re.compile(r"\b(ui|ux|css|styling|dark mode|layout|icons?|logo)\b", re.I),
    "translations": re.compile(r"\b(translat\w*|i18n|l10n|locali[sz]\w*)\b", re.I),
}
_CODE_LABELS = re.compile(r"\b(bug|feature|enhancement|refactor\w*|performance|type bug|"
                          r"kind bug|kind feature)\b")


def is_beginner_issue(labels: Iterable[str]) -> bool:
    """True when the maintainers labelled the issue for first-timers ("good
    first issue" and its spellings). What a newcomer's profile keeps."""
    return "beginner" in label_kinds(labels)


def issue_areas(labels: Iterable[str], title: str = "") -> list[str]:
    """Which of `CONTRIBUTION_TYPES` an issue looks like, from its labels and
    title. Ordering only: it never decides whether an issue is shown."""
    normed = [_norm(label) for label in labels]
    found = [area for area, pattern in _AREA_LABELS.items()
             if any(pattern.search(label) for label in normed)
             or _AREA_TITLES[area].search(title or "")]
    if not found or any(_CODE_LABELS.search(label) for label in normed):
        found.insert(0, "code")
    return found


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _linked_prs(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull requests in this repository that close or mention the issue.

    A pull request in another repository ("see upstream #12") is not work on
    this issue, so it is left out when its repository is known.
    """
    repo = ((node.get("repository") or {}).get("nameWithOwner") or "").lower()
    prs = [pr for pr in (node.get("closedByPullRequestsReferences") or {}).get("nodes") or []
           if pr]
    for item in (node.get("timelineItems") or {}).get("nodes") or []:
        pr = (item or {}).get("source") or (item or {}).get("subject")
        if pr and pr.get("state"):
            prs.append(pr)
    unique: dict[Any, dict[str, Any]] = {}
    for pr in prs:
        there = ((pr.get("repository") or {}).get("nameWithOwner") or "").lower()
        if repo and there and there != repo:
            continue
        # One pull request often shows up twice: as the closing reference and
        # as a cross-reference.
        unique.setdefault(pr.get("number") or (pr.get("state"), _login(pr)), pr)
    return list(unique.values())


def _login(thing: dict[str, Any] | None) -> str:
    return (((thing or {}).get("author") or {}).get("login") or "").lower()


def _live_claims(node: dict[str, Any]) -> dict[str, datetime]:
    """Who asked to work on this in the recent comments, and when, minus claims
    handed back. A release from the claimer drops their claim; a release from
    anyone else ("feel free to take it") drops them all."""
    claims: dict[str, datetime] = {}
    comments = [c for c in (node.get("recent") or {}).get("nodes") or [] if c]
    for i, c in enumerate(sorted(comments, key=lambda c: c["createdAt"])):
        body = c.get("body") or ""
        who = _login(c) or f"#{i}"  # a deleted account is still someone
        if _CLAIM.search(body):
            claims[who] = _ts(c["createdAt"])
        elif claims and _RELEASE.search(body):
            if who in claims:
                del claims[who]
            else:
                claims.clear()
    return claims


@dataclass(slots=True)
class OnIt:
    people: int
    open_prs: int
    # Days since the latest claim too old to count, if any.
    stale_claim_days: float | None


def on_it(node: dict[str, Any], prs: Sequence[dict[str, Any]], as_of: datetime
          ) -> OnIt | None:
    """Who is already working on the issue, or None when it is taken: someone
    assigned in the last `CLAIM_FRESH_DAYS` days, or an assignee who has
    commented or opened a pull request since. An assignee who went quiet is
    counted, not trusted."""
    def age(when: datetime) -> float:
        return (as_of - when).total_seconds() / 86400

    open_prs = [pr for pr in prs if pr.get("state") == "OPEN"]
    authors = {_login(pr) or f"pr#{i}" for i, pr in enumerate(open_prs)}
    claims = _live_claims(node)
    fresh = {who for who, when in claims.items() if age(when) <= CLAIM_FRESH_DAYS}
    stale = [age(when) for who, when in claims.items() if who not in fresh]
    people = authors | fresh

    assignees = node.get("assignees") or {}
    if assignees.get("totalCount"):
        logins = {(n.get("login") or "").lower() for n in assignees.get("nodes") or [] if n}
        if not logins:
            return None  # can't tell who, so can't tell they went quiet
        assigned_at: dict[str, datetime] = {}
        for item in (node.get("timelineItems") or {}).get("nodes") or []:
            who = ((item or {}).get("assignee") or {}).get("login")
            if who and item.get("createdAt"):
                assigned_at[who.lower()] = _ts(item["createdAt"])
        spoke = {_login(c) for c in (node.get("recent") or {}).get("nodes") or []
                 if c and age(_ts(c["createdAt"])) <= CLAIM_FRESH_DAYS}
        for who in logins:
            if who in authors or who in spoke or (
                    who in assigned_at and age(assigned_at[who]) <= CLAIM_FRESH_DAYS):
                return None
        people |= logins
    return OnIt(people=len(people), open_prs=len(open_prs),
                stale_claim_days=min(stale) if stale else None)


def _title_words(title: str) -> list[str]:
    stop = {"a", "an", "the", "to", "in", "of", "for", "on", "and", "with"}
    return [w for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
            if w not in stop and not w.isdigit()]


def farmed_issues(nodes: Iterable[dict[str, Any]],
                  team: Iterable[str] = ()) -> set[int]:
    """Numbers of issues that one account filed as a batch: at least
    `FARM_MIN_ISSUES` with near-identical titles ("Add a Japanese idiom", "Add
    a Korean idiom", ...) or created seconds apart by a script. Issues with no
    known author are never counted.

    A maintainer scripting a batch of starter issues is how many projects get
    ready for Hacktoberfest, so the burst rule skips the repository's own team:
    an OWNER, MEMBER or COLLABORATOR association, or a login in `team`."""
    team = {login.lower() for login in team}
    by_author: dict[str, dict[int, dict[str, Any]]] = {}
    maintainers: set[str] = set()
    for node in nodes:
        login = ((node or {}).get("author") or {}).get("login")
        if login and "number" in node:
            by_author.setdefault(login.lower(), {})[node["number"]] = node
            if node.get("authorAssociation") in MAINTAINER_ASSOCIATIONS:
                maintainers.add(login.lower())
    farmed: set[int] = set()
    for login, issues in by_author.items():
        if len(issues) < FARM_MIN_ISSUES:
            continue
        nums = sorted(issues)
        # Near-identical titles: each joins the first group whose first title
        # it resembles.
        groups: list[tuple[list[str], list[int]]] = []
        for n in nums:
            words = _title_words(issues[n].get("title") or "")
            if not words:
                continue
            for first, members in groups:
                if SequenceMatcher(None, first, words).ratio() >= FARM_TITLE_SIMILARITY:
                    members.append(n)
                    break
            else:
                groups.append((words, [n]))
        for _, members in groups:
            if len(members) >= FARM_MIN_ISSUES:
                farmed.update(members)
        if login in maintainers or login in team:
            continue
        # Scripted bursts: a run of issues each filed within seconds of the last.
        timed = sorted(nums, key=lambda n: _ts(issues[n]["createdAt"]))
        run = [timed[0]]
        for prev, n in pairwise(timed):
            gap = _ts(issues[n]["createdAt"]) - _ts(issues[prev]["createdAt"])
            if gap.total_seconds() <= FARM_BURST_SECONDS:
                run.append(n)
                continue
            if len(run) >= FARM_MIN_ISSUES:
                farmed.update(run)
            run = [n]
        if len(run) >= FARM_MIN_ISSUES:
            farmed.update(run)
    return farmed


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

    None also covers issues someone has already taken (assignee, a "taken" or
    "in progress" label, a claim in the last `CLAIM_FRESH_DAYS` days that was
    not handed back) and issues opened over `MAX_ISSUE_AGE_DAYS` ago. Every
    point comes with a sentence in `why`, positives first.
    """
    if node.get("locked") or (node.get("repository") or {}).get("isArchived"):
        return None
    prs = _linked_prs(node)
    if any(pr.get("state") == "MERGED" for pr in prs):
        return None  # solved, even if nobody closed the issue
    busy = on_it(node, prs, as_of)
    if busy is None or busy.people >= CROWDED:
        return None
    if (as_of - _ts(node["createdAt"])).days > MAX_ISSUE_AGE_DAYS:
        return None
    updated = _ts(node.get("updatedAt") or node["createdAt"])
    idle = (as_of - updated).total_seconds() / 86400
    if idle > ACTIVE_DAYS:
        return None

    labels = [n["name"] for n in (node.get("labels") or {}).get("nodes") or [] if n]
    kinds = label_kinds(labels)
    if kinds & {"not_ready", "taken"}:
        return None
    if _NON_TASK_TITLE.search(node.get("title") or "") or any(
            _NON_TASK_LABEL.search(_norm(label)) for label in labels):
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

    small_fix = bool(why) and why[0].startswith("Looks like a small fix")
    areas = issue_areas(labels, title)
    if not small_fix and areas[0] in ("docs", "tests"):
        score += 1
        why.append(f"{areas[0].capitalize()} work")

    if any(_HARD.search(_norm(label)) for label in labels):
        score -= 2
        cautions.append(f"Marked as harder (“{label_named(_HARD)}”)")
    repo = (node.get("repository") or {}).get("nameWithOwner", "")
    whole_repo = re.sub(r"[^a-z0-9]+", " ", repo.lower())
    normed = [_norm(label) for label in labels]
    setup = [line for line, in_title, in_label in _SETUP
             if (in_title.search(title) or any(in_label.search(n) for n in normed))
             and not in_title.search(whole_repo)]  # a Kubernetes project needs a cluster
    score -= 2 * min(len(setup), 2)
    cautions += setup

    if landing and (area := _mentioned_area(f"{title}\n{body}", landing, repo)):
        score += 2
        why.append(f"Mentions {area.path}/, where {area.landed} of {area.attempted} "
                   "pull requests from outside contributors were merged")

    opened = (as_of - _ts(node["createdAt"])).total_seconds() / 86400
    if opened <= 30:
        score += 1
        why.append(f"Opened {_ago(opened)}")
    if idle <= 14:
        score += 1.5
        if opened > 30:
            why.append(f"Active recently (last update {_ago(idle)})")
    elif idle <= 60:
        score += 0.5
        if opened > 30:
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

    if busy.people or busy.open_prs:
        # Ordering puts these after every free issue; the points carry that
        # into `find`, which weighs a repository by its best issues.
        score -= 2 * min(max(busy.people, busy.open_prs), 3)
    elif busy.stale_claim_days is not None:
        cautions.append(f"Someone asked to work on this {_ago(busy.stale_claim_days)}; "
                        "ask whether it is still free before you start")

    number = node["number"]
    issue = StarterIssue(
        number=number,
        title=title,
        url=node.get("url") or f"https://github.com/{repo}/issues/{number}",
        labels=labels,
        created_at=node["createdAt"],
        comments=comments,
        why=why + cautions,
        people=busy.people,
        open_prs=busy.open_prs,
    )
    return round(score, 2), issue


def rank(nodes: Iterable[dict[str, Any]], as_of: datetime, *,
         landing: Sequence[Area] = (), hacktoberfest: bool = False,
         limit: int = 20, team: Iterable[str] = ()) -> list[tuple[float, StarterIssue]]:
    """Deduplicate, drop farmed batches, score and sort: issues nobody is on
    first, then by score. Ties go to the newer issue, then the number. `nodes` are one repository's issues;
    `team` is passed to `farmed_issues`."""
    unique: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if node and "number" in node:
            unique.setdefault(node["number"], node)
    farmed = farmed_issues(unique.values(), team)
    scored: list[tuple[float, StarterIssue]] = []
    for number, node in unique.items():
        if number in farmed:
            continue
        if result := score_issue(node, as_of, landing=landing, hacktoberfest=hacktoberfest):
            scored.append(result)
    scored.sort(key=lambda pair: (bool(pair[1].people or pair[1].open_prs), -pair[0],
                                  -_ts(pair[1].created_at).timestamp(), pair[1].number))
    return scored[:limit]


# ---------------------------------------------------------------------------
# One repository


def _scored_issues(repo: str, transport: GitHubGraphQL, as_of: datetime, limit: int,
                   landing: Sequence[Area], hacktoberfest: bool, team: Iterable[str] = ()
                   ) -> list[tuple[float, StarterIssue]]:
    owner, _, name = normalise(repo).partition("/")
    labels = ",".join(SEARCH_LABELS)
    q = (f"repo:{owner}/{name} is:issue is:open no:assignee label:{labels} "
         f"created:>{_oldest_issue_date(as_of)}")
    data = transport.query(REPO_ISSUES, owner=owner, name=name, q=q,
                           assigned=f"repo:{owner}/{name} is:issue is:open assignee:* "
                                    "sort:updated-desc")
    repository = data.get("repository")
    if repository is None:  # the search half answered, so the base class did not raise
        raise RepoNotFound(f"{owner}/{name}")
    if repository.get("isArchived"):
        return []
    nodes = [*((data.get("labelled") or {}).get("nodes") or []),
             *((repository.get("issues") or {}).get("nodes") or [])]
    assigned = {n["number"] for n in (data.get("assigned") or {}).get("nodes") or []
                if n and "number" in n}
    nodes = [_hidden_assignee(n) if n and n.get("number") in assigned else n for n in nodes]
    return rank(nodes, as_of, landing=landing, hacktoberfest=hacktoberfest, limit=limit,
                team={*team, *mergers(repository)})


def _hidden_assignee(node: dict[str, Any]) -> dict[str, Any]:
    """An issue search calls assigned whose `assignees` read empty: the assignee
    is an account GitHub hides. Who they are and when they were assigned are
    hidden too, so it reads as taken (`on_it`)."""
    if (node.get("assignees") or {}).get("totalCount"):
        return node
    return {**node, "assignees": {"totalCount": 1, "nodes": []}}


def mergers(repository: dict[str, Any]) -> set[str]:
    """People who merged the repository's recent pull requests (bots aside):
    merging needs write access."""
    return {m["login"] for pr in (repository.get("mergers") or {}).get("nodes") or []
            if (m := (pr or {}).get("mergedBy")) and m.get("login")
            and m.get("__typename") == "User"}


def starter_issues(repo: str, token: str | None, limit: int = 20,
                   as_of: datetime | None = None, *,
                   landing: Sequence[Area] = (), hacktoberfest: bool = False,
                   transport: GitHubGraphQL | None = None) -> list[StarterIssue]:
    """Open issues in `repo` that suit a newcomer and nobody has taken, best first.

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
        "first_time_merged_authors": signals.distinct_first_timer_merged_authors,
        "no_reply": signals.outsider_ignored,
        "median_first_response_hours": signals.median_first_response_hours,
    }


def rules_screen(transport: GitHubGraphQL, as_of: datetime,
                 days: int = DEFAULT_CONTRIBUTOR_DAYS) -> Callable[[str], RepoScreen]:
    """`discover`'s free screen as a `find` screen: one page of pull-request
    threads, arithmetic only, plus where outsider work landed in that page."""
    from holt import discover
    from holt.agent import people
    from holt.agent.signals import build_threads

    def screen(repo: str) -> RepoScreen:
        screened, records = discover.screen_slug(repo, transport, as_of, days)
        landing = landing_mod.compute(build_threads(records))
        return RepoScreen(verdict=screened.verdict, stats=_stats_subset(screened.signals),
                          landing=list(landing.landed), team=people.maintainers(records))

    return screen


def _oldest_issue_date(as_of: datetime) -> str:
    return (as_of - timedelta(days=MAX_ISSUE_AGE_DAYS)).date().isoformat()


def issue_source_queries(languages: Sequence[str], hacktoberfest: bool,
                         as_of: datetime) -> list[str]:
    """Issue search, one query per language (GitHub ANDs `language:`)."""
    since = (as_of - timedelta(days=ACTIVE_DAYS // 2)).date().isoformat()
    label = "hacktoberfest" if hacktoberfest else ",".join(SOURCE_LABELS)
    base = (f"is:issue is:open no:assignee -linked:pr archived:false label:{label} "
            f"updated:>{since} created:>{_oldest_issue_date(as_of)}")
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
# A repository younger than this with fewer stars than that is too new and too
# small to have a track record with newcomers, whatever one page of pull
# requests says.
NEW_REPO_DAYS = 180
TINY_REPO_STARS = 200


def brand_new_and_tiny(repo: dict[str, Any], as_of: datetime) -> bool:
    created = repo.get("createdAt")
    if not created:
        return False
    young = (as_of - _ts(created)).days < NEW_REPO_DAYS
    return young and (repo.get("stargazerCount") or 0) < TINY_REPO_STARS


def source_candidates(transport: GitHubGraphQL, languages: Sequence[str],
                      topics: Sequence[str], hacktoberfest: bool, as_of: datetime,
                      max_repos: int) -> list[str]:
    """Candidate repositories, most promising first.

    Weight: two per matching issue from issue search (capped), plus the
    repository's open beginner-labelled issue count from repository search
    (capped). Issue search cannot filter by topic, so it is skipped when topics
    are given. Archived, forked, and brand-new tiny repositories are skipped.
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
                    or (repo.get("stargazerCount") or 0) < MIN_ISSUE_SOURCE_STARS
                    or brand_new_and_tiny(repo, as_of)):
                continue
            hits[repo["nameWithOwner"]] = hits.get(repo["nameWithOwner"], 0) + 1
        for slug, n in hits.items():
            add(slug, 2 * min(n, 5))
    for node in (n for page in repo_pages for n in page):
        if (not node or node.get("isArchived") or node.get("isFork")
                or brand_new_and_tiny(node, as_of)):
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
                                hacktoberfest, result.team)
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
        parts.append(f"{merged} of {tried} recent pull requests from outside "
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
        lines.append(f"{indent}  {issue.on_it}")
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
    lines += ["Each repository below merges pull requests from outside contributors "
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
