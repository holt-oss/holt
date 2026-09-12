# Why this is a pipeline and not a prompt

What splitting the work into stages earns, and — in equal detail — what it does
not. The pipeline diagram and the headline numbers are in
[README.md](../README.md); this document is the argument behind them.

---

## What the orchestration buys

Four things follow from splitting this into stages rather than asking one model
one question. Each is stated with the measurement that supports it, and the
section after this one states what the split does **not** buy.

**1. A rejection rule that no single prompt can hold.** Holt rejects a repository
when contributions land *easily* and nobody reviews them — high merge rate, almost
no human review. That is a project where a stranger's pull request is waved
through into something nobody maintains, and it looks identical to a healthy
project on every signal GitHub displays. The rule lives in `verdict.py` as two
constants, it was **pre-registered with numeric predictions before it was run**
(`eval/PREREGISTRATION-2.md`), and it was validated on the second pool, which had
never been used to develop it:

| | before the rule | after |
|---|---|---|
| Specificity, pool 2 (out of sample) | 0.58 | **0.83** |

All three pre-registered predictions held. Specificity is the thing Holt exists
to provide — saying *no* — and before this rule it was a coin flip.

**2. Re-answering the question costs nothing.** The contributor's time budget is a
parameter: `holt analyze <repo> --days 3` and `--days 90` are different questions
with different answers. Because every time-shaped threshold is derived inside
`verdict.py` and the model output is unchanged, **re-running with a different
budget makes zero model calls**. A single prompt has to be re-asked, re-billed,
and may return a different verdict for reasons unrelated to the change.

**3. The model never owns the decision — and this is the one that measurably pays.**
`src/holt/agent/verdict.py` is the only path from findings to a verdict and runs
no model. Across three runs Holt returns identical verdicts on **22 of 22**
repositories; the baseline, which puts the whole decision inside one model call,
on **17 of 22**.

**4. Arithmetic where arithmetic works.** Counting landings and measuring reply
latency are not model problems. *But the arithmetic thresholds never bind on this
pool*: setting `MIN_MERGES` and `MIN_DISTINCT_AUTHORS` to zero leaves all 22
verdicts and the confusion matrix unchanged. They are guardrails that this
sample never tested.

Two further properties, both structural rather than accuracy-improving:

**Verification can only subtract — and on this pool it subtracts nothing.**
Stage D resolves every evidence id a finding cites and drops what does not
resolve. Across three runs and 22 repositories it examined **1,402 findings and
dropped 0**. That is the correct outcome of citations that resolve, not evidence
that the mechanism works; the mechanism is covered by tests
(`tests/test_verify.py`) rather than by the pool. It also checks only that an id
*exists*, not that the evidence supports the claim.

**The holdout is structural for timestamps, procedural for payloads.** Every fact
passes through one `EvidenceProvider` whose base class asserts the cutoff on
every record, and a subclass cannot return a record with a post-cutoff
*timestamp*. Repository metadata is timestamped at repository creation, so its
*payload* — `pushed_at`, `is_archived`, `stargazer_count` — is as of fetch. No
pool repository is archived, so nothing leaked here, but the guarantee is
narrower than "structural" suggests.

**Stage B (`onboarding`) reaches the report and not the verdict**, like Stage C.
Only Stage A's `repo_kind` and the arithmetic signals are consulted by
`verdict.py`.

---

## What the orchestration does not buy

Everything above is what the split earns. This is what it does not, and it is
published because a claim about the first is worth nothing without the second.

**The model stages' measurable contribution to accuracy is tiny, and we can now
say precisely where the accuracy lives.** When this was first measured — before
the rejection rule shipped — one prompt over the *same* signals and the *same*
evidence digest matched the full pipeline exactly (0.42 = 0.42 on pool 2). On
the frozen runs the pipeline leads that same-evidence ablation by a wide margin
(0.63 against 0.32 ±0.07 out of sample), and the difference is **not the model
stages getting smarter — it is the deterministic verdict layer**, where the
pre-registered rubber-stamp rule now lives. A prompt can be handed the same
evidence; it cannot be handed a rule it is structurally unable to override, and
the ablation's specificity (0.47, against the pipeline's 0.83) is what that
costs it.

**Ablating the pipeline, in MCC**, holding the frozen model output fixed and
varying only `verdict.py`:

| Configuration | MCC |
|---|---|
| full pipeline | +0.61 |
| Stage A repository-kind rules disabled | +0.60 |
| arithmetic thresholds set to zero | +0.61 |
| both disabled | +0.60 |

The model stages and kind rules are now worth **+0.01 MCC** over the arithmetic
alone — even the registry catch has migrated into the rubber-stamp rule, which
rejects a registry for the same reason a model would: work waved through
unread. The stages still buy what a rule cannot: the evidence a claim cites,
the prose a person reads, and `repo_kind` for the reports where naming the
category matters.

