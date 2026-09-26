# Human-time comparison — how to actually run it

The protocol is fixed in [`HUMAN-TIME-PROTOCOL.md`](HUMAN-TIME-PROTOCOL.md) and
was written before any stopwatch started. **Do not read this runbook as licence
to change it.** This file is only the mechanics: what to open, in what order,
what to write down, and where the numbers go afterwards.

Budget: **~50 minutes** end to end. Three repositories at up to 20 minutes each
is the worst case (60), but two of the three will finish early or hit the cap
and stop.

> **Why this exists at all.** The brief's evaluation table has three rows —
> primary outcome, **human time per task**, cost per task. Two of the three are
> already measured and published. This one needs a person with a stopwatch, and
> that person is you.

---

## 0. Before you start the clock

- [ ] **Read the protocol once, fully.** Especially the "Rules for the human
      side" section. If you discover mid-run that you broke a rule, that
      repository's timing is void — restart it rather than reporting it.
- [ ] **Close Holt.** No terminal with `holt` in it, no fixtures open, no
      `trajectories/` tab. The protocol says github.com only, and you have read
      these repositories before; the point is to time *the method*, not to
      pretend you have amnesia.
- [ ] **Have a stopwatch you can start and stop with one key.** Phone timer is
      fine. Not a mental estimate afterwards.
- [ ] **Open a blank file** for notes. You are recording process, not just
      minutes — see §2.
- [ ] **Do the three in the order given below.** The protocol fixed the
      repositories; fixing the order too removes one more degree of freedom.

The three repositories, from the protocol:

| # | Repository | Why it is in the set |
|---|---|---|
| 1 | `runelite/plugin-hub` | a trap — high merge rate, almost no human review |
| 2 | `NixOS/nixpkgs` | genuinely viable, and very large |
| 3 | `stablyai/orca` | small, quiet, ambiguous |

---

## 1. The human side, per repository

**The task, verbatim from the protocol** — read it before each one, do not
paraphrase it from memory:

> Decide whether an outside contributor with one week should attempt this
> repository, and write two sentences citing specific pull requests.

**Done** means a verdict of viable / not viable / insufficient evidence, **plus
at least two citations of specific pull requests** supporting it. A feeling is
not done. Two sentences with no PR numbers in them is not done.

**Procedure**

1. Open `https://github.com/<owner>/<name>` in a fresh tab.
2. **Start the clock the moment the page renders.**
3. Work however you would normally. Nothing is off limits on github.com —
   the PR list, filters, search, `CONTRIBUTING.md`, the insights tab.
4. **Stop the clock when the second sentence is written**, not when you feel
   you know the answer. Writing it down is part of the task for both sides.
5. **At 20:00, stop regardless.** Record `not reached at 20` and move on. This
   is a censored observation and it is a legitimate result — it is in fact the
   most likely outcome for `nixpkgs`, and reporting it honestly is worth more
   than a heroic 34-minute number.

**Do not** look at Holt's answer for a repository before you have timed it. If
you already know Holt's verdict for one of these three from memory, say so in
the notes for that repository — it is a bias against the human side being
independent, and it belongs in the write-up rather than in your head.

---

## 2. What to write down, per repository

Copy this block three times into your notes file and fill it in **as you go**,
not afterwards:

```
repository:
elapsed:                    (mm:ss, or "not reached at 20")
verdict:                    viable / not_viable / insufficient_evidence
the two sentences:

pull requests cited:        (numbers)
PRs actually opened:        (count — all of them, not just the cited ones)
read CONTRIBUTING?          yes / no
checked reply latency?      yes / no — and how
checked whether merges were reviewed?   yes / no
anything you noticed that you think Holt would miss:
did you already know Holt's verdict here?   yes / no
```

The last three lines are the ones that make this more than a stopwatch. The
protocol commits to reporting *what was actually looked at*, and "I never once
checked whether anyone reviewed those merges" is a finding, not an admission.

---

## 3. Holt's side

Run this **after** all three human timings are done, so nothing you see leaks
backwards.

The protocol specifies a **live** run, so the comparison includes crawling:

```sh
export OPENAI_API_KEY=...
export GITHUB_TOKEN=...          # classic token, no scopes needed

for repo in runelite/plugin-hub NixOS/nixpkgs stablyai/orca; do
  echo "=== $repo"
  time PYTHONPATH=. uv run holt analyze "$repo" --live
done
```

