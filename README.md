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

Holt is pre-1.0 and needs Python 3.11 or newer. Pick whichever installer you
already have:

```sh
pipx install holt-cli          # recommended if you have pipx
uv tool install holt-cli       # if you use uv
pip install --user holt-cli    # plain pip
```

The same commands work in PowerShell on Windows.

## Quickstart

**1. Give Holt a GitHub token.** Holt only reads public data, so the token needs
no permissions. [Create one here](https://github.com/settings/tokens/new?description=holt)
(leave every box unticked), then:

```sh
holt token
```

It asks for the token and saves it privately on your computer. Already use the
GitHub CLI? Holt picks up `gh auth token` automatically, so you can skip this.

**2. Ask about a repository.**

```sh
holt analyze pallets/flask
```

That is the whole thing: a verdict and the numbers behind it, free, with no AI
key. Or run `holt` with no arguments for the interactive interface.

<details>
<summary>Prefer an environment variable for the token?</summary>

```sh
export GITHUB_TOKEN=your_token             # macOS / Linux
```

```powershell
$env:GITHUB_TOKEN = "your_token"           # Windows PowerShell
```

</details>

### Optional: add a written explanation

With a model set up, the report also explains itself in plain English and quotes
the pull request threads it relied on. The model never chooses the verdict.
Gemini's free tier is the cheapest way to start:

```sh
holt models --provider gemini --model gemini-2.5-flash
export GEMINI_API_KEY=your_key             # PowerShell: $env:GEMINI_API_KEY = "your_key"
holt analyze pallets/flask
```

Get a Gemini key at <https://aistudio.google.com/apikey>. Holt also supports
OpenRouter (`--provider openrouter`, key in `OPENROUTER_API_KEY`), Anthropic,
OpenAI, Ollama (local, no key), and any OpenAI-compatible endpoint. Without a
model, every command gives the rules-only report.

## Use the terminal interface

Run Holt without a subcommand to open the interactive terminal interface:

```sh
holt
```

Type a repository and press enter. The first time, it asks for your GitHub
token. From there you can revisit past reports, open the evidence behind a claim
on GitHub (`o`), and set up a model (`ctrl+l`). Press `?` on any screen for help.

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
| `holt analyze <owner/repo>` | Assess one repository using current GitHub data. Add `--json` for machine-readable output. |
| `holt compare <repo>…` | Compare repositories side by side. |
| `holt start --lang python` | Find open starter issues in repositories that merge newcomers' work. |
| `holt profile` | Save the languages, topics, contribution type, and time budget you want. |
| `holt discover --live` | Find and screen repositories for that profile. |
| `holt next <repo> --as <login>` | Rank open issues after you have contributed to a project. |
| `holt token` | Save a GitHub token (asked for, never echoed). |
| `holt models` | Optional: set up a model for the written explanation. |
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
