# Good first issues for launch (drafts)

Twelve small, real issues to open before Hacktoberfest. Each one was checked
against `main` on 2026-09-25. They are drafts for the maintainer to review and
create; nothing here has been posted to GitHub.

Every issue gets the `good first issue` label plus one area label: `area:engine`,
`area:cli`, `area:tui`, `area:extension` or `area:docs`. Each body ends with the
same footer:

> New to Holt? [CONTRIBUTING.md](../../CONTRIBUTING.md#your-first-pr-in-15-minutes)
> gets you from clone to pull request in about 15 minutes. Comment here before
> you start so two people don't pick the same issue.

---

## 1. `holt start --hacktoberfest` misses labels like "Hacktoberfest 2026"

**Labels:** good first issue, area:engine
**Files:** `src/holt/starter.py` (`_HACK`), `tests/test_starter.py`

`label_kinds()` only treats a label as Hacktoberfest when, after normalising,
it is exactly `hacktoberfest` (`_HACK = re.compile(r"^hacktoberfest$")`). Many
projects label their issues `Hacktoberfest 2026`, `hacktoberfest-2026` or
`🎃 hacktoberfest`, and those issues lose their Hacktoberfest point.

`hacktoberfest-accepted` is a pull request label, not an issue label, and must
stay excluded (a test already checks this).

**Done when:** the three variants above count as `hacktoberfest`,
`hacktoberfest-accepted` still does not, and there is a parametrised test for
each case. Run `uv run pytest tests/test_starter.py -q`.

## 2. Recognise "good first task" and "good first feature" labels

**Labels:** good first issue, area:engine
**Files:** `src/holt/starter.py` (`_BEGINNER`), `tests/test_starter.py`

`_BEGINNER` matches `good first issue|bug|pr|contribution` but not
`good first task` or `good first feature`, which some large projects use.
Issues with only those labels are currently treated as unlabelled.

**Done when:** both labels give the `beginner` kind, and
`test_label_variants` in `tests/test_starter.py` has cases for them.

## 3. Add `holt --version`

**Labels:** good first issue, area:cli
**Files:** `src/holt/cli.py` (`main`), a test in `tests/test_beginner_first_run.py`

There is no way to ask which version is installed, and bug reports need it.
Add `parser.add_argument("--version", action="version", ...)` using
`importlib.metadata.version("holt-cli")`, with a fallback when the package
metadata is missing (for example when running from a source tree).

**Done when:** `holt --version` prints `holt 0.2.0` (or whatever is installed),
and a test checks that it exits 0 and prints the word `holt`.

## 4. Show examples in `holt start --help`

**Labels:** good first issue, area:cli
**Files:** `src/holt/cli.py` (the `start` sub-parser)

`holt start --help` lists its flags, but a beginner has to guess how they
combine. Add an `epilog` with three examples, using
`formatter_class=argparse.RawDescriptionHelpFormatter` as the top-level parser
already does:

```text
holt start --lang python
holt start --topic cli,web --hacktoberfest
holt start pallets/flask
```

**Done when:** the examples appear in `holt start --help` and
`tests/test_beginner_first_run.py::test_help_has_no_statistics_jargon` still
passes (add `["start", "--help"]` to its list while you are there).

## 5. Name an example model for each provider in `holt models --help`

**Labels:** good first issue, area:cli
**Files:** `src/holt/cli.py` (the `models` sub-parser)

`--model` says "e.g. claude-opus-5, llama3.2". Someone who has just picked
Gemini or OpenRouter has no idea what to type. Add an epilog with one working
line per common provider, for example:

```text
holt models --provider gemini --model gemini-2.5-flash
holt models --provider openrouter --model <a model id from openrouter.ai/models>
holt models --provider ollama --model llama3.2
```

**Done when:** the examples show in `holt models --help`, and each provider
named there is a key of `model.PROVIDER_PRESETS`.

## 6. utf-8 in `discover.py`, and extend the test that enforces it

**Labels:** good first issue, area:engine
**Files:** `src/holt/discover.py`, `tests/test_library_api.py`

Windows defaults to a legacy code page, so every text read and write in Holt
should say `encoding="utf-8"`. `test_every_file_call_in_the_engine_names_utf8`
enforces this for `agent/`, `evidence/`, `reponame.py` and `model.py` only.
`discover.py` still has `read_text()` and `write_text()` calls without it
(around lines 428 and 518).

**Done when:** `discover.py`, `profile.py`, `starter.py` and `cli.py` are added to
the file list in that test, every offender the test reports is fixed, and
`uv run pytest tests/test_library_api.py tests/test_discover.py -q` passes.

## 7. `holt profile` writes broken TOML if a value contains a quote

**Labels:** good first issue, area:engine
**Files:** `src/holt/profile.py` (`save`), `tests/test_profile.py`

`save()` builds TOML with f-strings: `f'"{v}"'`. A topic or language containing
`"` or `\` produces a file that `tomllib` cannot read back, so the next command
fails. It is unlikely, but it is a crash on user input, and the fix is small:
escape `\` and `"` in a helper, or reject such values with a clear message.

**Done when:** a round-trip test saves a profile with `c"sharp` as a language
and loads it back (or gets a clear error), and `uv run pytest
tests/test_profile.py -q` passes.

## 8. Extension: a last-resort selector for the repository title

**Labels:** good first issue, area:extension
**Files:** `extension/src/chip.ts` (`ANCHORS`), `extension/test/chip.test.ts`

The chip is placed by trying three CSS selectors in `ANCHORS`. When GitHub
changes its layout and none of them match, the chip silently disappears. Add a
fourth, deliberately generic, fallback: the first `<h1>` that contains a link
whose `href` is exactly `/<owner>/<repo>`. Place the chip `after` that link.

**Done when:** a jsdom test builds a page with only that `<h1>` (none of the
existing selectors present) and `findAnchor` returns the link, and the existing
tests still pass: `cd extension && npm ci && npm test && npm run typecheck`.

## 9. Extension README: add the desktop dark-theme screenshot

**Labels:** good first issue, area:extension, area:docs
**Files:** `extension/README.md`, `extension/screenshots/`

The README shows the desktop light theme only. `extension/screenshots/` has
`phone-dark.png` but no `desktop-dark.png`, and the dark theme is what a lot of
GitHub users see. Build the extension (`npm run build`), load it unpacked
(steps are in the README), take a screenshot of a repository page with GitHub
set to dark, and add it under the light one.

**Done when:** `extension/screenshots/desktop-dark.png` exists, is under 300 KB,
and is referenced from the README with alt text.

## 10. docs/COMMANDS.md: document `holt start`

**Labels:** good first issue, area:docs
**Files:** `docs/COMMANDS.md`

`holt start` shipped in 0.2.0 and is in the README and USAGE, but the command
reference has no row for it and no section. Add a row to the table ("starter
issues in repositories that merge newcomers' work", model calls: 0) and a
short section with one example per mode (`--lang`, `--hacktoberfest`, one
repository) and what a result line means. Copy the real output of a run rather
than inventing it.

**Done when:** `holt start` appears in the table and has a section; every
command in it runs as written.

## 11. TUI: hide `ctrl+t mode` when there is nothing to switch to

**Labels:** good first issue, area:tui
**Files:** `src/holt/tui/screens/home.py`, `tests/test_tui_screens.py`

In an install from PyPI there are no recordings, so home's `ctrl+t` can only say
"Holt reads GitHub live in this install; there is no other mode." It is still
advertised in the footer. Textual's `check_action` can hide a binding: return
`False` for `toggle_mode` when `session.recordings_available()` is false.

**Done when:** the footer omits `^t mode` when recordings are unavailable and
still shows it in a clone. Add a test that monkeypatches
`recordings_available` to `False` and checks the footer text. Run
`uv run pytest tests/test_tui_screens.py -q -k mode`.

## 12. USAGE.md: explain why new pull requests are not counted as ignored

**Labels:** good first issue, area:docs
**Files:** `USAGE.md` ("Reading the answer")

Since 0.2.0, a pull request opened in the last 48 hours with no reply is not
counted as ignored, so a repository is not punished for a PR opened this
morning. Reports say "N are too new to have had a reply", but USAGE.md never
explains it, so a reader has to guess what that means for the answer. Add two
or three plain sentences under "Reading the answer". The rule is
`awaiting_reply` in `src/holt/agent/signals.py`; the report sentence is in
`src/holt/agent/pipeline.py`.

**Done when:** USAGE.md explains the 48-hour rule in plain English, with no
internal names, and says it applies to live runs.
