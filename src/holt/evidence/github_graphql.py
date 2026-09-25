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

import os
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from holt.evidence.provider import EvidenceProvider
from holt.types import EvidenceRecord, Window

API = "https://api.github.com/graphql"

# Comment and review bodies carry the signal Holt actually reads: tone, intent,
# whether a maintainer engaged. Four thousand characters is far more than any of
# that needs. What blows past it is log dumps and stack traces -- one observed
# comment ran to 74,000 characters -- which cost a judge download size and cost
# the model context without changing a single judgement. Truncation is recorded
# on the record so a reader is never silently shown a partial quote.
MAX_BODY_CHARS = 4000

REPO_META = """
query($owner:String!, $name:String!, $until:GitTimestamp!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    createdAt pushedAt isArchived isMirror isFork stargazerCount
    description homepageUrl primaryLanguage { name }
    defaultBranchRef {
      name
      target {
        ... on Commit { history(until:$until, first:1) { nodes { oid committedDate } } }
      }
    }
  }
}
"""

# The README as it stood at the cutoff, not as it stands today. Reading HEAD
# would hand the agent a document rewritten months after the window it is
# supposed to be reasoning about -- a leak that would never announce itself.
REPO_DOCS = """
query($owner:String!, $name:String!, $readme:String!, $contributing:String!) {
  rateLimit { remaining resetAt }
  repository(owner:$owner, name:$name) {
    readme: object(expression:$readme) { ... on Blob { text } }
    contributing: object(expression:$contributing) { ... on Blob { text } }
  }
}
"""

