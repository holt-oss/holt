"""Give the per-repository trajectories the baseline calls they never had.

`holt analyze <repo> --baseline --replay` is a documented command and the
documented benchmark baseline command, but it failed from a clean clone on every
repository: `model.build` reads `fixtures/trajectories/<repo>.jsonl`, and the
baseline call was only ever recorded under the run-tagged directories the
evaluation harness reads. The benchmark was unaffected, which is why it went
unnoticed.

Nothing is re-recorded here and no model runs. A tagged run's `baseline` entry
is keyed on (label, model, system, prompt) exactly as the CLI computes it, so
the recording already answers the CLI's question; it was simply filed where the
CLI does not look.

Run: PYTHONPATH=. uv run python scripts/backfill_baseline_trajectories.py
"""

from __future__ import annotations

import json
from pathlib import Path

TRAJECTORIES = Path("fixtures/trajectories")
# Where the harness files its recordings, in preference order.
TAGGED = ["run1", "run2", "run3", "p2r1", "p2r2", "p2r3", "m1", "m2", "m3"]
WANTED = ("baseline", "baseline_matched")


def entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    filled = missing = 0
    for root in sorted(TRAJECTORIES.glob("*.jsonl")):
        have = entries(root)
        present = {e["key"] for e in have}
        labels = {e["label"] for e in have}
        if WANTED[0] in labels:
            continue

        added: list[dict] = []
        for tag in TAGGED:
            candidate = TRAJECTORIES / tag / root.name
            if not candidate.exists():
                continue
            for e in entries(candidate):
                if e["label"] in WANTED and e["key"] not in present:
                    present.add(e["key"])
                    added.append(e)
            if added:
                break

        if not added:
            missing += 1
            print(f"  no tagged recording for {root.name}")
            continue

        # Baseline calls go first: they are a separate solution, not a stage of
        # the pipeline, and reading the file top-down should say so.
        with root.open("w") as fh:
            for e in added + have:
                fh.write(json.dumps(e) + "\n")
        filled += 1

    print(f"backfilled {filled} trajectories; {missing} had no tagged recording")


if __name__ == "__main__":
    main()
