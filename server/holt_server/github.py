"""GitHub access for the server: the token pool and a cheap repo lookup.

Both go through the engine's own transport (`holt.evidence.github_graphql`),
so retries, rate-limit handling and the typed errors are the engine's.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from dataclasses import dataclass

import httpx

from holt_server.errors import ApiError

LOOKUP = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) { nameWithOwner isPrivate }
}
"""

LOOKUP_TIMEOUT_S = 15.0


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

    def __init__(self, pool: TokenPool, http: httpx.Client) -> None:
        self.pool = pool
        self.http = http

    async def repo(self, repo: str) -> RepoInfo:
        return await asyncio.to_thread(self._repo, repo)

    def _repo(self, repo: str) -> RepoInfo:
        from holt.evidence.github_graphql import GitHubGraphQL
        from holt_server.engine import translate

        owner, _, name = repo.partition("/")
        try:
            data = GitHubGraphQL(token=self.pool.next(), client=self.http).query(
                LOOKUP, timeout=LOOKUP_TIMEOUT_S, owner=owner, name=name)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise translate(exc, repo) from exc
        found = data.get("repository")
        if not found or found.get("isPrivate"):
            from holt_server.errors import not_found_repo

            raise not_found_repo(repo)
        return RepoInfo(name_with_owner=found["nameWithOwner"])
