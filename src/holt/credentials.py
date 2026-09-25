"""Finding a GitHub token without making a beginner hunt for one.

Holt only reads public data, but GitHub's API still wants a token, and "go and
set an environment variable" is where a lot of first runs end. So the token is
looked for in three places, in order:

1. `GITHUB_TOKEN` in the environment — an explicit choice always wins.
2. A token saved with `holt token` or the interface's first-run prompt, in the
   config directory, readable only by you (0600).
3. `gh auth token`, when the GitHub CLI is installed and logged in.

Whatever is found is put into `GITHUB_TOKEN` for this process, which is where the
evidence layer reads it. A token value is never printed or logged; only where it
came from is.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from holt import paths

#: Pre-filled token form. A classic token with no scopes reads public data,
#: which is all Holt ever does.
TOKEN_URL = "https://github.com/settings/tokens/new?description=holt"

ENV = "GITHUB_TOKEN"


def token_path() -> Path:
    return paths.config_dir() / "credentials.toml"


def saved_token(path: Path | None = None) -> str:
    path = path or token_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return str(data.get("github_token", "")).strip()


def save_token(token: str, path: Path | None = None) -> Path:
    """Write the token where only this user can read it."""
    token = token.strip()
    if not token or any(c in token for c in "\"\\\n\r"):
        raise ValueError("That does not look like a GitHub token.")
    path = path or token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Created 0600 rather than chmod-ed after, so there is no moment when the
    # file exists with wider permissions. Windows ignores the mode; the file
    # sits in the per-user profile there.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f'github_token = "{token}"\n')
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    os.environ[ENV] = token
    return path


def gh_token() -> str:
    """`gh auth token`, or "" when gh is absent, logged out, or slow."""
    if os.environ.get("HOLT_DISABLE_GH"):
        return ""
    gh = shutil.which("gh")
    if not gh:
        return ""
    try:
        done = subprocess.run(
            [gh, "auth", "token"], capture_output=True, text=True, timeout=5,
            encoding="utf-8",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def find_token() -> tuple[str, str]:
    """`(token, where it came from)`, or `("", "")`."""
    if token := os.environ.get(ENV, "").strip():
        return token, ENV
    if token := saved_token():
        return token, str(token_path())
    if token := gh_token():
        return token, "gh auth token"
    return "", ""


def ensure_token() -> str:
    """Find a token and export it for this process. Returns where it came from."""
    token, source = find_token()
    if token:
        os.environ[ENV] = token
    return source


def missing_token_message() -> str:
    """What to do when there is no token anywhere. Plain English, exact steps."""
    return (
        "Holt needs a GitHub token to read a repository's pull requests.\n"
        "It only reads public data, so the token needs no permissions.\n"
        "\n"
        f"  1. Create one (leave every box unticked): {TOKEN_URL}\n"
        "  2. Save it:  holt token\n"
        "\n"
        "Or, if you use the GitHub CLI:  gh auth login\n"
        "Or set it for this terminal only:\n"
        "  macOS/Linux:  export GITHUB_TOKEN=<your token>\n"
        "  PowerShell:   $env:GITHUB_TOKEN = \"<your token>\""
    )
