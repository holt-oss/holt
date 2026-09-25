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
    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
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


class UpstreamError(GitHubError):
    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(
            "GitHub didn't answer properly, even after retrying. Try again in a "
            "moment." + (f" ({detail})" if detail else "")
        )
