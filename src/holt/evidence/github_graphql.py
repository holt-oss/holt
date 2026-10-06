"""Live GitHub evidence, via GraphQL.

REST needs roughly four calls per pull request (the PR, its reviews, its
comments, its files). At 5,000 requests/hour that exhausts the budget well
before the pool is crawled. One GraphQL query returns a page of PRs with all
four, so the same crawl costs a couple of hundred points instead.

A pull request is decomposed into *events*, not stored whole. A PR opened in
April and merged in July is two facts with two timestamps: the agent may see
the first and must not see the second. Storing the PR as a single record with
a single timestamp would force a choice between leaking the merge and hiding
the thread. Event decomposition removes the choice.
"""

from __future__ import annotations

import base64
import contextvars
import logging
import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from holt.about import language_shares, license_name
from holt.evidence.errors import (
    AuthError,
    Forbidden,
    RateLimited,
    RepoNotFound,
    UpstreamError,
)
from holt.evidence.provider import EvidenceProvider
from holt.types import EvidenceRecord, Window

API = "https://api.github.com/graphql"

log = logging.getLogger(__name__)

# A pull request page asks for files, reviews and comments on 25 PRs at once,
# and on a busy repository GitHub can take well over thirty seconds to build it.
# The old 30s client timeout turned exactly those repositories -- the popular
# ones people ask about most -- into failures.
TIMEOUT_S = 60.0
HEAVY_TIMEOUT_S = 120.0

# Transient failures (5xx, timeouts, dropped connections) are retried with
# exponential backoff. GitHub answers an expensive GraphQL query with a 502
# more often than one would like, and the second try usually succeeds.
MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 1.5

# A secondary rate limit asks us to wait. Short waits are worth sitting out;
# longer ones go back to the caller as `RateLimited(retry_after)`, because a web
# request cannot hang for ten minutes.
MAX_RATE_LIMIT_WAIT_S = 60.0
# GitHub's advice for a secondary limit that names no wait: at least a minute.
SECONDARY_WAIT_S = 60.0
# How GitHub words a secondary limit ("abuse detection" is the older name).
SECONDARY_WORDS = ("secondary rate limit", "abuse detection", "rate limit")

# Comment and review bodies carry the signal Holt actually reads: tone, intent,
# whether a maintainer engaged. Four thousand characters is far more than any of
# that needs. What blows past it is log dumps and stack traces -- one observed
# comment ran to 74,000 characters -- which cost a judge download size and cost
# the model context without changing a single judgement. Truncation is recorded
# on the record so a reader is never silently shown a partial quote.
MAX_BODY_CHARS = 4000

_REPO_FIELDS = """\
    createdAt pushedAt isArchived isMirror isFork stargazerCount
    hasPullRequestsEnabled pullRequestCreationPolicy
    description homepageUrl primaryLanguage { name }
    nameWithOwner mirrorUrl parent { nameWithOwner }
    repositoryTopics(first:20) { nodes { topic { name } } }
    releases(first:10, orderBy:{field:CREATED_AT, direction:DESC}) {
      totalCount
      nodes { tagName name createdAt publishedAt isPrerelease }
    }
    defaultBranchRef {
      name
      target {
        ... on Commit { history(until:$until, first:1) { nodes { oid committedDate } } }
      }
    }
    forkCount licenseInfo { spdxId name } issues(states:OPEN) { totalCount }
    languages(first:3, orderBy:{field:SIZE, direction:DESC}) { totalSize edges { size node { name } } }
"""
REPO_META = """
query($owner:String!, $name:String!, $until:GitTimestamp!) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner, name:$name) {
""" + _REPO_FIELDS + """\
  }
}
"""

# The README as it stood at the cutoff, not as it stands today. Reading HEAD
# would hand the agent a document rewritten months after the window it is
# supposed to be reasoning about -- a leak that would never announce itself.
#
# Projects put these files in more places than the root, and name them in more
# ways than `README.md`: `.github/CONTRIBUTING.md` is GitHub's own recommended
# location, and Python projects often ship `README.rst`. Every candidate is
# asked for in one query (an aliased blob lookup each) and the first that
# exists wins, in the order listed.
README_CANDIDATES = (
    "README.md", "README.rst", "README", "README.txt", "README.markdown",
    "readme.md", "Readme.md", "README.MD", "readme.rst", ".github/README.md",
    "docs/README.md",
)
CONTRIBUTING_CANDIDATES = (
    "CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md",
    "CONTRIBUTING.rst", ".github/CONTRIBUTING.rst", "docs/CONTRIBUTING.rst",
    "CONTRIBUTING", "CONTRIBUTING.txt", "contributing.md",
    ".github/contributing.md", "docs/contributing.md", "Contributing.md",
    "CONTRIBUTING.MD", "docs/source/contributing.rst", "docs/contributing.rst",
)
# A project's rules on AI-written contributions, where it keeps them in a file
# of their own (agent/asks.py reads them). Blob lookups are free: adding paths
# doesn't change what the query costs.
AI_POLICY_CANDIDATES = (
    "AI_POLICY.md", ".github/AI_POLICY.md", "docs/AI_POLICY.md", "AI_USAGE_POLICY.md",
    "LLM_POLICY.md", ".github/LLM_POLICY.md", "AI-POLICY.md",
)
DOC_CANDIDATES = {"readme": README_CANDIDATES, "contributing": CONTRIBUTING_CANDIDATES,
                  "ai_policy": AI_POLICY_CANDIDATES}

# The stale bot's config (agent/stale.py), read in the same query: probot's
# file, and the workflow names actions/stale is kept under on the golden set.
# Every workflow's text would be too much (pytorch's 156 come to 1.1 MB), so
# the query lists the folder's names too, and a workflow with "stale" in its
# name that isn't a candidate is read with a second, small query.
STALE_PROBOT = (".github/stale.yml", ".github/stale.yaml")
WORKFLOWS = ".github/workflows"
STALE_WORKFLOWS = (
    "stale.yml", "stale.yaml", "stale-bot.yml", "stale-issues.yml", "stale-prs.yml",
    "stale-pr.yml", "stale_issue.yml", "stale-issues-and-prs.yml", "close-stale.yml",
    "close-stale-issues.yml", "close-stale-prs.yml", "shared_stale.yml", "mark-stale.yml",
)
STALE_CANDIDATES = {"probot": STALE_PROBOT,
                    "actions": tuple(f"{WORKFLOWS}/{n}" for n in STALE_WORKFLOWS)}
MAX_STALE_FILES = 3


def _blob_fields(rev: str, candidates: dict[str, tuple[str, ...]],
                 aliases: dict[str, tuple[str, str]], prefix: str = "") -> list[str]:
    """An aliased blob lookup per candidate path at `rev`, filling `aliases`."""
    fields = []
    for kind, paths in candidates.items():
        for i, path in enumerate(paths):
            alias = f"{prefix}{kind}{i}"
            aliases[alias] = (kind, path)
            # rev is a hex sha or HEAD, and paths are our own constants or
            # names GitHub listed (checked by `_safe_path`): nothing here comes
            # from the user, so interpolating is safe.
            fields.append(
                f'{alias}: object(expression:"{rev}:{path}") {{ ... on Blob {{ text }} }}'
            )
    return fields


def _doc_fields(rev: str) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """The docs' and the stale bot's blob lookups at `rev`, and the workflow
    folder's names, with alias -> (kind, path). All free: no connections."""
    aliases: dict[str, tuple[str, str]] = {}
    fields = _blob_fields(rev, DOC_CANDIDATES, aliases)
    fields += _blob_fields(rev, STALE_CANDIDATES, aliases, prefix="stale_")
    aliases["workflows"] = ("workflows", WORKFLOWS)
    fields.append(f'workflows: object(expression:"{rev}:{WORKFLOWS}") '
                  "{ ... on Tree { entries { name } } }")
    return fields, aliases


def _repo_query(fields: list[str]) -> str:
    return (
        "query($owner:String!, $name:String!) {\n"
        "  rateLimit { cost remaining resetAt }\n"
        "  repository(owner:$owner, name:$name) {\n    "
        + "\n    ".join(fields)
        + "\n  }\n}\n"
    )


