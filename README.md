# Holt

[![CI](https://github.com/holt-oss/holt/actions/workflows/ci.yml/badge.svg)](https://github.com/holt-oss/holt/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/holt-cli.svg?color=83a9ff)](https://pypi.org/project/holt-cli/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-69c7a6.svg)](https://github.com/holt-oss/holt/blob/main/pyproject.toml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-83a9ff.svg)](https://github.com/holt-oss/holt/blob/main/LICENSE)

**Find an open-source project that will actually merge your first PR.**

Paste a GitHub repository. Holt reads its recent pull requests and tells you,
in plain English, whether newcomers get replies, get merged, and where their
work lands. The answer is one of **Worth your time**, **Not worth your time**
or **Not enough evidence**, with links to the pull requests behind it.

![Holt answering for pallets/flask, then finding starter issues](https://raw.githubusercontent.com/holt-oss/holt/main/assets/demo.gif)

<!-- HOLT_SITE_URL: the orchestrator replaces this URL once the domain is final. -->
**[Try it in your browser](https://holt.aahil-khan.xyz)** · no install, no
account · [Install the CLI](#2-the-command-line) ·
[Get the browser extension](#3-the-browser-extension)

Holt is read-only. It never opens pull requests, posts comments or contacts
maintainers, on any surface.

## Three ways to use it

### 1. The web app

<!-- HOLT_SITE_URL -->
Open **<https://holt.aahil-khan.xyz>** and paste a repository. Or change one
word in any GitHub link, `github.com` to `holt.aahil-khan.xyz`, and you land on
the report:

```text
https://github.com/pallets/flask
https://holt.aahil-khan.xyz/pallets/flask
```

No repository in mind? **Find a project** asks which languages you read and how
much time you have, then lists welcoming repositories with open starter issues.

<table>
  <tr>
    <td><img src="https://raw.githubusercontent.com/holt-oss/holt/main/assets/web-report-light-desktop.jpg" alt="The report for pallets/flask: Worth your time, with the counts behind it and a first issue to try" width="640"></td>
    <td><img src="https://raw.githubusercontent.com/holt-oss/holt/main/assets/web-find-dark-phone.jpg" alt="Find a project on a phone: pick languages and time, get welcoming repositories" width="200"></td>
  </tr>
</table>

### 2. The command line

The same engine runs on your machine, from PyPI. It needs Python 3.11 or newer;
use whichever installer you have (all three work in PowerShell too):

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
holt start --lang python          # starter issues in repositories that merge newcomers
holt analyze pallets/flask        # is this one worth your time?
holt                              # the interactive terminal interface
```

No AI key is needed. Without one you get the rules-only report: the answer and
the numbers behind it, free. For a written explanation that quotes the threads
it relied on, `holt models` sets up a model; Gemini's free tier is the cheapest
start.

![holt analyze pallets/flask in a terminal: Worth your time, what the evidence shows, where outsider work landed](https://raw.githubusercontent.com/holt-oss/holt/main/assets/cli-analyze.png)

| Command | Purpose |
|---|---|
| `holt analyze <owner/repo>` | Assess one repository. `--days N` for the time you have, `--json` for machine-readable output. |
| `holt start` | Starter issues, across repositories (`--lang`, `--topic`, `--hacktoberfest`) or in one. |
| `holt compare <repo>…` | Several repositories side by side. |
| `holt next <repo> --as <login>` | After your first merge: open issues near the files you already changed. |
| `holt profile`, `holt discover --live` | Say what you want to work on, then search for it. |
| `holt token`, `holt models` | Save a GitHub token; optionally set up a model. |

**The terminal interface.** Bare `holt` opens it: type a repository, watch the
run, open any piece of evidence on GitHub with `o`, and come back to past
assessments. Press `?` on any screen for help.

![The Holt terminal interface showing the assessment for pallets/flask](https://raw.githubusercontent.com/holt-oss/holt/main/assets/tui.png)

[docs/USAGE.md](https://github.com/holt-oss/holt/blob/main/docs/USAGE.md)
walks through the whole workflow and
[docs/COMMANDS.md](https://github.com/holt-oss/holt/blob/main/docs/COMMANDS.md)
lists every flag.

### 3. The browser extension

**Holt for GitHub** adds a small chip next to the repository name on
github.com (**Holt: Worth your time · 15 of 100 newcomer PRs merged**) and
marks the issues Holt would pick first. Clicking the chip opens the full
report. It sends only the `owner/repo` you are looking at, keeps nothing, and
never writes to GitHub.

![The Holt chip next to a repository name on GitHub, and Holt pick marks on the issue list](https://raw.githubusercontent.com/holt-oss/holt/main/extension/screenshots/desktop-light.png)

It is not on the extension stores yet. To try it, build it and load it
unpacked in Chrome, Edge, Brave or Firefox:
[extension/README.md](https://github.com/holt-oss/holt/blob/main/extension/README.md).

## Hacktoberfest

Every October the site has a seasonal page, **[/hacktoberfest](https://holt.aahil-khan.xyz/hacktoberfest)**:
repositories taking part that actually merge newcomers' work, with starter
issues by language, and a few tips so your pull request doesn't get ignored.
From the command line:

```sh
holt start --hacktoberfest --lang python
```

## For maintainers: a README badge

Show newcomers they are welcome. Paste this into your README, with your own
`owner/repo`:

```markdown
[![Holt](https://holt.aahil-khan.xyz/badge/owner/repo.svg)](https://holt.aahil-khan.xyz/owner/repo)
```

The badge shows Holt's current answer for your repository and links to the
report. It updates when the report does; you never have to touch it again.

## How the verdict works

| Answer | Meaning |
|---|---|
| **Worth your time** | Outsiders get replies and land real work here, fast enough for the time you have. |
| **Not worth your time** | The record says a newcomer's week is unlikely to go anywhere here. |
| **Not enough evidence** | Too little outside activity to call it either way. That is an answer, not an error. |

**Rules decide. AI only explains.** The answer comes from fixed rules applied
to counted evidence: who tried, who got merged, how fast the first reply came,
and whether anyone actually reviewed the work. An AI model can add a written
explanation that quotes the threads it relied on, and every claim it makes is
checked against the record before you see it. Unsupported claims are dropped.
The model never chooses the answer.
[docs/DESIGN.md](https://github.com/holt-oss/holt/blob/main/docs/DESIGN.md)
has the argument.

## How well it works, and where it doesn't

Holt was tested on repositories it had never seen, with the outcome hidden
from it. It got **about four in five calls right** (balanced accuracy 0.82). A
single AI prompt over the same repositories' READMEs and metadata got 0.61.

That is evidence, not a guarantee. Know the limits:

- **It is a filter, not an oracle.** One call in five is wrong. Open the
  linked pull requests before you commit a week.
- **It reads the past.** Repository cultures change, and a quiet month can
  look worse than it is.
- **It is about your time, not their quality.** A superb project with a deep
  review queue can still be a poor place for a first pull request.
- **Counts, not conversations.** Without a model, Holt can't tell you what a
  thread said or who was welcoming, only what happened.

[docs/research/EVALUATION.md](https://github.com/holt-oss/holt/blob/main/docs/research/EVALUATION.md)
has the design and the full numbers, and
[docs/research/REPRODUCTION.md](https://github.com/holt-oss/holt/blob/main/docs/research/REPRODUCTION.md)
reproduces them from a clone with no API key, no token and no money.

## The repository

| Path | What |
|---|---|
| `src/holt/` | The engine, the CLI and the terminal interface (`holt-cli` on PyPI) |
| `web/` | The web app |
| `server/` | The HTTP API the web app calls |
| `extension/` | The browser extension |
| `docs/` | Everything else, starting from [docs/README.md](https://github.com/holt-oss/holt/blob/main/docs/README.md) |

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
