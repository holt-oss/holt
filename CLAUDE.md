# Holt

Holt tells a would-be open-source contributor whether a GitHub repository is
worth their time. It reads recent PR history (do outsiders get replies? get
merged? where does their work land?) and computes a deterministic verdict:
**Worth your time / Not worth your time / Not enough evidence**. A model can
add a written, cited explanation; it never chooses the verdict.

It started as a competition CLI/TUI (micro1 Frontier Engineering Challenge,
"most useful real-world workflow"). It is now being relaunched as an
open-source product whose **main surface is a web app**, with the CLI/TUI
secondary. Launch target: **Hacktoberfest, 1 October 2026**. Audience:
beginners (college students first). Every change should be judged by
"does this get more people to a useful answer faster?"

## Layout

| Path | What | Owner language |
|---|---|---|
| `src/holt/` | The engine + CLI + TUI (Python package `holt-cli` on PyPI) | Python 3.11+, uv |
| `src/holt/agent/` | Signals, model stages, verification, verdict rules | |
| `src/holt/evidence/` | GitHub GraphQL provider, fixtures, redaction | |
| `src/holt/tui/` | The terminal interface (Textual) | |
| `server/` | HTTP API wrapping the engine (FastAPI, Postgres) — see `API.md` and `server/README.md` | Python |
| `web/` | The web app (Next.js App Router, TypeScript, Tailwind, Auth.js) — `web/README.md` | TypeScript |
| `extension/` | Browser extension: a Holt chip on github.com, talks to the web app's public API — `extension/README.md` | TypeScript |
| `e2e/` | Playwright smoke tests against a deployed Holt (staging by default) — `e2e/README.md` | TypeScript |
| `deploy/` | Dockerfiles and the staging preview stack — `deploy/README.md` | |
| `website/` | Legacy static landing page. Still serves the live site until `web/` launches; don't extend it. | |
| `docs/` | All documentation; `docs/README.md` is the index. `docs/research/` holds the evaluation and reproduction guides. | |
| `eval/`, `fixtures/`, `trajectories/`, `scripts/` | Research/benchmark material from the competition. Large. Don't touch unless the task is about evaluation. | |
| `tests/` | pytest suite (runs from fixtures, no network) | |

`API.md` is the contract between `server/` and `web/`. Change it only in the
same PR as the code that implements the change, and say so in the PR.

## Setup, run, test

```sh
export PATH="$HOME/.local/bin:$PATH"   # uv lives here on the server
uv sync
uv run pytest -q                        # ~675 tests, ~3 min, no network
uv run holt analyze NixOS/nixpkgs --replay          # offline smoke test (from a clone)
uv run holt analyze pallets/flask --live --no-model # needs GITHUB_TOKEN
```

Web: `cd web && npm ci && npm run dev -- -p $PORT` (see `web/README.md`).
Server: see `server/README.md`. Extension: `cd extension && npm ci && npm test`.

`.cx/setup` does `uv sync` and `npm ci` in a fresh worktree.

## Conventions

- Never break the engine's contract: the verdict is computed by rules in
  `agent/verdict.py` from verified findings; the model only interprets and
  explains. Unsupported findings are dropped before the verdict.
- Holt is read-only toward GitHub. It never posts, opens PRs, or contacts anyone.
- User-facing text is plain English for beginners. No internal enum names
  (`not_viable`), no statistics jargon (MCC, p-values) in product output.
  Research detail belongs in `docs/research/EVALUATION.md`.
- Anything installed from PyPI must work outside a repo clone: no paths
  relative to the current directory. User data goes under the platform data
  dir (`~/.local/share/holt` on Linux).
- File I/O uses `encoding="utf-8"` (Windows users).
- Keep `uv run pytest` green; add tests for new behaviour. Tests must not hit
  the network.
- Secrets never go in the repo, logs, or trajectories. `.env` files are gitignored.
- Commit on your branch with clear messages; open a draft PR. Never commit to `main`.

## Deploy

Not decided yet (hosting to be chosen; domains available: operationally.systems,
aahil-khan.xyz, plus a new one to be bought). PyPI releases go through
`.github/workflows/publish.yml` on a GitHub release (see `docs/RELEASING.md`).

Orchestrator may deploy after a merge: no