**That last sentence used to have no number behind it. It does now.** MCC scores
the verdict, and the verdict is a three-valued label that `verdict.py` decides
with arithmetic — so the model stages were being measured only on the one task
they do not do. The deliverable is a written assessment, and no arithmetic has
produced one. Measuring *the report* instead
(`PYTHONPATH=. uv run python eval/evidence_integrity.py`, replay, $0, six frozen
runs):

| | resolve | faithful | checkable statements per report |
|---|---|---|---|
| **Holt** | 100% | 99% | **11.8** |
| same-evidence ablation, one prompt | 100% | no quotes | 3.4 |
| the verdict layer alone | — | — | **0** |

A statement is *checkable* when its cited id resolves and, where words are
attributed to somebody, they said them. Over 1,950 statements Holt's are
checkable 100% of the time; the ablation writes 832 and **273 of them — 33% —
cite nothing a reader could open**. Note the shape of that failure: the ablation
is not careless with the ids it uses, since every reference it makes resolves.
It simply does not make one. A resolution *rate* cannot show that — a method
citing once, correctly, scores 100% — which is why the headline is a count.

So the two axes have two different winners, and both are published: on the
verdict the rule layer supplies the entire lead and the model stages add +0.01;
on the report the ordering reverses and the rule layer scores zero, because
arithmetic does not cite. This measurement should have existed before the +0.01
result was published rather than after it.

**The ablation ships as a mode, and out of sample it costs more than +0.01
suggested.** `holt analyze <repo> --no-model` returns the verdict from the rules
alone: no key, no spend, no model call. It is the +0.01 finding taken to its
conclusion — if the rules decide, the verdict should be obtainable without a
model. Measured against the same ground truth:

| | pool 1 (n=22) | pool 2, out of sample (n=33) |
|---|---|---|
| full pipeline | +0.61 | +0.63 |
| `--no-model` | +0.60 | +0.55 |
| gap | −0.01 | **−0.08** |

**In sample the model stages are worth one point of MCC; out of sample they are
worth eight.** The +0.01 above is a pool 1 number and does not survive the move
to pool 2. Both figures are printed in the mode's own report, so nobody gets the
flattering one alone — and on the report axis the mode writes 0 citable
statements against 11.8. The failure mode where a key is missing is now a
documented mode rather than a crash.

**And Path Finder, which we shipped losing.** Ranking issues by how likely an
outsider is to land a merged fix scores precision@3 of 0.173 against GitHub's
`good first issue` label at 0.187 over 25 repositories — indistinguishable, and
its own pre-registered cut condition. It ships because 13 of those 25
repositories carry no beginner-labelled issue at all, and because **the tool
prints that result in its own output next to the ranking**, not here. Run
`holt analyze NixOS/nixpkgs --replay` and read the "Where to start" section.

---

## Deliberate non-uses

A documented non-use is a judgement, not an omission.

- **No memory or vector store.** Each assessment is independent; there is nothing
  to carry between them that the evidence provider does not already hold.
- **No provider variance in the numbers.** Every benchmark figure was measured
  under one pinned, dated model per stage, and the eval path resolves those ids
  unconditionally — a test proves it ignores any user configuration on disk.
  The *product* does let you choose (`holt models`: other OpenAI models, Claude,
  Ollama, Gemini, any OpenAI-compatible endpoint), and its own output warns that
  committed recordings replay only under the defaults. The line we hold is that
  portability must never move variance into a number being reported.
- **No personal fit or skill matching.** No ground truth exists for "will this
  developer enjoy this", so it cannot enter the holdout, so it cannot contribute
  to a measured claim.
- **Stage C's thread signals are computed but excluded from the verdict.**
  Measuring them showed they are inverted — see [the changelog](../CHANGELOG.md).

---

## Where the code is, and why that split

Counted rather than left for a reader to count, because the largest number here
is the one that looks worst:

| | lines | share of `src/holt` |
|---|---|---|
| `tui/` — the terminal interface | 6,181 | 56% |
| core — `cli`, `model`, `report`, `discover`, baselines | 2,069 | 19% |
| `agent/` — the five stages, signals, verify, verdict | 1,954 | 18% |
| `evidence/` — the provider and its GraphQL client | 851 | 8% |
| **`src/holt` total** | **11,055** | |
| `tests/` | 4,696 | |
| `eval/` — harnesses, labels, baselines, statistics | 2,409 | |

The interface remains severable from the analysis engine: Textual ships in the
default product install because bare `holt` opens the TUI, but it is imported
lazily and non-interface code does not depend on it. The CLI and TUI call the
same pipeline and render the same underlying assessment.
