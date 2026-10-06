"""What can go wrong talking to GitHub, as types a caller can act on.

The web server maps these straight onto API error codes (`not_found`,
`rate_limited` with `retry_after`, `upstream`), so each carries a message a
beginner can read. All of them are `RuntimeError`s, so code that already
catches that -- the CLI prints the message and exits -- keeps working.
"""

from __future__ import annotations


class GitHubError(RuntimeError):
    """Base class. The message is plain English and safe to show a user."""


class RepoNotFound(GitHubError):
    def __init__(self, repo: str) -> None:
        self.repo = repo
        super().__init__(
            f"Couldn't find {repo} on GitHub. Check the spelling; private "
            "repositories can't be read."
        )


class RateLimited(GitHubError):
    """`secondary`: GitHub's limit on how much is asked at once (it answers
    with points to spare), not the hourly budget running out."""

    def __init__(self, retry_after: float | None = None, secondary: bool = False) -> None:
        self.retry_after = retry_after
        self.secondary = secondary
        wait = (
            f" Try again in about {max(1, round(retry_after / 60))} minute(s)."
            if retry_after else " Try again in a few minutes."
        )
        super().__init__("GitHub is limiting how fast we can read right now." + wait)


class AuthError(GitHubError):
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "GitHub rejected the access token. Check that GITHUB_TOKEN is set, "
            "valid and not expired." + (f" ({detail})" if detail else "")
        )


class Forbidden(GitHubError):
    """A 403 that is not a rate limit: GitHub won't answer this request. About
    what was asked for, not proof the token is dead (that is a 401)."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "GitHub refused this request. The access token may not be allowed "
            "to read this repository." + (f" ({detail})" if detail else "")
        )


class UpstreamError(GitHubError):
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "GitHub didn't answer properly, even after retrying. Try again in a "
            "moment." + (f" ({detail})" if detail else "")
        )
