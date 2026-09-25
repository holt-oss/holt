"""Turn whatever a person pasted into `owner/repo`.

People paste what is in their address bar: `https://github.com/pallets/flask`,
`github.com/pallets/flask.git`, a link to a file under `/tree/main/src`, a URL
carrying `?tab=readme-ov-file` or `#readme`. All of those name one repository
and all of them should work. What should not work is anything that names
something else -- a GitLab project, a bare word, a user's profile -- and for
those the error says, in plain English, what to type instead.
"""

from __future__ import annotations

import re

# GitHub's own rules: owners are alphanumerics and single hyphens (up to 39
# chars); repository names also allow `.` and `_`, up to 100 chars.
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

_GITHUB_HOSTS = {"github.com", "www.github.com"}

# Top-level GitHub paths that are not an owner.
_NOT_OWNERS = {
    "orgs", "settings", "marketplace", "explore", "topics", "trending",
    "collections", "sponsors", "notifications", "login", "search", "features",
    "about", "pricing", "enterprise", "issues", "pulls", "codespaces", "new",
}

EXAMPLE = "Try something like pallets/flask or https://github.com/pallets/flask."


def normalise(text: str) -> str:
    """Return `owner/repo`, or raise ValueError with a sentence a beginner can act on."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError(f"Please enter a GitHub repository. {EXAMPLE}")

    s = raw
    # Fragment and query never name a repository; drop them first.
    s = s.split("#", 1)[0].split("?", 1)[0].strip()

    # SSH form: git@github.com:owner/repo.git
    ssh = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.*)$", s, flags=re.IGNORECASE)
    if ssh:
        host, path = ssh.group(1).lower(), ssh.group(2)
    else:
        m = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?([^/]*)(/.*)?$", s, flags=re.IGNORECASE)
        head = m.group(1) if m else ""
        # GitHub account names cannot contain a dot, so a first segment with
        # one is a host (github.com, gitlab.com), never an owner.
        if "://" in s or "." in head:
            host, path = head.lower(), (m.group(2) or "")
        else:
            host, path = "", s

    if host:
        host = host.split("@")[-1].split(":")[0]
        if host not in _GITHUB_HOSTS:
            where = "GitLab" if "gitlab" in host else "Bitbucket" if "bitbucket" in host else host
            raise ValueError(
                f"Holt only reads GitHub repositories, and that link points to {where}. "
                f"{EXAMPLE}"
            )

    parts = [p for p in path.strip().strip("/").split("/") if p]
    if len(parts) < 2:
        if host and parts:
            raise ValueError(
                f"That link points to the GitHub account {parts[0]!r}, not to one of "
                f"its repositories. Add the repository name, like {parts[0]}/<repo>."
            )
        raise ValueError(
            f"{raw!r} is not a repository. Holt needs the owner and the name, "
            f"separated by a slash. {EXAMPLE}"
        )
    if not host and len(parts) > 2:
        raise ValueError(
            f"{raw!r} has too many parts. Use owner/repo, or paste the full GitHub "
            f"link. {EXAMPLE}"
        )

    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if owner.lower() in _NOT_OWNERS or not _OWNER.match(owner):
        raise ValueError(f"{owner!r} is not a GitHub account name. {EXAMPLE}")
    if not _REPO.match(repo) or repo in {".", ".."}:
        raise ValueError(f"{repo!r} is not a valid repository name. {EXAMPLE}")
    return f"{owner}/{repo}"