Record the **real** time from each `time`, not user or sys.

Expect roughly 40 s and about $0.012 per repository
([`docs/research/REPRODUCTION.md`](../docs/research/REPRODUCTION.md), costs table). If a live run fails on
rate limits, note it and retry — a failed crawl is not a timing.

Also record, separately and labelled as such, the replay path, because that is
what a reader reproducing the work actually pays:

```sh
for repo in runelite/plugin-hub NixOS/nixpkgs stablyai/orca; do
  time PYTHONPATH=. uv run holt analyze "$repo" --replay
done
```

The protocol already states the reference figure for replay across the whole
pool: median 12 ms per repository, 0.9 s for all of it. Your three numbers
should be consistent with that; if they are wildly not, something is wrong with
the run rather than with the figure.

---

## 4. Reporting it

The protocol fixes what gets reported: **per repository, human minutes (or "not
reached at 20"), Holt seconds, and whether the two verdicts agree.** Speed is
worthless if the fast answer is wrong, so disagreements are reported
individually rather than averaged away.

### Where it goes

**a. `eval/HUMAN-TIME-PROTOCOL.md`** — append a `## Result` section at the
bottom of the file that fixed the protocol. Same pattern as
`eval/PREREGISTRATION.md`, which keeps its failed prediction with the outcome
appended: the protocol and its result live in one file so nobody has to trust
that they matched.

**b. `README.md`** — a short block near the Result section. The brief's
evaluation table wants a `Human time per task` row; give it one, with the n=3
caveat attached to the number rather than in a footnote:

```markdown
| Metric | Simple baseline | Holt | Change |
|---|---|---|---|
| Primary outcome (MCC, pool 2, out of sample) | 0.21 | 0.63 | +0.42 |
| Human time per task | <mm:ss>, n=3, self-timed | ~40 s live / 12 ms replay | — |
| Cost per task | <baseline $> | $0.012 live / $0.00 replay | — |
```

Fill the baseline cost from the same run rather than assuming it — the baseline
is one prompt, so it is cheaper per call, and the honest table says so.

**c. `CHANGELOG.md`** — one entry, dated the day you do it, in the established
shape: what you tried, why, the evidence, the decision. It is an experiment like
any other and the changelog is explicitly the record of experiments.

### The three declarations that must travel with the number

These are in the protocol already. They have to appear **wherever the number
appears**, not only in the protocol file:

1. **n = 3 is an illustration, not evidence of a population effect.** Label it
   that way in the README, the changelog and the video if you mention it.
2. **The timer is the tool's author**, who knows what to look for and is
   therefore faster than a real first-time user. This biases *against* Holt,
   which is the safe direction — say so.
3. **If the human beats Holt, or finds something Holt missed, it goes in the
   README exactly as written in the protocol.** That clause was written before
   the timing precisely so it could not be dropped after it.

---

## 5. Failure modes to avoid

| | |
|---|---|
| Timing after the fact from memory | The whole number is then an estimate of your optimism. Use the stopwatch. |
| Pushing past 20 minutes "because I'm nearly there" | Turns a clean censored observation into an unbounded one. Stop at 20. |
| Reporting a mean over three | Report the three. A mean over n=3 with one censored value is not a mean of anything. |
| Quietly dropping a repository where the human won | The protocol forbids this in writing. It is also the most interesting possible outcome. |
| Reporting Holt's replay time as the comparison | Replay is 12 ms because the crawl already happened. The comparison number is the **live** one; replay is reported separately and labelled. |
| Letting the number appear without the n=3 and author-bias caveats | Every other number in this project carries its limits. This one is the weakest and needs them most. |

---

## 6. Definition of done for this task

- [ ] Three human timings recorded, with the §2 block filled for each
- [ ] Three live Holt timings recorded, with `real` times
- [ ] Three replay timings recorded, labelled separately
- [ ] Agreement / disagreement noted per repository, with disagreements written
      out individually
- [ ] `## Result` appended to `HUMAN-TIME-PROTOCOL.md`
- [ ] Metric table row added to `README.md` with all three declarations attached
- [ ] `CHANGELOG.md` entry written, dated
- [ ] `uv run pytest -rs` still green — `tests/test_docs_claims.py` recomputes
      README numbers, so a new table can break the build. That is the guard
      working; fix the number, not the test.
