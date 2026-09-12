> **Outcome: measured, shipped with the measurement attached.** Built and
> evaluated on both pools. It did **not** beat its comparators: combined
> precision@3 of 0.173 against the `good first issue` label's 0.187 over 25
> repositories (paired difference −0.013, 95% CI [−0.133, +0.120], sign test
> p = 0.51).
>
> Cut condition 2 was met, and the coverage query below is why it ships anyway:
> **13 of those 25 repositories carry no beginner-labelled issue at all**, and 17
> of 25 carry fewer than three — so on most of the pool the `good first issue`
> comparator reorders nothing and *is* recency under another name. The ranking is
> printed with its own losing number beside it, in the tool's output rather than
> only here.
>
> The document below is unedited, so the design can be read against what it
> produced.

---

# Path Finder — ground truth first, implementation second

Written 2026-08-30, **before any implementation**, because the rule this project
keeps is that we do not ship a capability we cannot measure.

---

## The gap this addresses

Holt currently answers `VIABLE / NOT_VIABLE / INSUFFICIENT_EVIDENCE`. That is a
verdict, not an action. A developer who reads "viable" still has to open the
repository and work out where to start — which is most of the work the tool was
supposed to remove.

The product answer is: *given that this repository is worth your time, here is a
specific issue you could realistically land, and here is what happened to people
who tried similar things.*

## The task, stated so it can be scored

> Given a repository judged viable, rank the issues that were **open at the
> cutoff** by how likely an outsider is to land a merged pull request resolving
> them.

Ranking, not classification. A developer looks at two or three candidates, so
the metric is precision at small k.

## The ground truth

Computable, and on the same temporal discipline as everything else:

> An issue is a **realised entry point** if, after the cutoff, it was closed by a
> merged pull request whose author was **not** in the repository's pre-cutoff
> committer set.

Every term is mechanical. `closedByPullRequestsReferences` gives the linking,
`mergedAt` gives the merge, and the outsider test reuses the definition already
used by L1 — computed from pre-cutoff data, so it cannot leak.

## Feasibility — measured, not assumed

Counted live against 8 viable pool repositories, first 50 issues each:

| | Count |
|---|---|
| issues open at the cutoff | 188 |
| later closed | 112 |
| **later closed by a merged pull request** | **42** |

A **22% base rate** before the outsider filter, which will roughly halve it.
Extrapolated across the ~35 viable repositories in both pools with full paging,
this yields on the order of 800–1,500 scorable issues. That is enough to support
precision at k=3 with a meaningful comparison against chance.

Per-repository variance is severe and is the main risk: `nixpkgs` has 18 realised
entry points in 42 sampled issues, `Homebrew/homebrew-cask` has 0 in 3. The
metric must therefore be **computed per repository and averaged**, never pooled
across repositories, or nixpkgs alone decides the result.

## What it is measured against

Three comparators, all on the same issue set:

| Comparator | Why |
|---|---|
| **base rate** | the fraction of issues open at T that were realised. Any ranking must beat picking at random. |
| **recency** | newest issues first. The obvious heuristic, and free. |
| **`good first issue` label** | what the ecosystem already offers. If the label beats us, the feature has no reason to exist. |

That third comparator is the one that matters. Holt's whole premise is that
existing GitHub signals do not tell you what you need — the same claim has to be
tested here, and it may lose.

## Exclusions, declared in advance

- Repositories with fewer than 10 issues open at the cutoff are excluded; a
  precision@3 over 4 issues is noise.
- **Repositories with zero realised entry points are excluded from the mean.**
  Precision at k is identically zero there for *every* method, including the
  comparators, so they cannot distinguish anything — they would only dilute all
  methods equally toward zero. Excluding empty queries is standard in ranking
  evaluation, and it is declared here **before any method has been scored**. The
  count of excluded repositories is reported alongside the result, because the
  exclusion is also a fact about how rare these opportunities are: on pool 1,
  6 of 14 viable repositories had none.
- Repositories Holt judges NOT_VIABLE are excluded. Path Finder only runs where
  the prior question was answered yes, and a confident route into
  `is-a-dev/register` is worse than no route at all.

## Known weaknesses of this design

**The counterfactual problem.** An issue nobody resolved might still have been a
fine entry point — nobody tried. This is the same asymmetry as the viability
label, and it is why the metric is **precision, not recall**: of the issues we
recommend, how many were actually realised. We never claim the unrecommended ones
were bad.

**Issue bodies can be edited after the cutoff.** GitHub's API returns the current
body, not the body as of T. Unlike pull request threads, which we reconstruct from
timestamped events, an edited issue body is a genuine small leak. Mitigation:
record `updatedAt` and report what fraction of scored issues were edited after
the cutoff, so the size of the leak is visible rather than assumed away.

**A second evaluation on a smaller sample.** This adds a metric that is weaker
than the viability one. If it is reported alongside without that caveat it dilutes
rather than strengthens.

## Cost and effort

| | |
|---|---|
| Issue crawling, both windows, ~35 repos | free (GitHub rate limit, not money) |
| One ranking call per repository per run | ~$0.01 × 35 ≈ **$0.35 per run** |
| Implementation | ~4h: issue evidence type, linking, label computation, ranking stage, eval |

## The gate — when to cut this

Cut it, without regret, if any of these hold:

1. Full crawling shows fewer than ~300 scorable issues after the outsider filter.
2. The `good first issue` comparator matches Holt's precision. The feature then
   has no argument for existing.
3. The final frozen benchmark is not yet run when ~8 hours remain. A measured
   viability result with no Path Finder beats an unmeasured Path Finder bolted
   into a product release whose main claim has not been re-verified.

**Decision:** the design is sound and the base rate supports it. Whether to build
it depends on the remaining budget and on the freeze happening first.
