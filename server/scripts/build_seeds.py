"""Build server/holt_server/seeds/repos.txt, the warm cache's seed list.

    GITHUB_TOKEN=... uv run python server/scripts/build_seeds.py [--total 300]

Uses the same sourcing as `holt start` / `/v1/find` (holt.starter): repositories
with the hacktoberfest topic, plus beginner-friendly repositories (open
good-first-issue style issues, recently active, not archived or forks) in each
of the top languages. Read-only; roughly two GraphQL searches per language.
Re-run it to refresh the list, and commit the result.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "holt_server" / "seeds" / "repos.txt"
LANGUAGES = ["python", "javascript", "typescript", "java", "go", "rust", "c++", "c",
             "c#", "php", "ruby", "kotlin"]
HACKTOBERFEST_SHARE = 0.4


def build(total: int, token: str) -> tuple[list[str], dict[str, int]]:
    from holt.starter import GitHub, source_candidates

    transport = GitHub(token=token)
    now = datetime.now(UTC)
    hack = source_candidates(transport, [], [], True, now, int(total * HACKTOBERFEST_SHARE))
    per_lang = {lang: source_candidates(transport, [lang], [], False, now, 40)
                for lang in LANGUAGES}
    picked: list[str] = []
    seen: set[str] = set()

    def add(repo: str) -> None:
        if repo.lower() not in seen and len(picked) < total:
            seen.add(repo.lower())
            picked.append(repo)

    for repo in hack:
        add(repo)
    # Round-robin over languages so each gets a fair share of what is left.
    for i in range(max((len(v) for v in per_lang.values()), default=0)):
        for repos in per_lang.values():
            if i < len(repos):
                add(repos[i])
    counts = {"hacktoberfest": len(hack), **{k: len(v) for k, v in per_lang.items()}}
    return picked, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--total", type=int, default=300)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 1
    repos, counts = build(args.total, token)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# Warm-cache seed repositories (holt_server/warm.py). One owner/repo per line.",
        f"# Generated {datetime.now(UTC).date().isoformat()} by server/scripts/build_seeds.py;",
        "# re-run it to refresh. Sourced like /v1/find: the hacktoberfest topic, then",
        f"# beginner-friendly repositories in {', '.join(LANGUAGES)}.",
        f"# Candidates found: {', '.join(f'{k} {v}' for k, v in counts.items())}.",
        "",
    ]
    args.out.write_text("\n".join(header + repos) + "\n", encoding="utf-8")
    print(f"wrote {len(repos)} repositories to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
