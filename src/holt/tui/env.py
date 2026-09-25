"""Reading `.env`, for the interface only.

`holt analyze` deliberately does not do this: the reproduction path should need
nothing but `--replay`, and a command whose behaviour depends on an untracked
file in the working directory is harder to reason about, not easier. The
interface is the one place where a person is sitting down to do several live
runs in a row, and re-exporting two variables each time is friction with no
purpose.

Values already in the environment win. `.env` fills gaps; it never overrides
something the user set deliberately for one run.

The file is in `.gitignore`. Nothing here writes to it, prints its contents, or
puts a value in an event, a log line or the interface.
"""

from __future__ import annotations

import os
from pathlib import Path


def load(path: str | Path = ".env") -> list[str]:
    """Set any variables `.env` defines that are not already set.

    Returns the names it filled in — names only, never values — so a caller can
    say where a credential came from without disclosing it.
    """
    file = Path(path)
    if not file.is_file():
        return []

    filled: list[str] = []
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not name or not value or os.environ.get(name):
            continue
        os.environ[name] = value
        filled.append(name)
    return filled
