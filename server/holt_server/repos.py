"""Turning whatever a person pasted into `owner/repo`: the engine's parser,
with its plain-English message as an `invalid_repo` error."""

from __future__ import annotations

from holt.reponame import normalise
from holt_server.errors import ApiError


def normalize(raw: str) -> str:
    """`https://github.com/o/r/tree/main?tab=x` -> `o/r`. Raises `invalid_repo`."""
    try:
        return normalise(raw)
    except ValueError as exc:
        raise ApiError("invalid_repo", str(exc)) from exc


def key(repo: str) -> str:
    """Case-insensitive identity, for cache lookups."""
    return repo.lower()
