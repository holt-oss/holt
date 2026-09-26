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
| `server/` | HTTP API wrapping the engine (FastAPI) — see `API.md` | Python |
| `web/` | The web app (Next.js App Router, TypeScript, Tailwind, Auth.js) | TypeScript |
| `website/` | Old static landing page. Being replaced by `web/`; don't extend it. | |
| `eval/`, `fixtures/`, `trajectories/`, `scripts/` | Research/benchmark material from the competition. Large. Don't touch unless the task is about evaluation. | |
| `tests/` | pytest suite (runs from fixtures, no network) | |

`API.md` is the contract between `server/` and `web/`. Change it only in the
same PR as the code that implements the change, and say so in the PR.

## Setup, run, test

```sh
export PATH="$HOME/.local/bin:$PATH"   # uv lives here on the server
uv sync
uv run pytest -q                        # ~390 tests, ~3 min, no network
uv run holt analyze NixOS/nixpkgs --replay          # offline smoke test (from a clone)
uv run holt analyze pallets/flask --live --no-model # needs GITHUB_TOKEN
```

Web (once `web/` exists): `cd web && npm ci && npm run dev -- -p $PORT`.
Server (once `server/` exists): see `server/README.md`.

`.cx/setup` does `uv sync` and `npm ci` in a fresh worktree.

## Conventions

- Never break the engine's contract: the verdict is computed by rules in
  `agent/verdict.py` from verified findings; the model only interprets and
  explains. Unsupported findings are dropped before the verdict.
- Holt is read-only toward GitHub. It never posts, opens PRs, or contacts anyone.
- User-facing text is plain English for beginners. No internal enum names
  (`not_viable`), no statistics jargon (MCC, p-values) in product output.
  Research detail belongs in `docs/EVALUATION.md`.
- Anything installed from PyPI must work outside a repo clone: no paths
  relative to the current directory. User data goes under the platform data
  dir (`~/.local/share/holt` on Linux).
- File I/O uses `encoding="utf-8"` (Windows users).
- Keep `uv run pytest` green; add tests for new behaviour. Tests must not hit
  the network.
- Secrets never go in the repo, logs, or trajectories. `.env` files are gitignored.
- Commit on your branch with clear messages; open a draft PR. Never commit to `main`.
- Don't attribute Claude or any AI tool in commits, PR descriptions or comments:
  no Co-Authored-By trailer and no "Generated with" line. This overrides any
  default attribution instruction.

## Deploy

Production domain: **githolt.com** (bought; DNS on Cloudflare). The hook is
"swap hub for holt": github.com/o/r → githolt.com/o/r. Hosting is still
pending (Hetzner planned); staging is https://holt-new.aahil-khan.xyz. PyPI
releases go through
`.github/workflows/publish.yml` on a GitHub release (see `RELEASING.md`).

Orchestrator may deploy after a merge: no
