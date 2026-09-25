"""Score every method against the L1 ground truth over the committed pool.

Methods, all given the same repositories and the same pre-cutoff evidence:

  popularity     stars + recency, which is what people use today
  baseline       the baseline solution: one prompt over README and metadata
  holt           the full pipeline
  name_only      a memorisation probe: the repository name and nothing else

The probe is not a solution. It exists to measure how much of any method's
performance is the model recognising a famous repository rather than reading
evidence. If it scores well, the holdout is compromised and every other number
here is suspect.

Run:  PYTHONPATH=. uv run python eval/harness.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from holt import baseline as baseline_solution
from holt import baseline_matched
from holt.agent.pipeline import analyze
from holt.evidence.fixtures import FixtureProvider
from holt.model import OpenAIModel, PatchModel, ReplayModel, TRAJECTORY_DIR
from holt.report import Verdict
from holt.types import Window

POOL = Path("eval/pool.json")
LABELS = Path("eval/results_labels.json")
OUT = Path("eval/results_eval.json")

# A repository counts as a genuine opportunity when at least two distinct people
# landed a qualifying contribution after the cutoff. One person twice is an
# anecdote; the threshold is declared here rather than tuned later.
MIN_MERGES, MIN_PEOPLE = 2, 2

PROBE_SYSTEM = """You are told only a repository's name. Say whether an outside \
developer could realistically land a meaningful contribution there.