def docs_query(oid: str) -> tuple[str, dict[str, tuple[str, str]]]:
    """A query asking for every candidate path, and alias -> (kind, path)."""
    fields, aliases = _doc_fields(oid)
    return _repo_query(fields), aliases


def _safe_path(name: str) -> bool:
    return bool(name) and all(c.isalnum() or c in "._-" for c in name)


def _found_docs(repo: dict[str, Any], aliases: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """`{"readme": {"text", "path"} | None, ...}`: the first candidate that
    exists; `stale`, the stale config files found; and `stale_unlisted`, the
    workflows named for staleness that no candidate covered
    (`GitHubGraphQL._with_stale` reads those)."""
    found: dict[str, Any] = {kind: None for kind in DOC_CANDIDATES}
    stale: list[dict[str, str]] = []
    for alias, (kind, path) in aliases.items():  # dicts keep candidate order
        blob = repo.get(alias)
        if alias == "workflows" or not blob or not blob.get("text"):
            continue
        if alias.startswith("stale_"):
            stale.append({"kind": kind, "path": path, "text": blob["text"]})
        elif found[kind] is None:
            found[kind] = {"text": blob["text"], "path": path}
    names = [e.get("name") or "" for e in ((repo.get("workflows") or {}).get("entries") or [])]
    found["stale"] = stale
    found["stale_unlisted"] = [
        f"{WORKFLOWS}/{n}" for n in names
        if "stale" in n.lower() and n.endswith((".yml", ".yaml")) and _safe_path(n)
        and f"{WORKFLOWS}/{n}" not in STALE_CANDIDATES["actions"]][:MAX_STALE_FILES]
    return found


# Date filtering happens server-side. Ordering by newest and paging until the
# timestamps fall past the cutoff would burn most of the rate-limit budget on
# records the window filter then discards.
#
# What it costs: GitHub charges one point per hundred connections a query asks
# for, rounded. A page of 25 pull requests asks for the search plus five
# connections per PR (files, reviews, comments, labels, timeline) -- 126, so
# one point a page. A sixth per-PR connection would make it 151 and two
# points, doubling a report's spend. That is why the close event and commit
# references share one timeline window instead of having one each; the price is
# that ten or more commit references after a close can crowd the close event
# out, and then how the PR was closed is recorded as unknown.
#
# The timeline is also the slow part: it added seven to twelve seconds to a
# report's fetch when measured. The one-page screen that `discover` and `find`
# run over many repositories at once is only a pre-filter, so it uses
# PR_SEARCH_SCREEN, which leaves the timeline out; its closes then carry no
# `closed_by` keys at all, as in a capture that never asked.
_PR_TIMELINE = """\
        timelineItems(last:10, itemTypes:[CLOSED_EVENT, REFERENCED_EVENT]) {
          nodes {
            __typename
            ... on ClosedEvent {
              createdAt actor { login __typename }
              closer { __typename ... on Commit { oid } ... on PullRequest { number } }
            }
            ... on ReferencedEvent {
              createdAt actor { login __typename }
              commit { oid } commitRepository { nameWithOwner }
            }
          }
        }
"""
_PR_FIELDS = """\
        number title createdAt mergedAt closedAt merged
        additions deletions changedFiles isDraft authorAssociation
        author { login __typename }
        mergedBy { login __typename }
        labels(first:10) { nodes { name } }
        files(first:20) { nodes { path additions deletions } }
        reviews(first:20) {
          nodes { createdAt state body authorAssociation author { login __typename } }
        }
        comments(first:30) {
          nodes { createdAt body authorAssociation author { login __typename } }
        }
""" + _PR_TIMELINE
PR_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type:ISSUE, first:25, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
""" + _PR_FIELDS + """\
      }
    }
  }
}
"""
PR_SEARCH_SCREEN = PR_SEARCH.replace(_PR_TIMELINE, "")
# The sample's unit. A report keeps the newest `max_pages` x 25 pull requests,
# and the settle-window read stops at a multiple of 25 read (`_settled`). These
# were PR_SEARCH's page size; they stay the sample's boundaries whatever size
# the pages are read in, so the evidence doesn't depend on it.
PAGE_SIZE = 25

# A full report reads its pages in PR_PAGE, whose size is a variable, 29 at a
# time: 1 + 29 x 5 = 146 connections still rounds to one point, where 30 would
# be 151 and two (measured with `rateLimit(dryRun:true)`). The newest 200 then
# take 7 queries instead of 8, and the settle-window read a point less when it
# runs long. The screen keeps PR_SEARCH_SCREEN's 25: its recorded runs replay
# by query text.
PR_PAGE = """
query($q:String!, $cursor:String, $first:Int!) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type:ISSUE, first:$first, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
""" + _PR_FIELDS + """\
      }
    }
  }
}
"""
FETCH_SIZE = 29

# A report's first query: the repository facts, its docs at HEAD and the first
# page of pull requests, together, for the point each of the three used to cost.
# The facts add about six connections, so this page holds 28 (1 + 28 x 5 + 6 =
# 147, one point; 29 measured two).
#
# The docs are asked for at HEAD because the cutoff commit isn't known until
# this query answers. `LiveGitHubProvider` uses them only when HEAD is the
# cutoff commit (`oid` below is HEAD's); otherwise, as on a read as of a past
# date or after a push since the cutoff, it reads them at the cutoff commit as
# before.
OPENING_SIZE = 28
# How recent a cutoff must be for the opening query to ask for the docs at HEAD.
LIVE_WITHIN = timedelta(days=1)


def opening_query(docs: bool) -> tuple[str, dict[str, tuple[str, str]]]:
    """The first query of a full report, and its docs' alias -> (kind, path)."""
    fields, aliases = _doc_fields("HEAD") if docs else ([], {})
    repo_fields = _REPO_FIELDS.replace("... on Commit { history", "... on Commit { oid history")
    document = (
        "query($owner:String!, $name:String!, $until:GitTimestamp!, $q:String!, $first:Int!) {\n"
        "  rateLimit { cost remaining resetAt }\n"
        "  repository(owner:$owner, name:$name) {\n"
        + repo_fields
        + "".join(f"    {f}\n" for f in fields)
        + "  }\n"
        "  search(query:$q, type:ISSUE, first:$first) {\n"
        "    issueCount\n"
        "    pageInfo { hasNextPage endCursor }\n"
        "    nodes {\n"
        "      ... on PullRequest {\n"
        + _PR_FIELDS
        + "      }\n    }\n  }\n}\n"
    )
    return document, aliases


# A pull request page takes GitHub three to five seconds to build, and a report
# reads seven to fourteen of them: read one after another, they were nearly the
# whole of a check's minute. GitHub's search cursors are page offsets
# (`base64("cursor:28")` is the page after the first 28), so once the first
# page confirms that, the rest are asked for this many at a time. Bounded,
# because GitHub asks clients not to hammer it with concurrent requests on one
# token.
PAGE_CONCURRENCY = 4


