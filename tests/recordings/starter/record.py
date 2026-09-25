"""Re-record the `holt start` fixtures from live GitHub. Not run by the tests.

    GITHUB_TOKEN=... uv run python tests/recordings/starter/record.py

Writes `find.json` (a small `find`) and `repo.json` (one `starter_issues`).
Each is the list of GraphQL responses keyed by `starter.query_key`, plus the
`as_of` the run used, so replaying with the same arguments asks the same
questions. The token travels in a header and is never recorded; credential
formats in bodies are scrubbed, and long bodies and documents are cut to keep the files small.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from holt import starter
from holt.evidence.redact import redact_payload

HERE = Path(__file__).parent
FIND_ARGS = {"languages": ["python"], "topics": [], "hacktoberfest": True,
             "max_repos": 3, "per_repo": 3, "limit": 3}
REPO = "ManimCommunity/manim"
MAX_BODY = 600


def _trim(value):
    if isinstance(value, dict):
        return {k: (v[:MAX_BODY] if k in ("body", "text") and isinstance(v, str) else _trim(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_trim(v) for v in value]
    return value


def _save(name: str, as_of: datetime, recorded: list[dict]) -> None:
    calls = []
    for call in recorded:
        clean, _ = redact_payload(_trim(call))
        calls.append(clean)
    path = HERE / name
    path.write_text(json.dumps({"as_of": as_of.isoformat(), "calls": calls},
                               indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(calls)} calls)", file=sys.stderr)


def main() -> None:
    as_of = datetime.now(UTC).replace(microsecond=0)

    recorded: list[dict] = []
    gh = starter.GitHub(recorder=recorded)
    starter.find(token=None, transport=gh, as_of=as_of, budget_seconds=120,
                 progress=lambda s: print(s, file=sys.stderr), **FIND_ARGS)
    _save("find.json", as_of, recorded)

    recorded = []
    gh = starter.GitHub(recorder=recorded)
    starter.starter_issues(REPO, None, as_of=as_of, transport=gh)
    _save("repo.json", as_of, recorded)


if __name__ == "__main__":
    main()