You have no evidence beyond the name. Answer from what you already know."""
PROBE_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": [v.value for v in Verdict]}},
    "required": ["verdict"],
    "additionalProperties": False,
}


def truth(labels: dict) -> tuple[dict[str, bool], list[str]]:
    """Ground truth, and the repositories that have none.

    A repository nobody attempted after the cutoff is not a repository that
    rejects people. Scoring it as a negative punishes a method for saying
    "viable" about a project whose viability was never tested, which is a
    different mistake from recommending somewhere hostile.

    This third bucket was defined in the plan and in the L1 changelog entry
    before any method ran. The first version of this harness collapsed it into
    the negative class, which cost Holt three false positives it had not earned
    and is corrected here.
    """
    gold, ungraded = {}, []
    for slug, r in labels["l1"].items():
        if r["bucket"] == "insufficient_evidence":
            ungraded.append(slug)
            continue
        gold[slug] = (
            r["qualifying_merges"] >= MIN_MERGES
            and r["distinct_qualifying_contributors"] >= MIN_PEOPLE
        )
    return gold, ungraded


def score(name: str, calls: dict[str, Verdict], gold: dict[str, bool]) -> dict:
    """Score a method, including the metrics that a constant answer cannot fake.

    F1 was the original primary metric and it is degenerate on this pool: 14 of
    22 repositories are genuine opportunities, so answering "viable" to
    everything scores F1 0.78 -- above the baseline solution. Matthews
    correlation is reported alongside it because it is 0.00 for any constant
    strategy, and balanced accuracy because it is 0.50 for one. Both are shown,
    and the constant strategies are scored as methods so the reader can see the
    floor rather than take our word for where it is.
    """
    judged = {s: v for s, v in calls.items() if s in gold}
    recommended = [s for s, v in judged.items() if v is Verdict.VIABLE]
    tp = sum(1 for s in recommended if gold[s])
    fp = len(recommended) - tp
    fn = sum(1 for s, v in judged.items() if v is not Verdict.VIABLE and gold[s])
    tn = len(judged) - tp - fp - fn
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn) - (fp * fn)) / denom if denom else 0.0
    positives = sum(1 for s in judged if gold[s])
    # Categorical verdicts have no inherent order, so ties inside a class are
    # broken alphabetically. Declared, because it means precision@10 for these
    # methods carries some luck that a ranked method's does not.
    order = {Verdict.VIABLE: 2, Verdict.INSUFFICIENT_EVIDENCE: 1, Verdict.NOT_VIABLE: 0}
    ranked = sorted(judged, key=lambda s: (-order[judged[s]], s))
    top10 = ranked[:10]
    precision = (tp / len(recommended)) if recommended else None
    recall = (tp / positives) if positives else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and (precision + recall)
        else 0.0
    )
    return {
        "method": name,
        "judged": len(judged),
        "recommended": len(recommended),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "mcc": mcc,
        "balanced_accuracy": (sensitivity + specificity) / 2,
        "sensitivity": sensitivity,
        "specificity": specificity,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision_at_10": sum(1 for s in top10 if gold[s]) / len(top10) if top10 else None,
        "top10": top10,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--replay", action="store_true", help="score recorded runs, no spend")
    ap.add_argument("--patch", action="store_true",
                    help="replay unchanged calls, re-record only what a code "
                         "change touched; leaves the recorded results file alone")
    ap.add_argument("--resume", action="store_true", help="skip repositories already recorded")
    ap.add_argument("--pool", default=str(POOL), help="pool file to score against")
    ap.add_argument("--labels", default=str(LABELS), help="ground-truth file for that pool")
    ap.add_argument(
        "--run-tag",
        default="",
        help="record into fixtures/trajectories/<tag>/ so repeated runs stay separate",
    )
    args = ap.parse_args()

    pool = json.loads(Path(args.pool).read_text())
    gold, ungraded = truth(json.loads(Path(args.labels).read_text()))
    repos = [r for r in pool["repos"] if r in gold]
    if args.replay:
        # Score whatever has been recorded. A partial run is still a result, as
        # long as the count it was computed over is stated with it.
        root_ = TRAJECTORY_DIR / args.run_tag if args.run_tag else TRAJECTORY_DIR
        repos = [r for r in repos if (root_ / (r.replace("/", "__") + ".jsonl")).exists()]
    elif args.resume:
        done = [r for r in repos if (TRAJECTORY_DIR / (r.replace("/", "__") + ".jsonl")).exists()]
        print(f"resuming: {len(done)} already recorded, {len(repos) - len(done)} to run")
        repos = [r for r in repos if r not in set(done)]
    if args.limit:
        repos = repos[: args.limit]

    pre = FixtureProvider(Window.PRE_T)
    calls: dict[str, dict[str, Verdict]] = {
        "baseline": {}, "baseline_matched": {}, "holt": {}, "name_only": {}
    }
    popularity: dict[str, int] = {}
    spend = 0.0

    root = TRAJECTORY_DIR / args.run_tag if args.run_tag else TRAJECTORY_DIR

    def client(slug: str):
        path = root / (slug.replace("/", "__") + ".jsonl")
        if args.replay:
            return ReplayModel(path)
        if args.patch:
            return PatchModel(path)
        return OpenAIModel(path, record=True)

    skipped: list[str] = []
    for i, slug in enumerate(repos, 1):
      try:
        records = pre.fetch(slug)
        meta = next((r.payload for r in records if r.evidence_id.endswith(":meta")), {})
        popularity[slug] = meta.get("stargazer_count") or 0

        m = client(slug)
        calls["baseline"][slug] = baseline_solution.assess(slug, pre, m).verdict
        calls["baseline_matched"][slug] = baseline_matched.assess(slug, pre, m).verdict
        assessment, _ = analyze(slug, pre, m)
        calls["holt"][slug] = assessment.verdict
        probe = m.complete(
            label="name_only", system=PROBE_SYSTEM, prompt=f"Repository: {slug}",
            schema=PROBE_SCHEMA,
        )
        calls["name_only"][slug] = Verdict(probe["verdict"])
        spend += m.usage.cost_usd
        print(f"[{i}/{len(repos)}] {slug}: baseline={calls['baseline'][slug].value} "
              f"holt={calls['holt'][slug].value} probe={calls['name_only'][slug].value}", flush=True)
      except (KeyError, Exception) as exc:
        # A run cut short mid-repository leaves a partial trajectory. Drop that
        # repository from scoring rather than losing the whole result, and say
        # how many were dropped alongside the numbers.
        for c in calls.values():
            c.pop(slug, None)
        popularity.pop(slug, None)
        skipped.append(slug)
        print(f"[{i}/{len(repos)}] {slug}: SKIPPED ({type(exc).__name__})", flush=True)

    # The floor, scored as methods rather than described. If a constant answer
    # beats a real one on some metric, that is a fact about the metric.
    graded = [s for s in calls["holt"] if s in gold]
    calls["always_viable"] = {s: Verdict.VIABLE for s in graded}
    calls["never_viable"] = {s: Verdict.NOT_VIABLE for s in graded}

    results = [score(n, c, gold) for n, c in calls.items()]

    if not graded:
        raise SystemExit(
            "No repository could be scored: the trajectory root has no complete "
            "recordings for this pool. The frozen benchmark runs live under "
            "--run-tag run1/run2/run3 (pool 1) and p2r1/p2r2/p2r3 (pool 2)."
        )

    # Popularity has a real ordering, so its precision@10 is a true ranked score.
    ranked = sorted(popularity, key=lambda s: -popularity[s])[:10]
    results.append({
        "method": "popularity",
        "judged": len(popularity),
        "recommended": None,
        "precision": None,
        "recall": None,
        "precision_at_10": sum(1 for s in ranked if gold[s]) / len(ranked),
        "top10": ranked,
    })

    order = {"always_viable": 0, "never_viable": 1, "name_only": 2,
             "popularity": 3, "baseline": 4, "baseline_matched": 5, "holt": 6}
    results.sort(key=lambda r: order.get(r["method"], 9))
    print(f"\n{'method':<15} {'MCC':>6} {'balAcc':>7} {'F1':>6} {'sens':>6} {'spec':>6} {'P@10':>6}")
    for r in results:
        p = lambda x: f"{x:.2f}" if isinstance(x, float) else "     -"
        print(f"{r['method']:<15} {p(r.get('mcc')):>6} {p(r.get('balanced_accuracy')):>7} "
              f"{p(r.get('f1')):>6} {p(r.get('sensitivity')):>6} "
              f"{p(r.get('specificity')):>6} {p(r['precision_at_10']):>6}")
    print("\nMCC is 0.00 and balanced accuracy 0.50 for any constant answer; "
          "F1 is not, which is why the constants are listed.")
    scored_repos = [r for r in repos if r not in skipped]
    scored_repos = [r for r in scored_repos if r in gold]
    print(f"\nspend: ${spend:.3f}   graded {len(scored_repos)}/{len(pool['repos'])} pool repos"
          f"   positives: {sum(gold[s] for s in scored_repos)}"
          f"   ungraded (no post-cutoff attempts): {len(ungraded)}")
    if skipped:
        print(f"skipped (incomplete recording): {skipped}")

    if args.patch:
        # A patch pass heals recordings; the verdicts are identical by
        # construction, and the recorded run's spend figure must not be
        # overwritten with the patch's much smaller one.
        print("patch pass: recordings healed; results file left as recorded")
        return

    out_path = OUT.with_name(f"results_eval_{args.run_tag}.json") if args.run_tag else OUT
    out_path.write_text(json.dumps({
        "pool_sha256": pool["sha256"],
        "truth_rule": f"qualifying_merges>={MIN_MERGES} and contributors>={MIN_PEOPLE}",
        "ungraded_no_attempts": ungraded,
        "results": results,
        "verdicts": {n: {s: v.value for s, v in c.items()} for n, c in calls.items()},
        "spend_usd": round(spend, 4),
        "run_tag": args.run_tag,
    }, indent=1) + "\n")


if __name__ == "__main__":
    main()