# The timing cohort (agent/timing.py): outside pull requests opened 60 to 240
# days before the reading, for how long merges take. Only the dates and who
# opened each, a hundred a page with no connections inside, so a page costs
# one point. Read only when the report's own pages don't reach back that far.
# One page of the whole window, newest first, is all of it on most
# repositories. On a busy one it covers a week or two (kubernetes: 17-30
# July), and one fortnight can be a release freeze or a holiday, so the other
# pages are the newest of each older part of the window instead: three pages
# read three stretches months apart.
TIMING_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type:ISSUE, first:100, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number createdAt mergedAt isDraft authorAssociation
        author { login __typename }
        mergedBy { login __typename }
      }
    }
  }
}
"""
TIMING_PAGES = 3
TIMING_DAYS = (60, 240)  # agent/timing.COHORT_DAYS


def timing_query(repo_slug: str, cutoff: datetime,
                 days: tuple[float, float] = TIMING_DAYS) -> str:
    """Pull requests opened `days[0]` to `days[1]` days before the cutoff."""
    start = (cutoff - timedelta(days=days[1])).date().isoformat()
    end = (cutoff - timedelta(days=days[0])).date().isoformat()
    return f"repo:{repo_slug} is:pr created:{start}..{end} sort:created-desc"


def timing_parts(pages: int) -> list[tuple[float, float]]:
    """The older parts of the window the pages after the first read, in days."""
    lo, hi = TIMING_DAYS
    step = (hi - lo) / max(1, pages)
    return [(lo + k * step, lo + (k + 1) * step) for k in range(1, pages)]


def project_timing(repo_slug: str, nodes: Iterable[dict[str, Any]],
                   home: str | None = None) -> Iterator[EvidenceRecord]:
    """The cohort's pull requests: one record when each was opened, and one
    when it was merged. Their own id prefix and payload keys, so nothing that
    reads the main sample (threads, the team, landings) ever counts them."""
    home = home or repo_slug
    for pr in nodes:
        created = _ts(pr.get("createdAt"))
        if created is None or pr.get("number") is None:
            continue
        base = f"timing:{repo_slug}#{pr['number']}"
        url = f"https://github.com/{home}/pull/{pr['number']}"
        yield EvidenceRecord(base, "github", url, created, {
            "login": _login(pr.get("author")), "bot": _is_bot(pr.get("author")),
            "association": pr.get("authorAssociation"), "draft": bool(pr.get("isDraft")),
        })
        if merged := _ts(pr.get("mergedAt")):
            # Who merged it: merging takes write access, so they're on the team
            # (agent/timing.py), whatever GitHub's association says.
            by = pr.get("mergedBy")
            yield EvidenceRecord(f"{base}:landed", "github", url, merged,
                                 {"by": _login(by) if by else None, "by_bot": _is_bot(by)})


def timing_window(repo_slug: str, cutoff: datetime, source: str, **facts: Any) -> EvidenceRecord:
    """Where the cohort came from: "sample" (the report's own pages reach back
    that far) or "search", with how many pages and whether the search ran out."""
    return EvidenceRecord(
        f"timing:{repo_slug}:window", "github", f"https://github.com/{repo_slug}",
        cutoff - timedelta(days=TIMING_DAYS[0]), {"source": source, **facts})


def timing_source(created: list[datetime], full: bool, cutoff: datetime) -> str:
    """"sample" when the newest pages hold the whole history (they weren't
    full) or reach back past the cohort's window, else "search"."""
    start = cutoff - timedelta(days=TIMING_DAYS[1])
    if not full or (created and min(created) <= start):
        return "sample"
    return "search"


def read_timing(transport: Any, request: str, home: str, cutoff: datetime,
                pages: int = TIMING_PAGES) -> list[EvidenceRecord]:
    """The timing search's records, window record first: the newest page of
    the whole window, then (if it didn't hold it all) the newest page of each
    older part (`timing_parts`)."""
    found, complete = transport.search_timing(timing_query(home, cutoff), 1)
    read = 1
    if not complete:
        for part in timing_parts(pages):
            more, _ = transport.search_timing(timing_query(home, cutoff, part), 1)
            found += more
            read += 1
    unique = list({n.get("number"): n for n in found}.values())
    return [timing_window(request, cutoff, "search", pages=read, complete=complete,
                          read=len(unique)),
            *project_timing(request, unique, home=home)]


# Issues, for Path Finder. Decomposed the same way pull requests are: an issue
# opening is a pre-cutoff fact, and an issue being closed by somebody's merged
# pull request is a post-cutoff one. The two must not travel together.
ISSUE_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type:ISSUE, first:50, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Issue {
        number title body createdAt closedAt lastEditedAt
        author { login __typename }
        labels(first:12) { nodes { name } }
        comments { totalCount }
        closedByPullRequestsReferences(first:5, includeClosedPrs:true) {
          nodes { number mergedAt author { login __typename } }
        }
      }
    }
  }
}
"""

MAX_ISSUE_BODY = 4000

# Repository search, for `holt discover`. Sourcing only: these results are where
# candidates come from, and the output says so. Nothing downstream treats search
# rank as a signal — the screening pass re-derives everything it uses from the
# contribution history.
REPO_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { cost remaining resetAt }
  search(query:$q, type:REPOSITORY, first:25, after:$cursor) {
    repositoryCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Repository {
        nameWithOwner description stargazerCount pushedAt isArchived isFork
        primaryLanguage { name }
        goodFirstIssues: issues(states:OPEN, labels:["good first issue",
          "good-first-issue", "beginner", "first-timers-only", "easy"]) { totalCount }
      }
    }
  }
}
"""


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _body(text: str | None) -> tuple[str | None, bool, int]:
    """Return (possibly truncated body, was_truncated, original_length)."""
    if not text:
        return text, False, 0
    if len(text) <= MAX_BODY_CHARS:
        return text, False, len(text)
    return text[:MAX_BODY_CHARS], True, len(text)


def _login(actor: dict[str, Any] | None) -> str:
    """Deleted accounts come back as null; bots carry a distinct __typename."""
    if not actor:
        return "(ghost)"
    return actor.get("login") or "(ghost)"


def _is_bot(actor: dict[str, Any] | None) -> bool:
    if not actor:
        return False
    if actor.get("__typename") == "Bot":
        return True
    login = (actor.get("login") or "").lower()
    return login.endswith("[bot]") or login in {"dependabot", "renovate", "greenkeeper"}


def _message(response: httpx.Response) -> str:
    """What GitHub said in a refusal's body, shortened. Never holds a token."""
    try:
        body = response.json()
        text = body.get("message") if isinstance(body, dict) else None
        return str(text or response.text)[:200]
    except Exception:  # noqa: BLE001 - a body we cannot decode says nothing
        return ""


def _rate_limit(response: httpx.Response) -> tuple[float, bool] | None:
    """(seconds GitHub asks us to wait, whether it is a secondary limit), or
    None if this 403 or 429 is not a rate limit.

    The primary limit (the hourly budget) sends `x-ratelimit-remaining: 0`
    with a reset time. A secondary limit (too much at once) comes with points
    to spare: a `Retry-After`, or only its message. A 403 with none of those is
    GitHub refusing the request itself.
    """
    headers = response.headers
    after: float | None = None
    if (raw := headers.get("retry-after")) is not None:
        try:
            after = max(0.0, float(raw))
        except ValueError:
            after = None
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            reset = max(0.0, float(headers.get("x-ratelimit-reset") or "") - time.time())
        except ValueError:
            reset = SECONDARY_WAIT_S
        return max(reset, after or 0.0), False
    if after is not None:
        return after, True
    text = _message(response).lower()
    if response.status_code == 429 or any(word in text for word in SECONDARY_WORDS):
        return SECONDARY_WAIT_S, True
    return None


def _not_found_name(errors: list[dict[str, Any]]) -> str:
    for e in errors:
        message = str(e.get("message", ""))
        if "name '" in message:
            return message.split("name '", 1)[1].split("'", 1)[0]
    return "that repository"


@dataclass
class Opening:
    """What a report's first query read (`GitHubGraphQL.opening`)."""

    meta: dict[str, Any]  # as `repo_meta` returns it, plus HEAD's oid
    search: dict[str, Any] | None  # the first page of the pull request search
    docs: dict[str, Any] | None  # as `docs_at` returns them, read at HEAD
    head: str | None  # HEAD's commit, which `docs` were read at


