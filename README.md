# Holt

[![CI](https://github.com/holt-oss/holt/actions/workflows/ci.yml/badge.svg)](https://github.com/holt-oss/holt/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-83a9ff.svg)](https://github.com/holt-oss/holt/blob/main/LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-69c7a6.svg)](https://github.com/holt-oss/holt/blob/main/pyproject.toml)

**Find out whether an open-source repository is worth your time before you
spend a weekend on it.**

Holt reads a repository's recent pull requests and answers one question for a
newcomer: do people from outside the project get replies, and does their work
get merged? The answer is one of **Worth your time**, **Not worth your time**,
or **Not enough evidence**, with links to the pull requests behind it.

<!-- HOLT_SITE_URL: the orchestrator replaces this URL once the domain is final. -->
**Try it in your browser: <https://holt.aahil-khan.xyz>**. No install and no
account needed.

<!-- TODO: demo GIF. Record the web app answering for one repository and save it
as assets/demo.gif, then replace this comment with:
![Holt answering for pallets/flask](https://raw.githubusercontent.com/holt-oss/holt/main/assets/demo.gif)
-->

## Three ways to ask

**1. Swap the host in any GitHub link.** Change `github.com` to
`holt.aahil-khan.xyz`:

```text
https://github.com/pallets/flask
https://holt.aahil-khan.xyz/pallets/flask
```

**2. Hacktoberfest.** Looking for repositories that will actually review your
four pull requests? Holt lists starter issues in repositories that merge
newcomers' work. Use the site, or run `holt start --hacktoberfest --lang python`
from the command line.

**3. The browser extension.** It adds a small chip next to the repository name
on GitHub (**Holt: Worth your time · 15 of 100 newcomer PRs merged**), and
marks the issues Holt would pick first. It sends only the `owner/repo` you are
looking at and never writes to GitHub.
[Install and privacy details](https://github.com/holt-oss/holt/blob/main/extension/README.md).

Holt is read-only everywhere. It never opens pull requests, posts comments, or
contacts maintainers.

## What the answer means

| Answer | Meaning |
|---|---|
| **Worth your time** | Outsiders get replies and land real work here, fast enough for the time you have. |
| **Not worth your time** | The record says a newcomer's week is unlikely to go anywhere here. |
| **Not enough evidence** | Too little outside activity to call it either way. That is an answer, not an error. |

The answer comes from fixed rules applied to counted evidence: who tried, who
got merged, how fast the first reply came, and whether anyone actually reviewed
the work. An AI model can add a written explanation that quotes the threads it
relied on, but it never chooses the answer. Treat it as a filter, not an
oracle, and open the linked pull requests before committing a week.

## The command line

The same engine runs on your machine. It needs Python 3.11 or newer; pick
whichever installer you have (all three work in PowerShell too):

```sh
pipx install holt-cli
uv tool install holt-cli
pip install --user holt-cli
```

Give it a GitHub token once. Holt reads only public data, so
[create a token](https://github.com/settings/tokens/new?description=holt) with
every box unticked, then run `holt token` and paste it. If you use the GitHub
CLI, Holt picks up `gh auth token` and you can skip this.

```sh
holt start --lang python          # starter issues in welcoming repositories
holt analyze pallets/flask        # is this one worth your time?
holt                              # the interactive terminal interface
```

No AI key is needed. Without one you get the rules-only report: the answer and
the numbers behind it, free. For the written explanation, `holt models` sets up
a model; Gemini's free tier is the cheapest start.

| Command | Purpose |
|---|---|
| `holt analyze <owner/repo>` | Assess one repository. `--json` for machine-readable output. |
| `holt start` | Starter issues, across repositories (`--lang`, `--topic`, `--hacktoberfest`) or in one. |
| `holt compare <repo>…` | Several repositories side by side. |
| `holt next <repo> --as <login>` | After your first merge: open issues near the files you already changed. |
| `holt profile`, `holt discover --live` | Save what you want to work on, then search for it. |
| `holt token`, `holt models` | Save a GitHub token; optionally set up a model. |

[USAGE.md](https://github.com/holt-oss/holt/blob/main/USAGE.md) walks through
the whole workflow, and
[docs/COMMANDS.md](https://github.com/holt-oss/holt/blob/main/docs/COMMANDS.md)
lists every flag.

![Holt terminal interface](https://raw.githubusercontent.com/holt-oss/holt/main/assets/holt.png)

## How well it works

Holt was tested on repositories it had never seen, with the outcome hidden from
it. It got about four in five calls right (**0.82 balanced accuracy**). A single
AI prompt over the same repositories' READMEs and metadata got 0.61. That is
evidence, not a guarantee: repository cultures change, and quiet periods can
look worse than they are.

- [Evaluation design and limitations](https://github.com/holt-oss/holt/blob/main/docs/EVALUATION.md)
- [Reproduce the published results](https://github.com/holt-oss/holt/blob/main/REPRODUCTION.md)
  (no API key, no token, no money)
- [How the engine decides](https://github.com/holt-oss/holt/blob/main/docs/DESIGN.md)

## Contributing

Holt is small, and one maintainer runs it. First pull requests are welcome.
[CONTRIBUTING.md](https://github.com/holt-oss/holt/blob/main/CONTRIBUTING.md)
starts with a 15-minute path to your first one, and issues labelled
[good first issue](https://github.com/holt-oss/holt/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
are sized for it. Participation is governed by the
[Code of Conduct](https://github.com/holt-oss/holt/blob/main/CODE_OF_CONDUCT.md);
security reports follow
[SECURITY.md](https://github.com/holt-oss/holt/blob/main/SECURITY.md).

> Holt started as the winner of **Most useful real-world workflow** at the
> micro1 Frontier Engineering Challenge.

## License

[Apache License 2.0](https://github.com/holt-oss/holt/blob/main/LICENSE).
