# Using Holt

You have a week and you want to spend it contributing to open source. Holt tells
you whether a repository is a good place to spend it, and shows you the pull
request threads it decided from.

This guide gets you from installation to a current repository assessment. If
you are reproducing the evaluation or checking benchmark numbers, use
[REPRODUCTION.md](REPRODUCTION.md) instead.

---

## Install

Pick whichever installer you already have. All three work the same on macOS,
Linux and Windows (PowerShell):

```sh
pipx install holt-cli
uv tool install holt-cli
pip install --user holt-cli
```

The `holt` command includes the terminal interface.

## Give Holt a GitHub token

GitHub asks for a token even to read public data. Holt only reads, so the token
needs **no permissions**:

1. [Create a token](https://github.com/settings/tokens/new?description=holt) and
   leave every box unticked.
2. Run `holt token` and paste it. It is saved in your config directory, readable
   only by you, and never printed.

If you already use the GitHub CLI and are logged in (`gh auth login`), Holt uses
`gh auth token` and you can skip both steps. You can also set it per terminal:

```sh
export GITHUB_TOKEN=your_token                # macOS / Linux
```

```powershell
$env:GITHUB_TOKEN = "your_token"              # Windows PowerShell
```

The interactive interface (`holt`) asks for the token the first time you need
one.

## Ask about a repository

```sh
holt analyze pallets/flask
```

About 20 seconds, and free: with no AI model set up, you get the rules-only
report, which is the verdict and the counts behind it. Holt only reads; it
never posts, opens a pull request, or contacts anybody.

Add `--json` for machine-readable output. When you pipe or redirect the report
(`holt analyze pallets/flask > flask.md`) it stays plain Markdown; on a terminal
it is formatted, and every piece of evidence is a clickable link to the pull
request on GitHub.

### Optional: a written explanation

With a model set up, the report adds a plain-English explanation and quotes the
pull request threads it relied on. The verdict itself does not change: it is
computed by rules, and the model only explains. The cheapest start for students
is Gemini's free tier ([get a key](https://aistudio.google.com/apikey)):

```sh
holt models --provider gemini --model gemini-2.5-flash
export GEMINI_API_KEY=your_key                # PowerShell: $env:GEMINI_API_KEY = "your_key"
```

Other providers: `--provider openrouter` (one key for many models, some free;
`OPENROUTER_API_KEY`), `anthropic` (`ANTHROPIC_API_KEY`), `openai`
(`OPENAI_API_KEY`), `ollama` (runs on your computer, no key), or
`openai-compatible` with `--base-url`. `holt models` shows what is set up, and
`--no-model` forces the free rules-only report even when a model is.

## When something goes wrong

Every error is one sentence plus the command that fixes it. The common ones:

| Holt says | Do this |
|---|---|
| needs a GitHub token | `holt token` (see above) |
| GitHub did not accept your token | create a new one and run `holt token` again |
| rate limit was reached | wait a few minutes and re-run the same command |
| could not find owner/name | check the spelling in the repository's URL; private repositories are not supported |
| `GEMINI_API_KEY` (or another key) is not set | set it as shown above, or add `--no-model` |

## Reading the answer

The report opens with one of three headlines:

| | |
|---|---|
| **Worth your time** | outsiders get in here, and there is a route for you |
| **Not worth your time** | the record says a stranger's week goes nowhere here |
| **Not enough evidence to say** | too little outsider activity to call it either way |

The third is a real answer, not a failure. Then:

- **What the evidence shows** — what happened to people who tried before you.
- **What decided it** — the one rule that produced the verdict. The verdict is
  computed, not written by a model, so it will not move if you re-run it.
- **What could not be determined** — what Holt looked for and did not find.
- **Where outsider work landed** — which directories accepted outsider pull
  requests and which never did. Usually the most directly useful section:

  > - **`pkgs/by-name`** — 13 merged of 62 attempted (21%)
  > - **`pkgs/top-level`** — 3 merged of 11 attempted (27%)
  >
  > Outsiders attempted these and none were merged: `pkgs/applications` (6),
  > `pkgs/build-support` (6).

- **Evidence** (with a model) — every claim above with a link to the pull
  request it came from, e.g.
  [pull request #526361](https://github.com/NixOS/nixpkgs/pull/526361). Open it
  and read the thread yourself. Anything Holt could not back this way was
  dropped before you saw it.

## Say how much time you have

Everything time-shaped scales from your actual budget — a project whose median
first reply is four days is a different proposition on a 3-day budget than on a
90-day one:

```sh
holt analyze pallets/flask --days 3
holt analyze pallets/flask --days 90
```

Changing `--days` costs nothing: the verdict is arithmetic, so no model runs.

## Compare a shortlist

Nobody decides about one repository.

```sh
holt compare pallets/flask astral-sh/uv
```

One row each, in the order you asked for — the answer, how many outsiders got in,
how fast the first reply comes, and the rule that decided it. It does not sort
them, because sorting would be a claim it has not measured.

## Find candidates in the first place

Say once what you want to work on, then let Holt source and screen:

```sh
holt profile --lang python --topic cli --days 7
holt discover --live
```

`discover` pulls candidates from GitHub search, screens them cheaply, and only
runs the full assessment on the survivors — so a 25-candidate session costs
cents rather than dollars. Screening reads only the newest threads, so treat its
numbers as a filter and the full report as the answer.

## Find your first issue

If you just want somewhere to start, ask for open issues in repositories that
actually merge newcomers' work:

```sh
holt start --lang python
holt start --lang javascript --topic cli,web --hacktoberfest
holt start pallets/flask
```

Holt searches GitHub for issues labelled for beginners (`good first issue`,
`help wanted`, `easy`, `hacktoberfest` and their variants), checks each
repository's recent pull requests with the free rules, and lists only the ones
worth your time, each with its best open, unassigned issues and the reasons
they were picked. Several topics mean "any of these". It needs a
`GITHUB_TOKEN` (no scopes) and takes about 20 seconds. Add `--json` for the
same data as the web API returns.

## After you have landed something

Once you have merged work in a repository, ask what to pick up next:

```sh
holt next NixOS/nixpkgs --as mweinelt
```

Open issues that name files or directories you have already touched come first,
newest first, then everything else by recency. No model call, no cost. The
ranking prints its own measured performance, confidence interval included, above
every list, so you can weigh it honestly.

## In a terminal interface

```sh
holt
```

Same commands, same evidence, browsable. Press `?` on any screen for the keys;
`o` opens the selected evidence on GitHub, `q` on a report goes back.

If you cloned the Holt repository rather than installing it, repositories that
have committed evidence (such as `pallets/flask`) are answered from that
snapshot; add `--live` for today's data.

---

## What Holt will not do for you

- **It never writes.** No pull requests, no issues, no comments, no messages to
  maintainers. It reads public data.
- **It does not rate maintainers.** A verdict is about fit for *your* week. A
  repository can be excellent and still be a poor place to spend your first one
  — a mature project with a deep review queue, for example.
- **It will not guess.** Where the record is thin it says so, and where two
  sources disagree it drops the field rather than picking a side.
- **It is a filter, not an oracle.** On the repositories we measured it gets
  about four in five calls right in each direction (balanced accuracy 0.80 in
  sample, 0.82 out of sample), which leaves a real fifth it gets wrong. Read the
  evidence section before you commit a week; that is what it is there for.

## More

- [docs/COMMANDS.md](docs/COMMANDS.md) — every command and flag, with real output.
- [REPRODUCTION.md](REPRODUCTION.md) — the evaluation, reproducible from a clean
  clone with no key.
- [docs/EVALUATION.md](docs/EVALUATION.md) — how well it works, and where it does not.
