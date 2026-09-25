"""GitHub access for the server: the token pool and a cheap repo lookup."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from holt_server.errors import ApiError, github_rate_limited, not_found_repo, upstream

API = "https://api.github.com/graphql"

LOOKUP = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) { nameWithOwner isPrivate }
}
"""


class TokenPool:
    """`GITHUB_TOKENS`, handed out round-robin, one per analysis."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)
        self._cycle = itertools.cycle(self._tokens) if self._tokens else None
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self._tokens)

    def next(self) -> str:
        if self._cycle is None:
            raise ApiError(
                "internal",
                "This server isn't set up to read GitHub yet. Please try again later.",
            )
        with self._lock:
            return next(self._cycle)


@dataclass
class RepoInfo:
    name_with_owner: str


class GitHubLookup:
    """Checks a repository exists and returns GitHub's casing for its name.

    One GraphQL point per call. Done before a job is queued, so a typo gets
    `not_found` at once instead of a failed job a minute later.
    """

    def __init__(self, pool: TokenPool, client: httpx.AsyncClient | None = None) -> None:
        self.pool = pool
        self._client = client

    async def repo(self, repo: str) -> RepoInfo:
        owner, _, name = repo.partition("/")
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                API,
                headers={"Authorization": f"bearer {self.pool.next()}"},
                json={"query": LOOKUP, "variables": {"owner": owner, "name": name}},
            )
        except httpx.HTTPError as exc:
            raise upstream() from exc
        finally:
            if self._client is None:
                await client.aclose()
        raise_for_github(response)
        body = response.json()
        data = (body.get("data") or {}).get("repository")
        if not data or data.get("isPrivate"):
            raise not_found_repo(repo)
        return RepoInfo(name_with_owner=data["nameWithOwner"])


def retry_after_from(response: httpx.Response) -> int:
    if value := response.headers.get("retry-after"):
        try:
            return max(1, int(value))
        except ValueError:
            pass
    if value := response.headers.get("x-ratelimit-reset"):
        try:
            return max(1, int(value) - int(datetime.now(UTC).timestamp()))
        except ValueError:
            pass
    return 600


def raise_for_github(response: httpx.Response) -> None:
    if response.status_code in (403, 429):
        raise github_rate_limited(retry_after_from(response))
    if response.status_code >= 400:
        raise upstream()
    body = response.json()
    for err in body.get("errors") or []:
        if err.get("type") == "RATE_LIMITED":
            raise github_rate_limited(retry_after_from(response))