# Date filtering happens server-side. Ordering by newest and paging until the
# timestamps fall past the cutoff would burn most of the rate-limit budget on
# records the window filter then discards.
PR_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { remaining resetAt }
  search(query:$q, type:ISSUE, first:25, after:$cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number title createdAt mergedAt closedAt merged
        additions deletions changedFiles
        author { login __typename }
        files(first:20) { nodes { path additions deletions } }
        reviews(first:20) { nodes { createdAt state body author { login __typename } } }
        comments(first:30) { nodes { createdAt body author { login __typename } } }
      }
    }
  }
}
"""


# Issues, for Path Finder. Decomposed the same way pull requests are: an issue
# opening is a pre-cutoff fact, and an issue being closed by somebody's merged
# pull request is a post-cutoff one. The two must not travel together.
ISSUE_SEARCH = """
query($q:String!, $cursor:String) {
  rateLimit { remaining resetAt }
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
  rateLimit { remaining resetAt }
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


class GitHubGraphQL:
    """Thin transport. Knows about auth, pagination and the rate-limit budget."""

    def __init__(self, token: str | None = None, client: httpx.Client | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError(
                "GITHUB_TOKEN is not set. Live mode needs a token; "
                "use fixture or replay mode to run without one."
            )
        self._client = client or httpx.Client(timeout=30.0)
        self.remaining: int | None = None

    def query(self, document: str, **variables: object) -> dict[str, Any]:
        response = self._client.post(
            API,
            headers={"Authorization": f"bearer {self.token}"},
            json={"query": document, "variables": variables},
        )
        response.raise_for_status()
        body = response.json()
        if "errors" in body:
            raise RuntimeError(f"GraphQL error: {body['errors']}")
        data = body["data"]
        if limit := data.get("rateLimit"):
            self.remaining = limit["remaining"]
        return data

    def repo_meta(self, owner: str, name: str, until: datetime) -> dict[str, Any]:
        repo = self.query(
            REPO_META, owner=owner, name=name, until=until.isoformat()
        )["repository"]
        if repo is None:
            raise RuntimeError(f"{owner}/{name} not found or not public")
        return repo

    def docs_at(self, owner: str, name: str, oid: str) -> dict[str, Any]:
        """README and CONTRIBUTING at a specific commit."""
        return self.query(
            REPO_DOCS,
            owner=owner,
            name=name,
            readme=f"{oid}:README.md",
            contributing=f"{oid}:CONTRIBUTING.md",
        )["repository"]

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

    def search_pull_requests(self, q: str, max_pages: int = 8) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        for _ in range(max_pages):
            search = self.query(PR_SEARCH, q=q, cursor=cursor)["search"]
            yield from (n for n in search["nodes"] if n)
            page = search["pageInfo"]
            if not page["hasNextPage"]:
                return
            cursor = page["endCursor"]


def search_query(repo_slug: str, window: Window, cutoff: datetime) -> str:
    """Bound the crawl by date server-side, on the side of the holdout we are on."""
    day = cutoff.date().isoformat()
    bound = f"created:<{day}" if window is Window.PRE_T else f"created:>={day}"
    return f"repo:{repo_slug} is:pr {bound} sort:created-desc"


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


def project(repo_slug: str, nodes: Iterable[dict[str, Any]]) -> Iterator[EvidenceRecord]:
    """Turn pull requests into timestamped, individually-addressable evidence."""
    for pr in nodes:
        number = pr["number"]
        base = f"pr:{repo_slug}#{number}"
        url = f"https://github.com/{repo_slug}/pull/{number}"
        shared = {"author": _login(pr["author"]), "author_is_bot": _is_bot(pr["author"])}

        yield EvidenceRecord(
            evidence_id=f"{base}:opened",
            source="github",
            url=url,
            timestamp=_ts(pr["createdAt"]),
            payload={
                **shared,
                "title": pr["title"],
                "additions": pr["additions"],
                "deletions": pr["deletions"],
                "changed_files": pr["changedFiles"],
                "files": [f["path"] for f in _nodes(pr["files"])],
            },
        )

        if merged_at := _ts(pr["mergedAt"]):
            yield EvidenceRecord(
                evidence_id=f"{base}:merged",
                source="github",
                url=url,
                timestamp=merged_at,
                payload={**shared, "merged": True},
            )
        elif (closed_at := _ts(pr["closedAt"])) and not pr["merged"]:
            yield EvidenceRecord(
                evidence_id=f"{base}:closed",
                source="github",
                url=url,
                timestamp=closed_at,
                payload={**shared, "merged": False},
            )

        for i, review in enumerate(_nodes(pr["reviews"])):
            yield EvidenceRecord(
                evidence_id=f"{base}:review:{i}",
                source="github",
                url=url,
                timestamp=_ts(review["createdAt"]),
                payload=_with_body(
                    {
                        "author": _login(review["author"]),
                        "author_is_bot": _is_bot(review["author"]),
                        "state": review["state"],
                    },
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
                    {
                        "author": _login(comment["author"]),
                        "author_is_bot": _is_bot(comment["author"]),
                    },
                    comment["body"],
                ),
            )


def project_repo_meta(repo_slug: str, repo: dict[str, Any]) -> EvidenceRecord:
    """Repository-level facts.

    Mutable counters (stars) are as-of-fetch, not as-of-T: GitHub does not expose
    a historical star count, so they cannot be reconstructed at the cutoff. The
    payload says so. Holt's own reasoning must not lean on them; the popularity
    diagnostic does, and that limitation is published rather than hidden.
    """
    return EvidenceRecord(
        evidence_id=f"repo:{repo_slug}:meta",
        source="github",
        url=f"https://github.com/{repo_slug}",
        timestamp=_ts(repo["createdAt"]),
        payload={
            "pushed_at": repo["pushedAt"],
            "is_archived": repo["isArchived"],
            "is_mirror": repo["isMirror"],
            "is_fork": repo["isFork"],
            "description": repo["description"],
            "homepage_url": repo["homepageUrl"],
            "primary_language": (repo["primaryLanguage"] or {}).get("name"),
            "stargazer_count": repo["stargazerCount"],
            "_counters_are_as_of_fetch_not_cutoff": True,
        },
    )


MAX_DOC_CHARS = 12000


def project_docs(repo_slug: str, docs: dict[str, Any], commit: dict[str, Any]) -> Iterator[EvidenceRecord]:
    """README and CONTRIBUTING as they stood at the cutoff commit."""
    when = _ts(commit["committedDate"])
    for kind in ("readme", "contributing"):
        blob = docs.get(kind)
        text = (blob or {}).get("text")
        if not text:
            continue
        truncated = len(text) > MAX_DOC_CHARS
        payload: dict[str, Any] = {
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
            url=f"https://github.com/{repo_slug}/blob/{commit['oid']}/{kind.upper()}.md",
            timestamp=when,
            payload=payload,
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
    ) -> None:
        super().__init__(window, cutoff or datetime.now(UTC))
        self.transport = transport or GitHubGraphQL()
        self.max_pages = max_pages
        self._seen: dict[str, EvidenceRecord] = {}

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        owner, _, name = request.partition("/")
        meta = self.transport.repo_meta(owner, name, self.cutoff)
        records: list[EvidenceRecord] = [project_repo_meta(request, meta)]

        branch = meta.get("defaultBranchRef") or {}
        history = ((branch.get("target") or {}).get("history") or {}).get("nodes") or []
        if history:
            docs = self.transport.docs_at(owner, name, history[0]["oid"])
            records.extend(project_docs(request, docs, history[0]))
        nodes = self.transport.search_pull_requests(
            search_query(request, self.window, self.cutoff), self.max_pages
        )
        records.extend(project(request, nodes))

        # Slice at the source; the base-class assertion is the safety net, not
        # the filter. A PR created before T can still carry a merge after it.
        kept = [r for r in records if self._in_window(r)]
        self._seen.update({r.evidence_id: r for r in kept})
        return kept

    def _in_window(self, record: EvidenceRecord) -> bool:
        if self.window is Window.PRE_T:
            return record.timestamp <= self.cutoff
        return record.timestamp > self.cutoff

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._seen.get(evidence_id)


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
        day = self.cutoff.date().isoformat()
        nodes = self.transport.search_issues(
            f"repo:{request} is:issue created:<{day}", self.max_pages
        )
        kept = [r for r in project_issues(request, nodes) if r.timestamp <= self.cutoff]
        self._seen.update({r.evidence_id: r for r in kept})
        return kept

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._seen.get(evidence_id)
