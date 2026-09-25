# Contributing to Holt

Thank you for helping Holt make open-source contribution choices less like
guesswork. Holt has one maintainer, so small, focused pull requests are the
fastest to get reviewed and merged.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before participating.
For usage questions, see [SUPPORT.md](SUPPORT.md). Report vulnerabilities using
the private process in [SECURITY.md](SECURITY.md), not a public issue.

## Your first PR in 15 minutes

**1. Pick something small.** Issues labelled
[good first issue](https://github.com/holt-oss/holt/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
say which files they touch and how to check your change. Comment on the issue
so nobody else starts the same one.

**2. Find your way around.** The repository in six lines:

| Path | What it is | Language |
|---|---|---|
| `src/holt/` | The engine, the CLI and the terminal interface (`holt-cli` on PyPI) | Python |
| `server/` | The HTTP API the web app calls ([API.md](API.md) is the contract) | Python, FastAPI |
| `web/` | The web app | TypeScript, Next.js |
| `extension/` | The browser extension that puts a chip on GitHub pages | TypeScript |
| `eval/`, `fixtures/` | The benchmark and its recorded evidence (large; only for evaluation work) | Python, JSON |
| `docs/`, `*.md` | Documentation | Markdown |

**3. Get the code.** A docs or extension change does not need the ~315 MB of
benchmark evidence, so you can skip it:

```sh
git clone --filter=blob:none --sparse https://github.com/holt-oss/holt.git
cd holt
git sparse-checkout set --no-cone '/*' '!/fixtures/'
```

Leave out the last line if you are working on the engine, whose tests read
`fixtures/`. [REPRODUCTION.md](REPRODUCTION.md#not-reproducing-the-benchmark-skip-the-evidence) has the
details.

**4. Run only the part you touch.**

| You changed | Run |
|---|---|
| Docs only | Nothing to run. Preview the Markdown on GitHub. |
| Engine, CLI, TUI | `uv sync`, then `uv run pytest tests/test_<area>.py -q` |
| Server | `uv sync`, then `uv run pytest server/tests -q` |
| Web app | `cd web && npm ci && npm run dev` |
| Extension | `cd extension && npm ci && npm test && npm run typecheck` |

[`uv`](https://docs.astral.sh/uv/) installs the right Python for you. The full
Python suite (`uv run pytest -rs`) takes a few minutes and CI runs it on every
pull request, so you don't need to run it locally for a small change.

**5. Open the pull request.** Say what changed for a user and how you checked
it. Link the issue with `Fixes #123`.

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

## Full development setup

Holt requires Python 3.11 or newer. The repository pins its working Python
version and dependencies through [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/holt-oss/holt.git
cd holt
uv sync
uv run pytest -rs
```

The default development environment includes the terminal interface and runs
the complete test suite without skips.

To exercise the two no-key commands shown to users:

```sh
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay
PYTHONPATH=. uv run python eval/harness.py --replay --run-tag run1
```

## Making a change

1. Fork the repository and branch from `main`.
2. Keep the change focused. Avoid unrelated cleanup in the same pull request.
3. Add or update tests for behavior changes.
4. Update user documentation when commands, output, or guarantees change.
5. Run `uv run pytest -rs`.
6. Open a pull request using the repository template and explain the user-facing
   behavior, evidence, and limitations.

Do not edit frozen evaluation pools after observing results. New experiments
must record their design and outcome when they happen, including unsuccessful
experiments. Do not rewrite historical evaluation records to make a later
result appear pre-registered.

Maintainer releases follow [RELEASING.md](RELEASING.md).

## Changing the verdict rules

Most contributions never touch this. If yours changes what verdict Holt gives,
open a feature request first: the evidence model and the evaluation design are
part of the product contract, so an implementation can be sound and still not
belong in Holt. Read [docs/DESIGN.md](docs/DESIGN.md) before changing the
engine and [docs/EVALUATION.md](docs/EVALUATION.md) before changing the
benchmark, labels, sampling, or headline metrics.

These invariants are load-bearing rather than stylistic:

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
