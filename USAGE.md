# Using Holt

You have a week and you want to spend it contributing to open source. Holt tells
you whether a repository is a good place to spend it, and shows you the pull
request threads it decided from.

This page is the product. If you are reproducing the evaluation or checking the
numbers, you want [REPRODUCTION.md](REPRODUCTION.md) instead.

---

## Install

```sh
git clone https://github.com/holt-oss/holt.git
cd holt
uv sync
```

That is all. [`uv`](https://docs.astral.sh/uv/) installs the right Python for
you: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Ask about a repository

Try it with no keys and no setup — a few well-known repositories ship with their
evidence already recorded:

```sh
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay
```

For a repository you actually care about, read GitHub directly:

```sh
export GITHUB_TOKEN=...      # a classic token with NO scopes is enough
export OPENAI_API_KEY=...
PYTHONPATH=. uv run holt analyze pallets/flask --live
```

About 40 seconds and about a cent. Holt only reads; it never posts, opens a pull
request, or contacts anybody.

**No OpenAI key?** Drop it and add `--no-model`:

```sh
export GITHUB_TOKEN=...
PYTHONPATH=. uv run holt analyze pallets/flask --live --no-model
```

You still get the verdict and the counts behind it. You lose the prose and the
quoted threads — the report says so itself. `holt models` points Holt at another
provider, including a local one, if you would rather not use OpenAI at all.

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

- **Evidence** — every claim above with the thread id it came from, e.g.
  `pr:NixOS/nixpkgs#526361:opened`. Paste it after `github.com/` and read the
  thread yourself. Anything Holt could not back this way was dropped before you
  saw it.

Watch that dropping happen with `--show-verification`.

## Say how much time you have

Everything time-shaped scales from your actual budget — a project whose median
first reply is four days is a different proposition on a 3-day budget than on a
90-day one:

```sh
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay --days 3
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay --days 90
```

Changing `--days` costs nothing: the verdict is arithmetic, so no model runs.

## Compare a shortlist

Nobody decides about one repository.

```sh
PYTHONPATH=. uv run holt compare runelite/plugin-hub NixOS/nixpkgs --replay
```

One row each, in the order you asked for — verdict, how many outsiders got in,
how fast the first reply comes, and the rule that decided it. It does not sort
them, because sorting would be a claim it has not measured.

## Find candidates in the first place

Say once what you want to work on, then let Holt source and screen:

```sh
PYTHONPATH=. uv run holt profile --lang python --topic cli --days 7
PYTHONPATH=. uv run holt discover --live
```

`discover` pulls candidates from GitHub search, screens them cheaply, and only
runs the full assessment on the survivors — so a 25-candidate session costs
cents rather than dollars. Screening reads only the newest threads, so treat its
numbers as a filter and the full report as the answer. Without `--live` it
replays a recorded demo session, which is a good way to see the shape of it
first.

## After you have landed something

Once you have merged work in a repository, ask what to pick up next:

```sh
PYTHONPATH=. uv run holt next NixOS/nixpkgs --as mweinelt
```

Open issues that name files or directories you have already touched come first,
newest first, then everything else by recency. No model call, no cost. The
ranking prints its own measured performance, confidence interval included, above
every list, so you can weigh it honestly.

## In a terminal interface

```sh
uv sync --extra tui
PYTHONPATH=. uv run holt tui
```

Same commands, same evidence, browsable.

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
