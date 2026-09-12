# Holt

[![CI](https://github.com/holt-oss/holt/actions/workflows/ci.yml/badge.svg)](https://github.com/holt-oss/holt/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-83a9ff.svg)](https://github.com/holt-oss/holt/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-69c7a6.svg)](https://github.com/holt-oss/holt/blob/main/pyproject.toml)

**Choose an open-source repository that is worth your time.**

Holt reads recent GitHub contribution history and shows what happens when
outside contributors try to help: whether they receive a response, whether
substantive work gets reviewed and merged, and where newcomer contributions
actually land. It turns that evidence into a verdict you can inspect before
committing days or weeks to a project.

![Holt terminal interface](https://raw.githubusercontent.com/holt-oss/holt/main/assets/holt.png)

Holt is read-only. It never opens pull requests, posts comments, or contacts
maintainers. Every factual claim in a full report links back to the pull request,
review, or comment that supports it.

> Winner of **Most useful real-world workflow** at the micro1 Frontier
> Engineering Challenge. Holt is now maintained as an independent open-source
> product by [`holt-oss`](https://github.com/holt-oss).

## Install

Holt is pre-1.0. You need [`uv`](https://docs.astral.sh/uv/) and Python 3.11 or
newer.

```sh
uv tool install holt-cli
```

Create a classic GitHub token with no scopes and expose it to Holt:

```sh
export GITHUB_TOKEN=your_token
```

Start with the rules-only report. It calls no model and needs no model API key:

```sh
holt analyze pallets/flask --live --no-model
```

For a written report with cited findings and quotations, configure a supported
model provider and run the full analysis:

```sh
export OPENAI_API_KEY=your_key
holt analyze pallets/flask --live
```

Run `holt models` to inspect or change the provider. OpenAI, Anthropic, Gemini,
Ollama, and OpenAI-compatible endpoints are supported.

## Use the terminal interface

Run Holt without a subcommand to open the interactive terminal interface:

```sh
holt
```

From there you can assess a repository, revisit past reports, inspect the
evidence behind a claim, compare candidates, and configure model providers.

## What you get

A repository assessment answers five practical questions:

- Do first-time contributors get meaningful work merged?
- How quickly does someone usually respond?
- Are pull requests reviewed by people or accepted mechanically?
- Which parts of the codebase have accepted outsider work?
- What specific evidence supports the verdict?

The headline is one of:

| Verdict | Meaning |
|---|---|
| **Worth your time** | There is evidence that outsiders can land useful work. |
| **Not worth your time** | The observed contribution path is a poor fit for the time you have. |
| **Not enough evidence** | Holt cannot support either conclusion from the available history. |

Treat the verdict as a filter, not an oracle. Open the cited evidence before
making a significant commitment.

## Commands

| Command | Purpose |
|---|---|
| `holt analyze <owner/repo> --live` | Assess one repository using current GitHub data. |
| `holt compare <repo>… --live` | Compare repositories side by side. |
| `holt profile` | Save the languages, topics, contribution type, and time budget you want. |
| `holt discover --live` | Find and screen repositories for that profile. |
| `holt next <repo> --as <login> --live` | Rank open issues after you have contributed to a project. |
| `holt models` | Inspect or change the model provider. |
| `holt tui` | Open the interactive terminal interface. |

See [USAGE.md](https://github.com/holt-oss/holt/blob/main/USAGE.md) for the
complete workflow and
[docs/COMMANDS.md](https://github.com/holt-oss/holt/blob/main/docs/COMMANDS.md)
for command details.

## How it works

Holt separates evidence collection, interpretation, verification, and the final
decision:

```text
GitHub history
    ↓
contribution signals + cited findings
    ↓
evidence verification
    ↓
deterministic verdict
    ↓
written explanation
```

The model may interpret threads and explain the result, but it does not choose
the verdict. Unsupported findings are removed before the decision is computed.
The same verified inputs therefore produce the same verdict.

The architecture and its boundaries are documented in
[docs/DESIGN.md](https://github.com/holt-oss/holt/blob/main/docs/DESIGN.md).

## Evaluation and limitations

Holt has been measured on two temporally held-out repository pools. On the
out-of-sample pool it reached 0.82 balanced accuracy and 0.63 Matthews
correlation, compared with 0.61 and 0.21 for a single prompt over repository
metadata and documentation. The committed fixtures and recordings make those
results reproducible.

The evaluation is evidence, not a guarantee. Repository cultures change, quiet
periods can look worse than they are, and no benchmark captures whether a
particular issue matches your skills. Holt is designed to show its work so you
can disagree with it intelligently.

- [Evaluation design and limitations](https://github.com/holt-oss/holt/blob/main/docs/EVALUATION.md)
- [Reproduce the published results](https://github.com/holt-oss/holt/blob/main/REPRODUCTION.md)
- [Recorded example analyses](https://github.com/holt-oss/holt/blob/main/trajectories/README.md)

## Contributing

Holt welcomes focused improvements to evidence providers, verdict rules,
terminal UX, documentation, evaluation, and platform support.

```sh
git clone https://github.com/holt-oss/holt.git
cd holt
uv sync
uv run pytest -rs
```

Read [CONTRIBUTING.md](https://github.com/holt-oss/holt/blob/main/CONTRIBUTING.md)
before opening a pull request. Community participation is governed by the
[Code of Conduct](https://github.com/holt-oss/holt/blob/main/CODE_OF_CONDUCT.md),
and security reports follow
[SECURITY.md](https://github.com/holt-oss/holt/blob/main/SECURITY.md).

## License

Holt is licensed under the
[Apache License 2.0](https://github.com/holt-oss/holt/blob/main/LICENSE).
