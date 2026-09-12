# Contributing to Holt

Thank you for helping Holt make open-source contribution choices less like
guesswork. Bug reports, documentation improvements, new evidence providers,
interface work, evaluation checks, and carefully scoped features are welcome.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before participating.
For usage questions, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities using
the private process in [SECURITY.md](SECURITY.md), not a public issue.

## Before you start

- Search existing issues and pull requests before opening a duplicate.
- For a substantial feature or a change to the verdict rules, open a feature
  request first. The evidence model and evaluation design are part of the
  product contract, so an implementation may be sound and still not belong in
  Holt.
- Small bug fixes, tests, and documentation corrections can go straight to a
  pull request.
- Never include API keys, GitHub tokens, private repository data, or unredacted
  personal information in an issue, fixture, recording, or pull request.

## Development setup

Holt requires Python 3.11 or newer. The repository pins its working Python
version and dependencies through [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/holt-oss/holt.git
cd holt
uv sync --extra tui
uv run pytest -rs
```

The optional TUI dependency is included above because the complete test suite
must run without skips. A plain `uv sync` remains a supported user path and has
its own CI job.

To exercise the two no-key commands shown to users:

```sh
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay
PYTHONPATH=. uv run python eval/harness.py --replay --run-tag run1
```

## Project invariants

These rules are load-bearing rather than stylistic:

- Holt is read-only. It does not write to GitHub, open pull requests, or contact
  maintainers.
- Every fact a model stage sees passes through `EvidenceProvider`.
- Every user-visible factual claim carries a source line or an evidence id that
  resolves to a real record.
- Verification may remove unsupported claims; it must not invent replacements.
- The model describes evidence but never owns the verdict. Verdict changes
  belong in the deterministic rule layer and need evaluation evidence.
- The temporal holdout boundary is enforced in code. Label-side data must never
  enter the agent path.
- Replayed and synthetic results identify themselves in their own output.
- A skipped test is not a passing test. Use `pytest -rs` and report skips.

Read [docs/DESIGN.md](docs/DESIGN.md) before changing the agent pipeline and
[docs/EVALUATION.md](docs/EVALUATION.md) before changing the benchmark, labels,
sampling, or headline metrics.

## Making a change

1. Fork the repository and branch from `main`.
2. Keep the change focused. Avoid unrelated cleanup in the same pull request.
3. Add or update tests for behavior changes.
4. Update user documentation when commands, output, or guarantees change.
5. Run `uv run pytest -rs` with the TUI extra installed.
6. Open a pull request using the repository template and explain the user-facing
   behavior, evidence, and limitations.

Do not edit frozen evaluation pools after observing results. New experiments
must record their design and outcome when they happen, including unsuccessful
experiments. Do not rewrite historical challenge documents to make a later
result appear pre-registered.

## Fixtures and recordings

Fixtures are public GitHub evidence, but public does not mean context-free.
Collect only what the evaluation or product needs, preserve source identity for
verification, and run the repository's redaction tooling before committing new
captures:

```sh
PYTHONPATH=. uv run python scripts/redact_fixtures.py --help
```

Never hand-edit a recording to make an evaluation pass. Re-record it through
the documented harness and state the model, prompt, cutoff, and run tag.

## Assisted contributions

Tool-assisted contributions are welcome. The contributor remains responsible
for understanding the change, checking every generated claim, running the
tests, and responding to review. Do not add automated attribution footers to
commit messages or pull-request descriptions.

## Licensing

Unless you explicitly state otherwise, a contribution intentionally submitted
for inclusion in Holt is provided under the Apache License, Version 2.0, as
described in section 5 of the license. You must have the right to submit the
work and must preserve required third-party attribution.
