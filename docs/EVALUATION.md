# How Holt is evaluated

Holt's product output is a recommendation, so its quality has to be inspectable.
This document explains how the benchmark pool was built, how ground truth is
computed, what the result is sensitive to, and what it does not cover. Exact
commands are in [REPRODUCTION.md](../REPRODUCTION.md).

---

## Evaluation design

**Temporal holdout at T = 2026-06-01.** The agent sees only evidence dated at or
before T. Labels are computed only from evidence after it. T sits just past the
models' training cutoff so that the label window falls outside training data;
moving T earlier would drag the label window *into* it, which is the leak that
actually matters.

**The pool is sampled from history, not from today.** GitHub search returns
today's stars and today's activity whatever date filter you apply, so a pool
drawn from it is pre-filtered for repositories that survived. Holt's pool is
sampled from GH Archive events over three contiguous days before T — repositories
as they appeared at the cutoff, with no knowledge of which lived. **Three of the
thirty were deleted before the run**; a search-based sample would have silently
excluded all three.

**Three things about the pool, stated rather than buried:**

- `is-a-dev/register` was **drawn, not placed**. The seed (`20260601`) is
  committed and the draw is verifiable by re-running `eval/sample_pool.py`.
- The busiest volume band drew **6 of 8 available** — a near-census, not a
  sample. "Stratified random" is accurate for three bands and approximately
  exhaustive for the fourth.
- The universe is **1,674 of 40,731** repositories, filtered to those with at
  least two distinct human pull request openers. A repository with one opener
  carries no outsider signal at all.

**The pool is hash-committed** (`eval/pool.json`, sha256 `f100b2209c…`) and was
never edited after results were seen.

**Labels are computed, never hand-judged**, and shipped in two versions. L0 is
the naive outsider merge rate. L1 adds bot exclusion, a diff-shape filter and a
human-review requirement. Both are run; the gap between them is in the changelog.

---

## Measured performance

The frozen benchmark compares Holt with progressively stronger one-prompt
baselines. Scores are mean Matthews correlation coefficient (MCC) across three
recorded runs; higher is better and `0.00` is chance-level correlation.

| Method | Pool 1 | Pool 2 |
|---|---:|---:|
| Repository name only | 0.16 | 0.10 |
| README, one prompt | 0.09 | 0.21 |
| Same evidence as Holt, one prompt | — | 0.32 |
| **Holt** | **0.61** | **0.63** |

Holt returned the same verdict in all three runs for **22 of 22** repositories
in pool 1, compared with **17 of 22** for the README baseline. Across both
pools, Holt was stable on **55 of 55** repositories; the baseline changed its answer on 16 of 55. These figures describe the committed benchmark, not a
guarantee for every repository or model.

---

## What this result depends on

Two sensitivities a reader would otherwise have to find themselves. Both are
reproducible with `PYTHONPATH=. uv run python eval/sensitivity.py`.

**The ground truth is our own definition.** L1 keeps an outsider merge only if
the diff is *substantive* and a human *reviewed* it — both filters chosen by
us, so the honest question is what happens when either is dropped. On the
earlier recorded runs this was a real vulnerability: dropping `substantive`
flipped the advantage to the baseline. On the frozen runs it no longer does —
Holt leads under **every** variant, though the margin narrows to +0.11 at its
thinnest. Mean MCC over the three frozen runs:

| Ground truth | Positives | Holt | Baseline |
|---|---|---|---|
| L1 as shipped | 14/22 | **+0.61** | +0.09 |
| drop the `reviewed` filter | 16/22 | **+0.60** | +0.01 |
| drop the `substantive` filter | 16/22 | **+0.39** | +0.28 |
| drop both (≈ the naive L0) | 18/22 | **+0.38** | +0.22 |

**The lead survives every variant, and the diff-shape filter is where most of
it lives.** Drop that filter and Holt still leads, +0.39 against +0.28, but the
margin is a third of what it was: most of Holt's advantage is against a ground
truth that counts *what a merged contribution changed*.

We think that is the right definition, and it is the first claim this project
makes rather than one introduced afterwards: a merged pull request that appends a
line to a JSON manifest is not a software contribution. A reader who rejects that
premise should reject the project, not just the number. The dependency is real,
it is not hidden, and it is one filter deep.

The honest tension: Stage A's prompt tells the model to judge a repository by
what its merged diffs touch, which is the same concept the `substantive` filter
encodes mechanically. Label and agent operationalise one construct two ways —
one by rule, one by judgement. That is not code sharing, and the temporal split
is intact, but it is closer than "the agent shares no diff-shape rules" implies.

---

## Known limitations

**L1 counts programme-cohort review as review.** Nine repositories in the pool
are GirlScript Summer of Code '26 projects with a points leaderboard — grep
`gssoc` in `fixtures/post_t/leonagoel__hybrid-recommender.json` and you will find
1,605 mentions. Leaderboard-driven pull requests are substantive by our diff-shape
filter and mentors do comment on them, so those repositories label as viable.
"A stranger's patch lands here" is *true* of them. Whether a week spent there is
the opportunity this tool is meant to find is a separate question our ground truth
does not ask, and we did not discover this until it broke a different experiment
(`eval/mover_controls.py`). The labels are hash-committed and were not touched
after the fact.

- **22 of 30 repositories graded** in pool 1. Three were deleted between the
  cutoff and the run; five had no post-cutoff outsider attempts to grade against.
- **Three runs per pool, so the ±0.00 half-ranges measure run-to-run stability
  rather than sampling error.** Sampling error is measured separately, over
  repositories: the Holt−baseline gap is large but not yet formally
  distinguishable at n=22 — see measured performance above.
- **The memorisation probe reaches 0.71 precision knowing only repository
  names.** Some of every method's score here is recognition rather than reading.
  Its recall is 0.36, which bounds how much.
- **Three repositories sit at GitHub search's 1000-result ceiling**, so their
  label figures are a sample rather than a census. An API boundary, not a choice.
- **Star counts are as-of-fetch, not as-of-cutoff.** GitHub exposes no historical
  count. Only the popularity diagnostic reads them.
- **Absence of merged outsider code is not proof of hostility**, and a good
  project can have a quiet quarter. The three-month label window makes this
  sharper than a longer one would.
- **`Homebrew/homebrew-cask` is a genuine disagreement**, not a bug: Holt calls
  it a registry, the label counts eleven qualifying merges. Casks are Ruby files.
  Neither side was tuned to agree with the other.

---

## Provenance

The benchmark inputs, recorded model calls, pool definitions, and result files
are committed so the published numbers can be reproduced without an API key or
GitHub token. Product development continues independently of this frozen
evaluation boundary.

The evaluation design responds to *The Benchmark Ceiling: Human Judgment,
Evaluation Scarcity, and the Political Economy of AI Capability Measurement*
([arXiv:2607.01254](https://arxiv.org/abs/2607.01254)), which argues that
discriminating signal concentrates in hard-tail items while fixed metrics
degrade under strategic optimisation. L0 is such a metric and L1 is the hard-tail
reconstruction; the aggregate scores tie while the hard cases separate cleanly,
which is the shape that argument predicts.
