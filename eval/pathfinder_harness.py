"""Score Path Finder against the comparators that could make it unnecessary.

Precision at k, computed per repository and averaged. Never pooled: on pool 1
one repository holds 71 of 114 realised entry points, and pooling would let it
decide the result on its own.

Comparators, all on the identical candidate set:

  random        the base rate. Any ranking must beat picking blind.
  recency       newest issue first. The obvious free heuristic.
  good_first    GitHub's own beginner labels first. **The one that matters** --
                Holt's whole premise is that existing signals do not tell a
                contributor what they need, and if the label ties us here the
                feature has no argument for existing.

Run:  PYTHONPATH=. uv run python eval/pathfinder_harness.py [--replay]
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from eval.labels import pathfinder
from holt.agent import entry
from holt.evidence.fixtures import FixtureProvider
from holt.model import OpenAIModel, ReplayModel, TRAJECTORY_DIR
from holt.types import Window

ISSUE_ROOT = Path("fixtures/issues")
K = 3

BEGINNER = ("good first issue", "good-first-issue", "beginner", "easy",
            "starter", "first-timers-only", "help wanted", "e-easy")


def is_beginner(record) -> bool:
    return any(
        any(b in label.lower() for b in BEGINNER)
        for label in (record.payload.get("labels") or [])
    )


def precision_at_k(ranked_keys: list[str], hits: set[str], k: int = K) -> float | None:
    top = ranked_keys[:k]
    return (sum(1 for x in top if x in hits) / len(top)) if top else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--pool", default="eval/pool.json")
    ap.add_argument("--labels", default="eval/results_labels.json")
    ap.add_argument("--out", help="write per-repository scores here, so pools combine "
                                  "without re-running either")
    args = ap.parse_args()

    ipre = FixtureProvider(Window.PRE_T, root=ISSUE_ROOT)
    ipost = FixtureProvider(Window.POST_T, root=ISSUE_ROOT)
    ppre = FixtureProvider(Window.PRE_T)

    lab = json.loads(Path(args.labels).read_text())["l1"]
    viable = {
        s for s, r in lab.items()
        if r["qualifying_merges"] >= 2 and r["distinct_qualifying_contributors"] >= 2
    }
    repos = [s for s in json.loads(Path(args.pool).read_text())["repos"] if s in viable]

    scores = {"holt": [], "recency": [], "good_first": [], "random": []}
    per_repo: dict[str, dict] = {}
    skipped_small = skipped_empty = 0
    spend = 0.0
    edited = candidates_total = 0
    coverage: list[tuple[str, int, int]] = []

    for slug in repos:
        try:
            pre_i, post_i, pre_p = ipre.fetch(slug), ipost.fetch(slug), ppre.fetch(slug)
        except FileNotFoundError:
            continue
        truth = pathfinder.score(list(pre_i) + list(pre_p), post_i)
        if not truth["scorable"]:
            skipped_small += 1
            continue
        if truth["realised"] == 0:
            skipped_empty += 1
            continue

        cand = pathfinder.candidates(pre_i)
        hits = set(truth["realised_keys"])
        labelled = sum(1 for r in cand.values() if is_beginner(r))
        coverage.append((slug, len(cand), labelled))
        edited += truth["edited_after_cutoff"]
        candidates_total += truth["candidates"]

        by_recent = sorted(cand.values(), key=lambda r: r.timestamp, reverse=True)
        scores["recency"].append(precision_at_k([pathfinder.issue_key(r.evidence_id) for r in by_recent], hits))
        by_label = [r for r in by_recent if is_beginner(r)] + [r for r in by_recent if not is_beginner(r)]
        scores["good_first"].append(precision_at_k([pathfinder.issue_key(r.evidence_id) for r in by_label], hits))
        scores["random"].append(truth["base_rate"])

        path = TRAJECTORY_DIR / "pathfinder" / (slug.replace("/", "__") + ".jsonl")
        model = ReplayModel(path) if args.replay else OpenAIModel(path, record=True)
        # The same call the CLI makes. If these diverged, the published precision
        # would describe something no user ever runs.
        ranked = entry.rank(slug, list(pre_i), list(pre_p), model)
        keys = [pathfinder.issue_key(r["evidence_id"]) for r in ranked]
        scores["holt"].append(precision_at_k(keys, hits))
        per_repo[slug] = {name: scores[name][-1] for name in scores}
        spend += getattr(model.usage, "cost_usd", 0.0)
        print(f"  {slug:<38} p@{K} holt={scores['holt'][-1]:.2f} "
              f"gfi={scores['good_first'][-1]:.2f} recent={scores['recency'][-1]:.2f} "
              f"base={truth['base_rate']:.2f}", flush=True)

    n = len(scores["holt"])
    print(f"\nprecision@{K}, mean over {n} scorable repositories")
    print(f"(excluded: {skipped_small} under the 10-issue floor, "
          f"{skipped_empty} with no realised entry point)\n")
    for name in ("random", "recency", "good_first", "holt"):
        vals = [v for v in scores[name] if v is not None]
        if vals:
            print(f"  {name:<12} {statistics.mean(vals):.3f}")
    if coverage:
        # Without this, the good_first row is quietly misread. Where a repository
        # has no labelled issue the comparator reorders nothing and *is* recency,
        # so "we tied the label" would really mean "we tied recency" on that repo.
        none_at_all = sum(1 for _, _, lab in coverage if lab == 0)
        under_k = sum(1 for _, _, lab in coverage if lab < K)
        total_lab = sum(lab for _, _, lab in coverage)
        print(f"\n`good first issue` coverage across the same repositories:")
        print(f"  {none_at_all}/{len(coverage)} have no beginner-labelled issue at all")
        print(f"  {under_k}/{len(coverage)} have fewer than {K}, so the label comparator "
              f"cannot fill a top-{K} and degenerates to recency there")
        print(f"  {total_lab}/{candidates_total} candidate issues carry a beginner label "
              f"({100*total_lab/candidates_total:.1f}%)")
    if candidates_total:
        print(f"\nissue bodies edited after the cutoff: {edited}/{candidates_total} "
              f"({100*edited/candidates_total:.1f}%) — the known leak, measured")
    print(f"spend: ${spend:.3f}")
    if args.out:
        Path(args.out).write_text(json.dumps({
            "pool": args.pool,
            "per_repo": per_repo,
            "skipped_small": skipped_small,
            "skipped_empty": skipped_empty,
            "coverage": {slug: {"candidates": n, "labelled": lab} for slug, n, lab in coverage},
            "edited_after_cutoff": edited,
            "candidates": candidates_total,
        }, indent=2) + "\n")
        print(f"per-repository scores: {args.out}")


if __name__ == "__main__":
    main()
