"""Turning whatever a person pasted into `owner/repo`."""

from __future__ import annotations

import re

from holt_server.errors import ApiError

# GitHub's own rules: owners are alphanumerics and single hyphens (39 max);
# repository names also allow `.` and `_` (100 max).
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def normalize(raw: str) -> str:
    """`https://github.com/o/r/tree/main?tab=x` -> `o/r`. Raises `invalid_repo`."""
    text = (raw or "").strip()
    text = text.split("#", 1)[0].split("?", 1)[0]
    text = re.sub(r"^(?:git\+)?(?:https?://|ssh://|git://)?", "", text, flags=re.I)
    text = re.sub(r"^git@github\.com:", "github.com/", text, flags=re.I)
    text = re.sub(r"^(?:www\.)?github\.com[/:]", "", text, flags=re.I)
    parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise invalid(raw)
    owner, name = parts[0], parts[1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not _OWNER.match(owner) or not _NAME.match(name) or name in {".", ".."}:
        raise invalid(raw)
    return f"{owner}/{name}"


def invalid(raw: str) -> ApiError:
    return ApiError(
        "invalid_repo",
        "That doesn't look like a GitHub repository. Paste something like "
        "owner/repo or https://github.com/owner/repo.",
    )


def key(repo: str) -> str:
    """Case-insensitive identity, for cache lookups."""
    return repo.lower()
