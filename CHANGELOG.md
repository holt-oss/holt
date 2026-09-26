# Changelog

All notable changes to Holt are documented here. Holt follows semantic
versioning once releases are published.

## 0.2.0 — unreleased

The release that makes `pip install holt-cli` useful on its own, for
Hacktoberfest.

### Added

- `holt start`: open starter issues in repositories that actually merge
  newcomers' work, found by language, topic or `--hacktoberfest`, or listed for
  one repository. Each issue says why it was picked. (#5)
- `holt token` saves a GitHub token readable only by you. Holt also finds a
  token in `GITHUB_TOKEN` or through `gh auth token`. (#8)
- `--json` output for `holt analyze` and `holt compare`. (#8)
- OpenRouter as a named model provider. (#8)
- Terminal interface: a first-run prompt for the GitHub token, `?` for help on
  any screen, and `o` to open evidence on GitHub. (#8)
- Typed GitHub errors (not found, rate limited, bad token, GitHub down) that
  callers can act on. (#7)

### Changed

- Without an AI model set up, every command gives the free rules-only report
  instead of failing. The terminal interface uses the provider chosen with
  `holt models`. (#8)
- Commands read GitHub live when there is no committed evidence for the
  repository, which is always the case for a PyPI install. (#8)
- User data lives in the platform's data and config directories
  (`~/.local/share/holt`, `~/.config/holt`, and the macOS and Windows
  equivalents), never in the current directory. (#8)
- Errors are one plain-English sentence with the command that fixes it, and
  never a traceback. Reports link every piece of evidence to its pull request,
  render as formatted text on a terminal, and use "Worth your time" instead of
  internal names. (#8)
- The rules that decide a verdict are explained in plain English. (#7)
- The README presents the web app, the command line and the browser
  extension as equals. Research and reproduction guides moved under
  `docs/research/`, the usage and release guides under `docs/`, with
  `docs/README.md` as the index.
- A model call records a trajectory only when `HOLT_RECORD_TRAJECTORIES=1`. (#7)

### Fixed

- Pull requests opened in the last 48 hours no longer count as ignored on live
  runs. (#7)
- GitHub timeouts, server errors and short rate limits are retried with
  backoff instead of failing the run. (#7)
- Repository text shown to a model is fenced as data, so a README cannot give
  it instructions. (#7)
- Pasted GitHub URLs (with `/tree/...`, `.git`, `?tab=...`) are understood, and
  anything that is not a GitHub repository gets a sentence saying what to type
  instead. (#7)

## 0.1.0 — 2026-09-13

### Added

- Evidence-backed assessments for GitHub repositories.
- Deterministic verdicts over verified findings.
- Live GitHub analysis and model-free analysis.
- Repository comparison, contributor profiles, candidate discovery, and
  follow-up issue ranking.
- Interactive terminal interface with inspectable evidence.
- Configurable OpenAI, Anthropic, Gemini, Ollama, and OpenAI-compatible model
  providers.
- Replayable evaluation fixtures and a temporal-holdout benchmark.
- Apache-2.0 licensing, contributor documentation, issue templates, security
  policy, and project governance.
- Distribution on PyPI as `holt-cli`, installable with
  `uv tool install holt-cli`, with the terminal interface included in the
  default install.