class GitHubGraphQL:
    """Thin transport. Knows about auth, retries, pagination and rate limits.

    Failures come back as the typed errors in `holt.evidence.errors`. A
    response carrying both `errors` and `data` is kept -- GitHub does that when
    one node of a big page could not be resolved, and throwing away twenty-four
    good pull requests for one bad one is worse than reading what arrived. What
    was lost is recorded in `partial_errors`.
    """

    def __init__(
        self,
        token: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise AuthError(
                "GITHUB_TOKEN is not set. Live mode needs a token; "
                "use fixture or replay mode to run without one"
            )
        self._client = client or httpx.Client(timeout=TIMEOUT_S)
        self._sleep = sleep
        # Tries per query (see MAX_ATTEMPTS). A query GitHub times out on
        # costs it the same again each time, so background work asks less.
        self.attempts = max(1, attempts)
        self.remaining: int | None = None
        # Rate-limit points GitHub charged this transport, summed over every
        # query. What one report costs is the difference across its fetch.
        self.points_used = 0
        self.partial_errors: list[dict[str, Any]] = []
        # Pages are read on several threads at once (see PAGE_CONCURRENCY).
        self._lock = threading.Lock()

    def query(
        self, document: str, *, timeout: float | None = None, **variables: object
    ) -> dict[str, Any]:
        for attempt in range(1, self.attempts + 1):
            last = attempt == self.attempts
            try:
                response = self._client.post(
                    API,
                    headers={"Authorization": f"bearer {self.token}"},
                    json={"query": document, "variables": variables},
                    **({"timeout": timeout} if timeout else {}),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if last:
                    raise UpstreamError(f"{type(exc).__name__} after {attempt} tries") from exc
                self._backoff(attempt)
                continue

            status = response.status_code
            if status == 401:
                raise AuthError("401 Unauthorized")
            if status in (403, 429):
                limit = _rate_limit(response)
                # The body is never kept, so this line is the only record of
                # which kind of refusal it was.
                log.warning(
                    "GitHub answered %d: retry-after=%s x-ratelimit-remaining=%s (%s)",
                    status, response.headers.get("retry-after"),
                    response.headers.get("x-ratelimit-remaining"), _message(response))
                if limit is None:
                    raise Forbidden(_message(response) or "HTTP 403")
                wait, secondary = limit
                self._limited(wait, secondary)
                if last or wait > MAX_RATE_LIMIT_WAIT_S:
                    raise RateLimited(wait, secondary)
                self._sleep(wait)
                continue
            if status >= 500:
                if last:
                    raise UpstreamError(f"HTTP {status} after {attempt} tries")
                self._backoff(attempt)
                continue
            if status >= 400:
                raise UpstreamError(f"HTTP {status}")

            try:
                body = response.json()
            except ValueError as exc:
                if last:
                    raise UpstreamError("GitHub sent a response that was not JSON") from exc
                self._backoff(attempt)
                continue
            return self._data(body)
        raise UpstreamError("no attempts made")  # pragma: no cover

    def _data(self, body: dict[str, Any]) -> dict[str, Any]:
        errors = body.get("errors") or []
        data = body.get("data")
        types = {e.get("type") for e in errors}
        if "RATE_LIMITED" in types:
            raise RateLimited(None)
        content = {k: v for k, v in (data or {}).items() if k != "rateLimit"}
        # A report's opening query asks for a search beside the repository,
        # and the search still answers (empty) when the repository is missing.
        if content.get("repository", True) is None and any(
            e.get("type") == "NOT_FOUND" and e.get("path") == ["repository"] for e in errors
        ):
            raise RepoNotFound(_not_found_name(errors))
        if errors and (not content or all(v is None for v in content.values())):
            if "NOT_FOUND" in types:
                raise RepoNotFound(_not_found_name(errors))
            raise UpstreamError("; ".join(str(e.get("message", "")) for e in errors)[:300])
        if errors:
            log.warning("GitHub returned partial data: %s", errors)
        with self._lock:
            self.partial_errors.extend(errors)
            if limit := (data or {}).get("rateLimit"):
                self.remaining = limit["remaining"]
                self.points_used += limit.get("cost") or 0
        return data or {}

    def _limited(self, wait: float, secondary: bool) -> None:
        """GitHub just answered with a rate limit. For a subclass that shares
        its token with other readers (the server's pool); it may raise
        `RateLimited` to hand the wait back instead of sitting it out here."""

    def _delay(self, attempt: int) -> float:
        return BACKOFF_BASE_S * (2 ** (attempt - 1))

    def _backoff(self, attempt: int) -> None:
        self._sleep(self._delay(attempt))

    def repo_meta(self, owner: str, name: str, until: datetime) -> dict[str, Any]:
        repo = self.query(
            REPO_META, owner=owner, name=name, until=until.isoformat()
        ).get("repository")
        if repo is None:
            raise RepoNotFound(f"{owner}/{name}")
        return repo

    def docs_at(self, owner: str, name: str, oid: str) -> dict[str, Any]:
        """README and CONTRIBUTING at a specific commit, wherever they live.

        Returns `{"readme": {"text", "path"} | None, "contributing": ...}`.
        """
        document, aliases = docs_query(oid)
        repo = self.query(document, owner=owner, name=name).get("repository") or {}
        return self._with_stale(owner, name, oid, _found_docs(repo, aliases))

    def _with_stale(self, owner: str, name: str, rev: str,
                    found: dict[str, Any]) -> dict[str, Any]:
        """`found` with its stale config complete: a workflow named for
        staleness that no candidate covered is read with one more small query,
        only then; files that aren't a stale bot's are dropped."""
        stale = list(found.get("stale") or [])
        if extra := found.pop("stale_unlisted", None):
            more: dict[str, tuple[str, str]] = {}
            fields = _blob_fields(rev, {"actions": tuple(extra)}, more)
            got = self.query(_repo_query(fields), owner=owner, name=name).get("repository") or {}
            stale += [{"kind": kind, "path": path, "text": got[a]["text"]}
                      for a, (kind, path) in more.items() if (got.get(a) or {}).get("text")]
        found["stale"] = [f for f in stale
                          if f["kind"] == "probot" or "actions/stale@" in f["text"]][:MAX_STALE_FILES]
        return found

    def search_issues(self, q: str, max_pages: int = 6) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        for _ in range(max_pages):
            search = self.query(ISSUE_SEARCH, q=q, cursor=cursor)["search"]
            yield from (n for n in search["nodes"] if n)
            page = search["pageInfo"]
            if not page["hasNextPage"]:
                return
            cursor = page["endCursor"]

    def search_repositories(self, q: str, max_pages: int = 2) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        for _ in range(max_pages):
            search = self.query(REPO_SEARCH, q=q, cursor=cursor)["search"]
            yield from (n for n in search["nodes"] if n)
            page = search["pageInfo"]
            if not page["hasNextPage"]:
                return
            cursor = page["endCursor"]

    def opening(
        self, owner: str, name: str, until: datetime, q: str, size: int, docs: bool,
    ) -> Opening:
        """A report's first query: facts, docs at HEAD and the first `size` pull
        requests of search `q` (see OPENING_SIZE)."""
        document, aliases = opening_query(docs)
        data = self.query(document, timeout=HEAVY_TIMEOUT_S, owner=owner, name=name,
                          until=until.isoformat(), q=q, first=size)
        repo = data.get("repository")
        if repo is None:
            raise RepoNotFound(f"{owner}/{name}")
        meta = {k: v for k, v in repo.items() if k not in aliases}
        target = (meta.get("defaultBranchRef") or {}).get("target") or {}
        return Opening(
            meta=meta, search=data.get("search"),
            docs=(self._with_stale(owner, name, target.get("oid") or "HEAD",
                                   _found_docs(repo, aliases)) if docs else None),
            head=target.get("oid"),
        )

    def search_pull_requests(
        self, q: str, max_pages: int = 8, timeline: bool = True,
        wanted: Callable[[], int] | None = None, first: Future | None = None,
    ) -> Iterator[dict[str, Any]]:
        """The first `max_pages` x PAGE_SIZE results of a pull request search.

        `timeline=False` is the faster screening query. The nodes come back in
        the order one-page-at-a-time paging would give them, however many
        pages are in flight and whatever size they are read in. `wanted`,
        asked after each page is read, says how many more PAGE_SIZE steps are
        worth asking for ahead of the reader (by default, as many pages as
        PAGE_CONCURRENCY allows): a reader that may stop early uses it to keep
        unread pages, each a point, to a few. `first` is the first page,
        already asked for (by `first_page` or `opening`).
        """
        limit = max_pages * PAGE_SIZE
        pages = (self._pages(PR_PAGE, q, limit, FETCH_SIZE, wanted, first) if timeline
                 else self._pages(PR_SEARCH_SCREEN, q, limit, None, wanted, first))
        for nodes in pages:
            yield from (n for n in nodes if n)

    def search_timing(self, q: str, max_pages: int = TIMING_PAGES) -> tuple[list[dict[str, Any]], bool]:
        """The timing cohort's pages: (nodes, whether the search ran out)."""
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            search = self.query(TIMING_SEARCH, q=q, cursor=cursor)["search"]
            nodes += [n for n in search["nodes"] if n]
            page = search["pageInfo"]
            if not page["hasNextPage"]:
                return nodes, True
            cursor = page["endCursor"]
        return nodes, False

    def first_page(self, q: str) -> Future:
        """Start reading a search's first page now, for `search_pull_requests(first=)`."""
        return in_background(self._page, PR_PAGE, q, None, FETCH_SIZE)

    def _page(self, document: str, q: str, cursor: str | None,
              first: int | None) -> dict[str, Any]:
        sized = {} if first is None else {"first": first}
        return self.query(
            document, timeout=HEAVY_TIMEOUT_S, q=q, cursor=cursor, **sized
        )["search"]

    def _pages(
        self, document: str, q: str, limit: int, size: int | None,
        wanted: Callable[[], int] | None, first: Future | None = None,
    ) -> Iterator[list[dict[str, Any] | None]]:
        """The search's results at offsets [0, limit), a page's nodes at a time.

        `size` is how many a page asks for (PR_PAGE's `$first`), or None for a
        document whose size is fixed at PAGE_SIZE. The first page's size is
        whatever was asked for; each page after it starts where the one before
        ended, so the offsets read are the same for any sizes.
        """
        step = size or PAGE_SIZE

        def page(start: int, cursor: str | None) -> dict[str, Any]:
            return self._page(document, q, cursor, min(size, limit - start) if size else None)

        head = first.result() if first is not None else page(0, None)
        yield head["nodes"][:limit]
        info = head["pageInfo"]
        read = len(head["nodes"])
        if not info["hasNextPage"] or read >= limit:
            return
        cursor = info["endCursor"]
        if cursor == offset_cursor(read):
            # GitHub's count, when it has one, keeps a small repository from
            # being asked for pages it doesn't have. When the count runs short,
            # the paging below carries on from the last page.
            total = head.get("issueCount") or 0
            starts = deque(range(read, min(limit, max(total, read + 1)), step))
            pending: deque[tuple[int, Future]] = deque()
            pool = ThreadPoolExecutor(PAGE_CONCURRENCY, thread_name_prefix="holt-page")

            def top_up() -> None:
                ahead = (PAGE_CONCURRENCY if wanted is None
                         else math.ceil(wanted() * PAGE_SIZE / step))
                while starts and len(pending) < max(1, min(PAGE_CONCURRENCY, ahead)):
                    # Each page runs in a copy of the reader's context: the
                    # server stops a timed-out job through a context variable.
                    run = contextvars.copy_context().run
                    start = starts.popleft()
                    pending.append((start, pool.submit(run, page, start, offset_cursor(start))))

            try:
                top_up()
                while pending:
                    start, future = pending.popleft()
                    search = future.result()
                    read = start + len(search["nodes"])
                    yield search["nodes"][:limit - start]
                    if not search["pageInfo"]["hasNextPage"] or read >= limit:
                        return
                    cursor = search["pageInfo"]["endCursor"]
                    top_up()
            finally:
                # A reader that stopped early leaves pages not yet started.
                for _, future in pending:
                    future.cancel()
                pool.shutdown(wait=False)
        # One at a time: cursors that aren't offsets, or pages past the count.
        while read < limit:
            search = page(read, cursor)
            if not search["nodes"]:
                return
            yield search["nodes"][:limit - read]
            read += len(search["nodes"])
            if not search["pageInfo"]["hasNextPage"]:
                return
            cursor = search["pageInfo"]["endCursor"]

def done(value: Any) -> Future:
    """A future that already holds `value`."""
    future: Future = Future()
    future.set_result(value)
    return future


def in_background(fn: Callable[..., Any], /, *args: Any) -> Future:
    """`fn(*args)` on a thread of its own, in a copy of the caller's context."""
    pool = ThreadPoolExecutor(1, thread_name_prefix="holt-side")
    try:
        return pool.submit(contextvars.copy_context().run, fn, *args)
    finally:
        pool.shutdown(wait=False)


def offset_cursor(offset: int) -> str:
    """GitHub's search cursor for the page starting after `offset` results."""
    return base64.b64encode(f"cursor:{offset}".encode()).decode()


def search_query(repo_slug: str, window: Window, cutoff: datetime) -> str:
    """Bound the crawl by date server-side, on the side of the holdout we are on."""
    day = cutoff.date().isoformat()
    bound = f"created:<{day}" if window is Window.PRE_T else f"created:>={day}"
    return f"repo:{repo_slug} is:pr {bound} sort:created-desc"


# --- the settled sample -------------------------------------------------------
#
# A busy repository's newest 200 pull requests span a day or two (pytorch,
# llvm, nixpkgs, cpython), and the engine's rates only count pull requests
# opened at least SETTLE_DAYS before the read (agent/rates.py), because what
# has already happened to a two-day-old pull request is mostly the fast
# outcomes: quick merges and quick triage closes. Rates over those read
# pytorch's merge rate as 39% and openssl's as 40%, where the pull requests
# that had two weeks to get an answer show 11% for openssl.
#
# So when the newest pages hold fewer than SETTLED_TARGET outside pull requests
# old enough to count, a second search reads further back: pull requests
# opened before the settle window (or before the oldest one already read),
# newest first, one page at a time until the target is met, at most
# SETTLED_MAX_PAGES pages. Each page is the same query, one point.
SETTLE_DAYS = 14
SETTLED_TARGET = 60
SETTLED_MAX_PAGES = 8
# The older read's first page starts early (`_settled_early`) only when the
# newest pages look set to span less than half the settle window.
EARLY_MARGIN = 2

_TEAM = {"OWNER", "MEMBER", "COLLABORATOR"}


def settled_query(repo_slug: str, cutoff: datetime, oldest: datetime | None) -> str:
    """Pull requests old enough to count, from where the newest pages stopped."""
    settle_day = (cutoff - timedelta(days=SETTLE_DAYS)).date()
    if oldest is not None and oldest.date() < settle_day:
        # The newest pages already reach past the window; carry on from their
        # last day (inclusive: the rest of that day wasn't read; repeats are
        # dropped by number).
        bound = f"created:<={oldest.date().isoformat()}"
    else:
        bound = f"created:<{settle_day.isoformat()}"
    return f"repo:{repo_slug} is:pr {bound} sort:created-desc"


def _outside_and_settled(node: dict[str, Any], before: datetime) -> bool:
    """Roughly what the engine will count: an outside, non-draft pull request
    opened before `before`. Only steers how far to read; the engine decides."""
    author = node.get("author") or {}
    login = (author.get("login") or "").lower()
    created = _ts(node.get("createdAt"))
    return bool(
        created is not None and created < before
        and author.get("__typename") != "Bot" and not login.endswith("bot")
        and not login.endswith("[bot]")
        and node.get("authorAssociation") not in _TEAM
        and not node.get("isDraft")
    )


def _nodes(connection: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A connection with nothing in it can come back as null, not as an empty list.

    Observed on a pull request that changed no files: `files` was null while
    `changedFiles` was 0. Treating null and empty as the same thing here keeps a
    single odd pull request from aborting a repository's whole capture.
    """
    if not connection:
        return []
    return [n for n in (connection.get("nodes") or []) if n]


def _with_body(payload: dict[str, Any], raw: str | None) -> dict[str, Any]:
    body, truncated, original = _body(raw)
    payload["body"] = body
    if truncated:
        payload["body_truncated"] = True
        payload["body_original_chars"] = original
    return payload


def _with_association(payload: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """The author's relationship to the repository, when the capture asked for it.

    GitHub's CommentAuthorAssociation: OWNER, MEMBER, COLLABORATOR,
    CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, FIRST_TIMER, MANNEQUIN or NONE. It is
    GitHub's view at fetch time, not when the comment was written, so a
    first-timer whose pull request has since been merged can read CONTRIBUTOR.
    Captures made before this field existed do not carry the key at all, so
    every reader must treat it as optional; that is also what keeps their
    recorded runs replaying unchanged.
    """
    if "authorAssociation" in node:
        payload["author_association"] = node["authorAssociation"]
    return payload


def _actor(prefix: str, actor: dict[str, Any] | None) -> dict[str, Any]:
    """`{prefix}` login and `{prefix}_is_bot`, or None when GitHub gave nobody."""
    return {
        prefix: _login(actor) if actor else None,
        f"{prefix}_is_bot": _is_bot(actor),
    }


def _closer(node: dict[str, Any] | None) -> dict[str, Any] | None:
    """What closed a pull request, when it was a commit or another pull request.

    A commit closing a pull request that was never merged through the button is
    how projects that land work outside GitHub (an internal sync, a merge bot,
    a maintainer pushing by hand) show up in the timeline.
    """
    if not node:
        return None
    kind = node.get("__typename")
    if kind == "Commit":
        return {"kind": "commit", "oid": node.get("oid")}
    if kind == "PullRequest":
        return {"kind": "pull_request", "number": node.get("number")}
    return None


def _closure(pr: dict[str, Any]) -> dict[str, Any]:
    """Who or what closed an unmerged pull request, from its last close event.

    Empty for a capture that did not ask for the timeline, so old fixtures stay
    as they were. When the timeline was asked for but the close event was not
    in the window (see PR_SEARCH), the fields are present and None: unknown,
    which is different from absent.
    """
    if "timelineItems" not in pr:
        return {}
    closes = [n for n in _nodes(pr["timelineItems"]) if n.get("__typename") == "ClosedEvent"]
    last = closes[-1] if closes else {}
    return {
        **_actor("closed_by", last.get("actor")),
        "closer": _closer(last.get("closer")),
    }


def _same_repo_references(repo_slug: str, pr: dict[str, Any]) -> list[dict[str, Any]]:
    """Commits *in this repository* that mention the pull request.

    Contributors pushing to their own forks generate most reference events, and
    those say nothing about whether the project landed the work, so they are
    dropped at capture. What is kept is a commit on the project itself naming
    the pull request -- often the only trace that a maintainer applied it by
    hand and then closed it. It is evidence for a merge, not proof: a commit on
    a work branch of the same repository mentions the PR too.
    """
    out = []
    for node in _nodes(pr.get("timelineItems")):
        if node.get("__typename") != "ReferencedEvent":
            continue
        where = (node.get("commitRepository") or {}).get("nameWithOwner") or ""
        if where.lower() != repo_slug.lower() or not node.get("createdAt"):
            continue
        out.append(node)
    return out


def project(
    repo_slug: str, nodes: Iterable[dict[str, Any]], home: str | None = None
) -> Iterator[EvidenceRecord]:
    """Turn pull requests into timestamped, individually-addressable evidence.

    `home` is the name GitHub currently uses for the repository, when it
    differs from `repo_slug` (the name asked for, which the evidence ids keep).
    Links and same-repository commit references use it.

    The fields the v2 capture added -- `author_association`, `is_draft`,
    `labels`, `merged_by`, `closed_by`/`closer` and the `:reference:` records --
    are written only when the query asked for them. Every reader must treat them
    as optional: committed fixtures predate them.

    Draft state and labels are read at fetch time, like the association: a pull
    request labelled `spam` after the cutoff carries the label here.
    """
    home = home or repo_slug
    for pr in nodes:
        number = pr["number"]
        base = f"pr:{repo_slug}#{number}"
        url = f"https://github.com/{home}/pull/{number}"
        shared = _with_association(
            {"author": _login(pr["author"]), "author_is_bot": _is_bot(pr["author"])}, pr
        )

        opened: dict[str, Any] = {
            **shared,
            "title": pr["title"],
            "additions": pr["additions"],
            "deletions": pr["deletions"],
            "changed_files": pr["changedFiles"],
            "files": [f["path"] for f in _nodes(pr["files"])],
        }
        if "isDraft" in pr:
            opened["is_draft"] = bool(pr["isDraft"])
        if "labels" in pr:
            opened["labels"] = [n["name"] for n in _nodes(pr["labels"])]
        yield EvidenceRecord(
            evidence_id=f"{base}:opened",
            source="github",
            url=url,
            timestamp=_ts(pr["createdAt"]),
            payload=opened,
        )

        if merged_at := _ts(pr["mergedAt"]):
            merged: dict[str, Any] = {**shared, "merged": True}
            if "mergedBy" in pr:
                merged.update(_actor("merged_by", pr["mergedBy"]))
            yield EvidenceRecord(
                evidence_id=f"{base}:merged",
                source="github",
                url=url,
                timestamp=merged_at,
                payload=merged,
            )
        elif (closed_at := _ts(pr["closedAt"])) and not pr["merged"]:
            yield EvidenceRecord(
                evidence_id=f"{base}:closed",
                source="github",
                url=url,
                timestamp=closed_at,
                payload={**shared, "merged": False, **_closure(pr)},
            )

        for i, review in enumerate(_nodes(pr["reviews"])):
            yield EvidenceRecord(
                evidence_id=f"{base}:review:{i}",
                source="github",
                url=url,
                timestamp=_ts(review["createdAt"]),
                payload=_with_body(
                    _with_association(
                        {
                            "author": _login(review["author"]),
                            "author_is_bot": _is_bot(review["author"]),
                            "state": review["state"],
                        },
                        review,
                    ),
                    review["body"],
                ),
            )

        for i, comment in enumerate(_nodes(pr["comments"])):
            yield EvidenceRecord(
                evidence_id=f"{base}:comment:{i}",
                source="github",
                url=url,
                timestamp=_ts(comment["createdAt"]),
                payload=_with_body(
                    _with_association(
                        {
                            "author": _login(comment["author"]),
                            "author_is_bot": _is_bot(comment["author"]),
                        },
                        comment,
                    ),
                    comment["body"],
                ),
            )

        # Each reference is its own dated fact: a commit can land after the
        # cutoff on a pull request opened before it, and must be sliced off
        # like any other later event.
        for i, ref in enumerate(_same_repo_references(home, pr)):
            yield EvidenceRecord(
                evidence_id=f"{base}:reference:{i}",
                source="github",
                url=url,
                timestamp=_ts(ref["createdAt"]),
                payload={
                    "commit": (ref.get("commit") or {}).get("oid"),
                    **_actor("actor", ref.get("actor")),
                },
            )


def project_repo_meta(repo_slug: str, repo: dict[str, Any]) -> EvidenceRecord:
    """Repository-level facts.

    Mutable counters (stars) are as-of-fetch, not as-of-T: GitHub does not expose
    a historical star count, so they cannot be reconstructed at the cutoff. The
    payload says so. Holt's own reasoning must not lean on them; the popularity
    diagnostic does, and that limitation is published rather than hidden.
    """
    payload: dict[str, Any] = {
        "pushed_at": repo["pushedAt"],
        "is_archived": repo["isArchived"],
        "is_mirror": repo["isMirror"],
        "is_fork": repo["isFork"],
        "description": repo["description"],
        "homepage_url": repo["homepageUrl"],
        "primary_language": (repo["primaryLanguage"] or {}).get("name"),
        "stargazer_count": repo["stargazerCount"],
        "_counters_are_as_of_fetch_not_cutoff": True,
    }
    # For the report's header only (holt/about.py); nothing downstream reads
    # them. Absent from captures made before they were asked for. (`topics`, which
    # the header shows too, comes with the personal-project rule.)
    if "forkCount" in repo:
        payload["fork_count"] = repo["forkCount"]
    if "issues" in repo:
        payload["open_issues"] = (repo["issues"] or {}).get("totalCount")
    if "licenseInfo" in repo:
        payload["license"] = license_name(repo["licenseInfo"])
    if "languages" in repo:
        payload["languages"] = language_shares(repo["languages"])
    if "defaultBranchRef" in repo:
        payload["default_branch"] = (repo["defaultBranchRef"] or {}).get("name")
    # Added with the v2 capture; absent from older fixtures. `parent` is the
    # repository this one was forked from, `mirror_url` where a mirror copies
    # from: both say "the real project is elsewhere".
    if "nameWithOwner" in repo:
        payload["name_with_owner"] = repo["nameWithOwner"]
    if "parent" in repo:
        payload["parent"] = (repo["parent"] or {}).get("nameWithOwner")
    if "mirrorUrl" in repo:
        payload["mirror_url"] = repo["mirrorUrl"]
    if "releases" in repo:
        payload["release_count"] = (repo["releases"] or {}).get("totalCount", 0)
    # GitHub's own pull request switches (engine 6): off, or collaborators only
    # (ALL | COLLABORATORS_ONLY). Absent from captures made before them.
    if "hasPullRequestsEnabled" in repo:
        payload["pull_requests_enabled"] = repo["hasPullRequestsEnabled"]
    if "pullRequestCreationPolicy" in repo:
        payload["pull_request_policy"] = repo["pullRequestCreationPolicy"]
    # Added with the personal-project rule (agent/personal.py); absent before.
    if "repositoryTopics" in repo:
        payload["topics"] = [
            n["topic"]["name"] for n in _nodes(repo["repositoryTopics"]) if n.get("topic")
        ]
    return EvidenceRecord(
        evidence_id=f"repo:{repo_slug}:meta",
        source="github",
        url=f"https://github.com/{repo_slug}",
        timestamp=_ts(repo["createdAt"]),
        payload=payload,
    )


def project_releases(repo_slug: str, repo: dict[str, Any]) -> Iterator[EvidenceRecord]:
    """The newest releases, one dated record each, so they slice at the cutoff.

    Only the newest ten are asked for: enough to tell a project that ships
    monthly from one that last shipped years ago. A reading as of a past cutoff
    may find all ten after it and keep none; the count on the meta record is
    as-of-fetch, like the other counters there.
    """
    for i, rel in enumerate(_nodes(repo.get("releases"))):
        when = _ts(rel.get("publishedAt") or rel.get("createdAt"))
        if when is None:
            continue
        tag = rel.get("tagName") or ""
        yield EvidenceRecord(
            evidence_id=f"repo:{repo_slug}:release:{i}",
            source="github",
            url=f"https://github.com/{repo_slug}/releases/tag/{quote(tag, safe='')}",
            timestamp=when,
            payload={
                "tag": tag,
                "name": rel.get("name"),
                "is_prerelease": bool(rel.get("isPrerelease")),
            },
        )


MAX_DOC_CHARS = 12000


def project_docs(repo_slug: str, docs: dict[str, Any], commit: dict[str, Any]) -> Iterator[EvidenceRecord]:
    """README, CONTRIBUTING and an AI policy as they stood at the cutoff commit."""
    when = _ts(commit["committedDate"])
    for kind in DOC_CANDIDATES:
        blob = docs.get(kind)
        text = (blob or {}).get("text")
        if not text:
            continue
        path = (blob or {}).get("path") or f"{kind.upper()}.md"
        truncated = len(text) > MAX_DOC_CHARS
        payload: dict[str, Any] = {
            "path": path,
            "kind": kind,
            "text": text[:MAX_DOC_CHARS],
            "commit_oid": commit["oid"],
        }
        if truncated:
            payload["text_truncated"] = True
            payload["text_original_chars"] = len(text)
        yield EvidenceRecord(
            evidence_id=f"repo:{repo_slug}:{kind}",
            source="github",
            url=f"https://github.com/{repo_slug}/blob/{commit['oid']}/{path}",
            timestamp=when,
            payload=payload,
        )


def project_stale(repo_slug: str, docs: dict[str, Any],
                  commit: dict[str, Any]) -> Iterator[EvidenceRecord]:
    """The stale bot's config files as they stood at the cutoff commit."""
    when = _ts(commit["committedDate"])
    for i, found in enumerate(docs.get("stale") or []):
        yield EvidenceRecord(
            evidence_id=f"repo:{repo_slug}:stale:{i}",
            source="github",
            url=f"https://github.com/{repo_slug}/blob/{commit['oid']}/{found['path']}",
            timestamp=when,
            payload={"kind": found["kind"], "path": found["path"],
                     "text": found["text"][:MAX_DOC_CHARS], "commit_oid": commit["oid"]},
        )


def project_issues(repo_slug: str, nodes: Iterable[dict[str, Any]]) -> Iterator[EvidenceRecord]:
    """Issue events. Opening is pre-cutoff evidence; being resolved is the label."""
    for issue in nodes:
        number = issue["number"]
        base = f"issue:{repo_slug}#{number}"
        url = f"https://github.com/{repo_slug}/issues/{number}"
        body = issue.get("body") or ""

        yield EvidenceRecord(
            evidence_id=f"{base}:opened",
            source="github",
            url=url,
            timestamp=_ts(issue["createdAt"]),
            payload={
                "title": issue.get("title"),
                "body": body[:MAX_ISSUE_BODY],
                "body_truncated": len(body) > MAX_ISSUE_BODY,
                "labels": [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])],
                "comments": (issue.get("comments") or {}).get("totalCount", 0),
                "author": _login(issue.get("author")),
                # The body GitHub returns is the current one, not the one that
                # existed at the cutoff. `lastEditedAt` is null unless the body
                # itself was edited; `updatedAt` bumps on any comment or label
                # change, and using it measured "had activity" rather than "was
                # edited" -- reporting a 100% leak that was not real.
                "last_edited_at": issue.get("lastEditedAt"),
            },
        )

        closed_at = _ts(issue.get("closedAt"))
        if not closed_at:
            continue
        merged = [
            p for p in (issue.get("closedByPullRequestsReferences") or {}).get("nodes", [])
            if p and p.get("mergedAt")
        ]
        yield EvidenceRecord(
            evidence_id=f"{base}:closed",
            source="github",
            url=url,
            timestamp=closed_at,
            payload={
                "resolved_by_merged_pr": bool(merged),
                "closing_prs": [
                    {"number": p["number"], "author": _login(p.get("author")),
                     "author_is_bot": _is_bot(p.get("author"))}
                    for p in merged
                ],
            },
        )


class LiveGitHubProvider(EvidenceProvider):
    """Crawls GitHub, then hands every record to the base-class window check.

    The default cutoff is **now**, not the benchmark's T. T = 2026-06-01 is an
    evaluation device; a live reader wants everything up to today, and a caller
    that inherited T by default reported an active repository created in July as
    having no history at all. The evaluation and the fixture capture pass their
    cutoff explicitly, which is the correct place for that decision to be
    visible.
    """

    def __init__(
        self,
        window: Window,
        cutoff: datetime | None = None,
        transport: GitHubGraphQL | None = None,
        max_pages: int = 8,
        timeline: bool = True,
        settled_pages: int | None = None,
        timing_pages: int | None = None,
    ) -> None:
        super().__init__(window, cutoff or datetime.now(UTC))
        self.transport = transport or GitHubGraphQL()
        self.max_pages = max_pages
        # How far past the newest pages a full report may read for pull
        # requests old enough to count (see SETTLED_TARGET). A screen doesn't.
        self.settled_pages = (
            (SETTLED_MAX_PAGES if timeline else 0) if settled_pages is None else settled_pages
        )
        # False for a quick screen: no close events or commit references (see
        # PR_SEARCH_SCREEN). A full report always reads them.
        self.timeline = timeline
        # Pages of the timing cohort a full report may read (TIMING_SEARCH).
        self.timing_pages = (
            (TIMING_PAGES if timeline else 0) if timing_pages is None else timing_pages
        )
        self._seen: dict[str, EvidenceRecord] = {}

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        owner, _, name = request.partition("/")
        opening = self._open(owner, name, request)
        meta = opening.meta if opening else self.transport.repo_meta(owner, name, self.cutoff)
        records: list[EvidenceRecord] = [project_repo_meta(request, meta)]
        records.extend(project_releases(request, meta))

        branch = meta.get("defaultBranchRef") or {}
        history = ((branch.get("target") or {}).get("history") or {}).get("nodes") or []
        # The README and CONTRIBUTING are read while the pull requests are,
        # unless the opening query read them already at the same commit.
        docs: Future | None = None
        if history and opening and opening.docs is not None and opening.head == history[0]["oid"]:
            docs = done(opening.docs)
        elif history:
            docs = in_background(self.transport.docs_at, owner, name, history[0]["oid"])
        # A search under a repository's old name finds nothing, although
        # GitHub answers the lookup above under either name and redirects its
        # pages: facebook/react-native, now react/react-native, read as a
        # project with no pull requests at all. So the search uses the name
        # GitHub gives back (and the opening's page, searched under the name
        # asked for, is dropped when they differ). The evidence ids keep the
        # name asked for, which is the one every caller looks them up by.
        home = meta.get("nameWithOwner") or request
        query = search_query(home, self.window, self.cutoff)
        head = opening.search if opening and home == request else None
        nodes: list[dict[str, Any]] = []
        early: tuple[str, Future] | None = None
        cohort_early: Future | None = None
        # The keywords only when used, so a transport written before them
        # (the tests have several) still serves full fetches.
        if head is not None:
            pages = self.transport.search_pull_requests(query, self.max_pages, first=done(head))
        elif self.timeline:
            pages = self.transport.search_pull_requests(query, self.max_pages)
        else:
            pages = self.transport.search_pull_requests(query, self.max_pages, timeline=False)
        for node in pages:
            nodes.append(node)
            if len(nodes) == PAGE_SIZE:
                early = self._settled_early(home, nodes)
                cohort_early = self._timing_early(request, home, nodes)
        cohort = self._timing(request, home, nodes, cohort_early)
        if self.window is Window.PRE_T:
            nodes += self._settled(home, nodes, early)
        if docs is not None:
            found = docs.result()
            records.extend(project_docs(request, found, history[0]))
            records.extend(project_stale(request, found, history[0]))
        records.extend(project(request, nodes, home=home))
        if cohort is not None:
            records.extend(cohort.result() if isinstance(cohort, Future) else cohort)

        # Slice at the source; the base-class assertion is the safety net, not
        # the filter. A PR created before T can still carry a merge after it.
        kept = [r for r in records if self._in_window(r)]
        self._seen.update({r.evidence_id: r for r in kept})
        return kept

    def _timing(self, request: str, home: str, nodes: list[dict[str, Any]],
                early: Future | None = None) -> Future | list[EvidenceRecord] | None:
        """The timing cohort (agent/timing.py): the newest pages themselves when
        they reach back past its window or hold the whole history, else one
        light search, read while the older pages are (or already started by
        `_timing_early`)."""
        if self.window is not Window.PRE_T or not self.timing_pages:
            return None
        created = [t for n in nodes if (t := _ts(n.get("createdAt")))]
        if timing_source(created, len(nodes) >= self.max_pages * PAGE_SIZE,
                         self.cutoff) == "sample":
            return [timing_window(request, self.cutoff, "sample")]
        if early is not None:
            return early
        if getattr(self.transport, "search_timing", None) is None:
            return None  # a test's transport from before the cohort
        return in_background(read_timing, self.transport, request, home, self.cutoff,
                             self.timing_pages)

    def _timing_early(self, request: str, home: str,
                      page: list[dict[str, Any]]) -> Future | None:
        """Start the cohort's search while the newest pages load, when the first
        of them shows the pages won't reach back to the cohort's window (at
        this page's pace, with room for it to slow). A wrong guess costs the
        search's points, up to three."""
        if (self.window is not Window.PRE_T or not self.timing_pages
                or not isinstance(self.transport, GitHubGraphQL)):
            return None
        created = [t for n in page if (t := _ts(n.get("createdAt")))]
        if len(created) < PAGE_SIZE:
            return None
        reach = (max(created) - min(created)) * self.max_pages * EARLY_MARGIN
        if max(created) - reach <= self.cutoff - timedelta(days=TIMING_DAYS[1]):
            return None
        return in_background(read_timing, self.transport, request, home, self.cutoff,
                             self.timing_pages)

    def _open(self, owner: str, name: str, request: str) -> Opening | None:
        """A full report's first query (see OPENING_SIZE), on the real transport."""
        if not self.timeline or not isinstance(self.transport, GitHubGraphQL):
            return None
        return self.transport.opening(
            owner, name, self.cutoff, search_query(request, self.window, self.cutoff),
            min(OPENING_SIZE, self.max_pages * PAGE_SIZE),
            # A cutoff in the past is rarely HEAD; don't fetch docs to drop them.
            docs=self.cutoff >= datetime.now(UTC) - LIVE_WITHIN,
        )

    def _settled_early(
        self, home: str, page: list[dict[str, Any]]
    ) -> tuple[str, Future] | None:
        """Start the older read's first page while the newest pages load, when
        the first of them shows it will be wanted: the repository is so busy
        that all the newest pages will fall inside the settle window, so they
        hold nothing old enough to count. `_settled` uses it only if it asks
        exactly this query; a wrong guess costs one page, a point."""
        if (
            self.window is not Window.PRE_T or not self.settled_pages
            or not isinstance(self.transport, GitHubGraphQL)
        ):
            return None
        created = [t for n in page if (t := _ts(n.get("createdAt")))]
        if len(created) < PAGE_SIZE:
            return None
        # Where the last newest page is likely to end, at this page's pace,
        # with room for the pace to slow. (The pace is the page's own: the
        # search leaves out today, so the page can start well before now.)
        reach = (max(created) - min(created)) * self.max_pages * EARLY_MARGIN
        if max(created) - reach < self.cutoff - timedelta(days=SETTLE_DAYS - 1):
            return None
        query = settled_query(home, self.cutoff, None)
        return query, self.transport.first_page(query)

    def _settled(
        self, home: str, nodes: list[dict[str, Any]],
        early: tuple[str, Future] | None = None,
    ) -> list[dict[str, Any]]:
        """Older pull requests, when the newest pages hold too few that count."""
        # Fewer than the pages could hold means the repository has no more.
        if not self.settled_pages or len(nodes) < self.max_pages * PAGE_SIZE:
            return []
        before = self.cutoff - timedelta(days=SETTLE_DAYS)
        have = sum(1 for n in nodes if _outside_and_settled(n, before))
        if have >= SETTLED_TARGET:
            return []
        seen = {n.get("number") for n in nodes}
        oldest = min((t for n in nodes if (t := _ts(n.get("createdAt")))), default=None)
        query = settled_query(home, self.cutoff, oldest)
        more: list[dict[str, Any]] = []
        start, read = have, 0

        def wanted() -> int:
            """PAGE_SIZE steps still needed, at the rate the ones read so far found them."""
            if have >= SETTLED_TARGET:
                return 0
            per_step = (have - start) / max(1.0, read / PAGE_SIZE)
            return math.ceil((SETTLED_TARGET - have) / max(per_step, 1.0))

        # Only the real transport reads pages ahead; the tests' fakes predate it.
        ahead: dict[str, Any] = (
            {"wanted": wanted} if isinstance(self.transport, GitHubGraphQL) else {}
        )
        if early is not None and early[0] == query:
            ahead["first"] = early[1]
        for read, node in enumerate(
            self.transport.search_pull_requests(query, self.settled_pages, **ahead), 1
        ):
            if node.get("number") not in seen:
                seen.add(node.get("number"))
                more.append(node)
                have += _outside_and_settled(node, before)
            # Stop at a page boundary, so no page read is left unused.
            if read % PAGE_SIZE == 0 and have >= SETTLED_TARGET:
                break
        return more

    def _in_window(self, record: EvidenceRecord) -> bool:
        if self.window is Window.PRE_T:
            return record.timestamp <= self.cutoff
        return record.timestamp > self.cutoff

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._seen.get(evidence_id)


def issue_query(repo_slug: str, cutoff: datetime) -> str:
    """Open issues created before the cutoff, newest first.

    `is:open` because the product asks where to start *now*: a closed issue is
    not a place to start, and without the qualifier half of the page budget went
    on issues that were already finished. The sort is explicit because GitHub's
    default "best match" ordering is not stable between calls, which made two
    runs on the same repository rank different candidate sets. (The benchmark's
    capture script builds its own query and still reads closed issues, because
    closure is its label.)
    """
    day = cutoff.date().isoformat()
    return f"repo:{repo_slug} is:issue is:open created:<{day} sort:created-desc"


class LiveGitHubIssueProvider(EvidenceProvider):
    """Issues, through the same chokepoint as everything else.

    Separate from `LiveGitHubProvider` rather than a flag on it because the two
    answer different questions and are captured into different fixture roots. A
    provider that returned issues or pull requests depending on a constructor
    argument would make every window assertion harder to read for no gain.
    """

    def __init__(
        self,
        window: Window,
        cutoff: datetime | None = None,
        transport: GitHubGraphQL | None = None,
        max_pages: int = 6,
    ) -> None:
        # Same default as LiveGitHubProvider, for the same reason: live means now.
        super().__init__(window, cutoff or datetime.now(UTC))
        self.transport = transport or GitHubGraphQL()
        self.max_pages = max_pages
        self._seen: dict[str, EvidenceRecord] = {}

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        # Slice at the source. `created:<T` is a server-side qualifier, so the
        # newest-first ordering cannot fill the page with issues we must not see.
        nodes = self.transport.search_issues(
            issue_query(request, self.cutoff), self.max_pages
        )
        kept = [r for r in project_issues(request, nodes) if r.timestamp <= self.cutoff]
        self._seen.update({r.evidence_id: r for r in kept})
        return kept

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._seen.get(evidence_id)
