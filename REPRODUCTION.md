# Reproducing Holt

Written for someone starting from a clean machine with nothing installed, who
wants to check the result rather than use the tool. **If you just want to use
Holt on a repository, [USAGE.md](USAGE.md) is the shorter page.**

**The headline result needs no API key, no GitHub token, and no money.**

Use a full clone for reproduction. It includes the frozen evidence fixtures,
recorded model calls, pool definitions, labels, and result files needed to
verify the published measurements without making live API calls.

---

## What you need

| | |
|---|---|
| Python | 3.12 (pinned in `.python-version`; `uv` installs it for you) |
| Package manager | [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Disk | ~120 MB for the clone (evidence fixtures are the bulk) |
| Network | to clone and to install dependencies; **not** to reproduce the result |

Nothing else. No API key for the headline number.

---

## 1. Clone and install

```sh
git clone https://github.com/holt-oss/holt.git
cd holt
uv sync
```

`uv sync` installs the pinned Python and dependencies from `uv.lock`.

## 2. Run the tests

```sh
uv run pytest -rs
```

**Expected:** `388 passed`, no skips. **Runtime:** about two minutes.

The `-rs` flag reports skipped tests explicitly — a skipped test is not a
passing one.

Three of these are load-bearing rather than incidental: `eval/test_independence.py`
reads the import graph and fails if any label module imports the agent,
`tests/test_evidence_bounds.py` constructs a deliberately misbehaving provider
subclass to confirm it still cannot return evidence from the wrong side of the
cutoff, and `tests/test_docs_claims.py` recomputes the numbers printed in this
guide, `README.md` and `USAGE.md` from the committed results and runs every
command either guide prints — so a claim that goes stale fails the build rather
than sitting on the page.

## 3. Reproduce the headline result — no key, no spend

The frozen benchmark is three recorded live runs per pool, replayable by tag:

```sh
PYTHONPATH=. uv run python eval/harness.py --replay --run-tag run1   # pool 1
PYTHONPATH=. uv run python eval/harness.py --replay --run-tag p2r1 \
    --pool eval/pool2.json --labels eval/results_labels_pool2.json   # pool 2
```

**Runtime:** about 30 seconds each. **Cost:** $0.00.

This scores every method from committed evidence fixtures and committed model
trajectories. No network call is made and no model runs.

**Expected output for `run1`** (the results table):

```
method             MCC  balAcc     F1   sens   spec   P@10
always_viable     0.00    0.50   0.78   1.00   0.00   0.60
never_viable      0.00    0.50   0.00   0.00   1.00   0.60
name_only         0.11    0.55   0.48   0.36   0.75   0.60
popularity           -       -      -      -      -   0.70
baseline          0.02    0.51   0.64   0.64   0.38   0.50
baseline_matched   0.49    0.71   0.84   0.93   0.50   0.70
holt              0.61    0.80   0.86   0.86   0.75   0.80

spend: $0.477   graded 22/30 pool repos   positives: 14   ungraded (no post-cutoff attempts): 5
```

For `p2r1`, the holt row reads `0.63  0.82  0.85  0.81  0.83  0.90` — and it is
identical on `p2r2` and `p2r3`, because the verdict is deterministic. The
README's headline figures are means over the three runs per pool:

```sh
PYTHONPATH=. uv run python eval/aggregate.py             # pool 1, runs 1-3
PYTHONPATH=. uv run python eval/aggregate.py --pool 2    # pool 2, out of sample
PYTHONPATH=. uv run python eval/stats.py        # uncertainty over repositories
PYTHONPATH=. uv run python eval/evidence_integrity.py   # citations and yield
```

`evidence_integrity.py` scores the *report* rather than the verdict: whether
cited ids resolve, whether quoted words are in the record, and how many
checkable statements a report makes. It reads the same six frozen runs. This is
the axis on which the verdict layer scores zero, and it is reported because MCC
cannot see it.

The `spend` figure is what the recorded run cost when it was made; replaying it
costs nothing.

**Matthews correlation is the primary metric**, because it is 0.00 for any
constant answer. F1 and precision@10 are reported alongside it precisely because
they are not: answering "viable" to everything scores F1 0.78, above the baseline
solution. The constant strategies are scored as methods so the floor is visible.
See the changelog.

## 4. Run both solutions on one repository — still no key

The benchmark compares Holt with a one-prompt baseline. Both are
runnable, on the same repository, from the same evidence:

```sh
# baseline: one prompt over README and metadata
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --baseline --replay

# the full pipeline
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay
```

Each prints a Markdown assessment. Both declare, in the output itself, that they
are replaying recorded model output rather than calling a model.

The disagreement worth looking at is `is-a-dev/register`, a domain registry with
hundreds of merged outsider pull requests and no software contributions:

```sh
PYTHONPATH=. uv run holt analyze is-a-dev/register --baseline --replay   # viable
PYTHONPATH=. uv run holt analyze is-a-dev/register --replay              # not_viable
```

To watch verification remove unsupported findings:

```sh
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay --show-verification
```

Findings whose evidence ids do not resolve are printed as `DROPPED` on stderr and
never appear in the report.

The other commands run from the same committed evidence, still with no key:

```sh
# a shortlist, side by side; rows in the order you asked for
PYTHONPATH=. uv run holt compare runelite/plugin-hub NixOS/nixpkgs --replay

# open issues ranked for someone who has merged work there; no model call at all
PYTHONPATH=. uv run holt next NixOS/nixpkgs --as mweinelt

# a recorded discovery session: sourcing, free screening, survivor analyses
PYTHONPATH=. uv run holt discover
```

`discover` states in its own output that it is replaying a recorded session and
which GitHub search produced the candidates. `next` prints its measured numbers
— including the interval that spans zero — above every ranking.

## 5. Verify the pool was not chosen to flatter the result

```sh
PYTHONPATH=. uv run python eval/sample_pool.py     # dry run, writes nothing
```

Re-draws the pool from the committed frame using the committed seed. It prints
the same 30 repositories that are in `eval/pool.json`, whose sha256 is recorded
inside the file. `is-a-dev/register` appears because the seed put it there.

## 6. Re-run the labels

**Needs the full clone**, not the zip: this is the one section that reads
`fixtures/post_t/`.

```sh
PYTHONPATH=. uv run python eval/run_labels.py
```

Recomputes L0 and L1 from post-cutoff fixtures and prints the rank movement
between them. `runelite/plugin-hub` moves from 1st to 22nd. **Runtime:** ~20s,
**cost:** $0.00.

---

## Running against a live model (optional, costs money)

Only needed to re-record trajectories or analyse a repository not in the pool.

```sh
export OPENAI_API_KEY=...
PYTHONPATH=. uv run python eval/harness.py            # full sweep, ~$0.36, ~25 min
PYTHONPATH=. uv run python eval/harness.py --resume   # only repositories not yet recorded
```

Models are pinned to dated ids (`gpt-5-mini-2025-08-07`) in `src/holt/model.py`,
not floating aliases, so a recorded run cannot drift underneath you.

Replay refuses to serve a recording whose prompt has changed rather than
answering a question that is no longer being asked. If you edit a prompt, replay
will fail loudly and you will need to re-record.

## Analysing any repository live (optional)

```sh
export OPENAI_API_KEY=...
export GITHUB_TOKEN=...      # a classic token with NO scopes is sufficient
PYTHONPATH=. uv run holt analyze owner/name --live
```

A zero-scope token still gets 5,000 GraphQL points an hour, which is ample. Holt
reads public data only and never writes.

**Cost:** about $0.012 a repository. **Runtime:** about 40 seconds.

## Rebuilding the sampling frame from scratch (optional, slow)

```sh
./scripts/fetch_gharchive.sh 2026-05-28 2026-05-29 2026-05-30   # ~1.9 GB, ~15 min
uv run python eval/build_frame.py                               # ~6 min
```

Only needed to verify the frame itself. `eval/frame.json` is committed, so the
pool draw can be checked without this.

---

## Costs and runtimes at a glance

| Task | Key needed | Runtime | Cost |
|---|---|---|---|
| Tests | no | ~2 min | $0.00 |
| **Headline result (`--replay`)** | **no** | **30 s** | **$0.00** |
| Both solutions on one repo | no | 5 s | $0.00 |
| Re-run labels | no | 20 s | $0.00 |
| Verify the pool draw | no | 10 s | $0.00 |
| Full live sweep | yes | ~25 min | ~$0.36 |
| One repository live | yes + GitHub | ~40 s | ~$0.012 |
| Rebuild the frame | no | ~20 min | $0.00 |

---

## If something fails

**`No recorded response for <stage>`** — a prompt or a stage's model was changed
after the trajectories were recorded. That is the replay guard working. Re-record
with a key, or check out the committed state.

**`ContaminationError`** — evidence from the wrong side of the cutoff reached a
provider. This is a bug, not a condition to handle; the run should stop.

**`GITHUB_TOKEN is not set`** — you are on the live path. The headline result does
not need it; use `--replay`.
