# The commands, and what they tell you

Every command below runs from committed evidence with **no API key, no GitHub
token and no spend**. Setup is two lines — see
[REPRODUCTION.md](../REPRODUCTION.md):

```sh
uv sync
PYTHONPATH=. uv run holt analyze NixOS/nixpkgs --replay
```

| Command | What it does | Model calls |
|---|---|---|
| `holt analyze <repo>` | the full assessment for one repository | 5 stages |
| `holt analyze <repo> --baseline` | the baseline arm: one prompt over README + metadata | 1 |
| `holt analyze <repo> --no-model` | the verdict from the rules alone | 0 |
| `holt compare <repo>…` | a shortlist side by side | 5 per repo |
| `holt discover` | source candidates, screen them free, analyse survivors | survivors only |
| `holt next <repo> --as <login>` | rank open issues for someone who has landed work | 0 |
| `holt profile` | say once what you want to work on; `discover` reads it | 0 |
| `holt models` | choose a provider for the *product* (never for a reported number) | 0 |
| `holt tui` | open the terminal interface | as above |

Flags worth knowing on `analyze`: `--days N` (how many days you actually have —
everything time-shaped scales from it, and re-running with a different budget
makes **zero** model calls), `--replay` (recorded model output), `--live` (read
GitHub now), `--as-of YYYY-MM-DD`, `--show-verification` (print what Stage D
dropped and why), `--entry-points` (the prototype issue ranking, off by default
because it does not beat GitHub's `good first issue` label).

---

## What the report tells you that GitHub does not

**Where outsider work actually landed.** Every pull request Holt reads carries its
file list. That list decided whether a diff counted as substantive and was then
thrown away; now it is counted. For `NixOS/nixpkgs`:

> - **`pkgs/by-name`** — 13 merged of 62 attempted (21%)
> - **`pkgs/top-level`** — 3 merged of 11 attempted (27%)
>
> Outsiders attempted these and none were merged: `maintainers/maintainer-list.nix`
> (11), `pkgs/applications` (6), `pkgs/build-support` (6), `doc/release-notes` (2).

In a tree of that size, that is where a stranger's week has a chance and where it
does not. GitHub does not show it, `CONTRIBUTING` does not say it, and no amount
of star-counting implies it. **It ranks nothing and predicts nothing** — after five
capabilities cut for losing to a cheap comparator, a section that makes no claim
is a deliberate choice. An attempt counts once per pull request rather than once
per file; only outsiders count, decided per thread in time order; and a directory
is named as "never landed" only when at least two people tried.

## A shortlist, not one repository

Nobody is deciding about a single project.

```
$ holt compare runelite/plugin-hub NixOS/nixpkgs is-a-dev/register stablyai/orca --replay

| repository          | verdict    | outsiders in | first reply | why
| runelite/plugin-hub | not_viable | 70/101       | 4.2h        | repo_kind=registry: merged work here is…
| NixOS/nixpkgs       | viable     | 15/100       | 0.8h        | 15 first-time merges by 15 distinct people…
| is-a-dev/register   | not_viable | 35/191       | 12.3h       | repo_kind=registry: merged work here is…
| stablyai/orca       | viable     | 4/7          | 0.3h        | 4 first-time merges by 4 distinct people…
```

The `why` column is **the rule that fired**, not a summary of the prose, so the
comparison is on the deterministic part. Rows come out in the order you asked for;
it sorts nothing, because sorting is a claim.

`runelite/plugin-hub` is the row that makes the case: 70 of 101 outsiders merged,
replies in 4.2 hours — the best-looking project on the list — and it is rejected,
with the reason in the same row.

## If you have no shortlist yet

`holt discover` builds one from a stated profile — languages, topics, what you
want to contribute, how many days you actually have. Ask once with
`holt profile`, or pass flags. Candidates come from GitHub repository search;
Holt claims the *screening*, not the sourcing or the ordering, and the screening
is free: `verdict.py` needs exactly one model-derived input, so every rejection
rule runs as arithmetic at $0.00.

```
$ holt discover        # replays the recorded demo session; no token, no key

Screened 25 candidates … Rejected 9:
- 3 nobody outside has landed work in
- 2 outsider attempts went unanswered
- 2 work merged without review (the rubber-stamp rule)
- 2 replies too slow for a 7-day budget

| repository    | verdict               | outsiders in | first reply |
| tqdm/tqdm     | insufficient_evidence | 26/179       | 1128.2h     |
| fastapi/typer | viable                | 7/48         | 14.9h       |
| beetbox/beets | viable                | 33/87        | 9.1h        |
|   ↳ tests: outsider work has merged in `test` (26 merged)
```

Screening reads only the newest page of threads, so its numbers are noisier than
the benchmark's — the recorded session shows the disclosure earning its keep:
`tqdm/tqdm` survived shallow screening and flipped to insufficient at full
depth, where the median first reply turned out to be 1,128 hours. Model spend
for the whole session: $0.08, all of it on the five survivors.

## Once you have landed work somewhere

`holt next <repo> --as <your-login>` ranks the open issues by one deterministic
rule: issues naming a file or directory you have already touched come first,
newest first, then the rest by recency. No model call. The rule ships because it
is the best of five methods we measured — hit@10 0.234 against 0.211 for a
weighted eight-feature scorer that was cut for losing to it, 0.188 for recency,
0.172 for chance — and the output prints that measurement, including the 95%
interval [−0.003, +0.132] that spans zero, with every ranking. Each row says
which path tokens overlapped, or that none did.
