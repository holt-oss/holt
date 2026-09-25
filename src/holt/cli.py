"""holt — is this repository worth your time?"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from holt import baseline, credentials, model, paths, reponame
from holt.agent import entry, pipeline
from holt.evidence.fixtures import FixtureProvider
from holt.evidence.provider import EvidenceProvider
from holt.agent.verdict import headline
from holt.report import EntryPoint
from holt.types import T_CUTOFF, Window

ISSUES_URL = "https://github.com/holt-oss/holt/issues"

# Issue evidence is captured and replayed separately from pull-request evidence,
# so that adding the ranker did not invalidate a single recorded verdict
# trajectory. The evaluation of the verdict and the evaluation of the ranking stay
# independent of each other.
ISSUE_ROOT = "fixtures/issues"
PATHFINDER_TRAJECTORIES = "pathfinder"


def normalise(repo: str) -> str:
    """Best-effort `owner/repo`, never raising.

    Kept lenient for the TUI, which calls it on stored and half-typed names.
    Commands use `reponame.normalise`, which rejects what is not a GitHub
    repository with a message that says what to type instead.
    """
    try:
        return reponame.normalise(repo)
    except ValueError:
        repo = repo.strip().rstrip("/")
        if "github.com" in repo:
            repo = repo.split("github.com", 1)[1].lstrip("/:")
        return "/".join(repo.split("/")[:2])


def as_of_from(args: argparse.Namespace) -> datetime:
    """How recent the evidence may be.

    **T = 2026-06-01 is an evaluation device, not a product setting.** It exists so
    labels can be computed from records the agent was never shown. A person asking
    about a repository today wants everything up to today, and cutting them off in
    June throws away the three most relevant months -- badly enough that an active
    repository created in July reports "no outsider activity" and looks dead.

    So: fixtures answer as of T, because that is what they contain; live runs
    answer as of now, unless `--as-of` says otherwise. `--as-of 2026-06-01` on a
    live run reproduces the benchmark's view.
    """
    if getattr(args, "as_of", None):
        return datetime.fromisoformat(args.as_of).replace(tzinfo=UTC)
    return datetime.now(UTC) if args.live else T_CUTOFF


def make_issue_provider(live: bool, as_of: datetime) -> EvidenceProvider:
    if not live:
        return FixtureProvider(Window.PRE_T, root=Path(ISSUE_ROOT))
    from holt.evidence.github_graphql import LiveGitHubIssueProvider

    return LiveGitHubIssueProvider(Window.PRE_T, cutoff=as_of)


def make_provider(live: bool, as_of: datetime) -> EvidenceProvider:
    if not live:
        return FixtureProvider(Window.PRE_T)
    from holt.evidence.github_graphql import LiveGitHubProvider

    return LiveGitHubProvider(Window.PRE_T, cutoff=as_of)


class UserError(Exception):
    """Something the reader can fix. Printed as-is, with no traceback."""


def has_fixture(repo: str) -> bool:
    """Whether committed evidence for this repository is on disk.

    Only ever true in a clone of the Holt repository. An install from PyPI has
    none, so every command there reads GitHub live.
    """
    try:
        return FixtureProvider(Window.PRE_T).path_for(repo).is_file()
    except OSError:
        return False


def choose_live(args: argparse.Namespace, repos: list[str]) -> None:
    """Read GitHub live unless every repository asked about has committed
    evidence. Without this, `holt analyze pallets/flask` from a PyPI install
    failed looking for a file that only exists in a clone."""
    if not args.live and not getattr(args, "replay", False):
        args.live = not all(has_fixture(r) for r in repos)
    if args.live:
        require_github_token()


def require_github_token() -> None:
    if not credentials.ensure_token():
        raise UserError(credentials.missing_token_message())


def recording_path(repo: str, kind: str = "verdict") -> Path:
    """Where a live model run on this machine records its calls, when
    recording is on (`HOLT_RECORD_TRAJECTORIES=1`; off by default). Never the
    committed recordings, and never the current directory."""
    stamp = _STARTED
    return paths.runs_dir() / repo.replace("/", "__") / stamp / f"{kind}.jsonl"


_STARTED = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
_hinted = False


def model_client(repo: str, args: argparse.Namespace, quiet: bool = False):
    """The model for a run, or None for the rules-only report.

    Rules-only is what you get whenever no model is set up. The verdict never
    needed one; a beginner with no API key still gets a real answer, and a
    one-paragraph hint on how to add the written explanation.
    """
    global _hinted
    if getattr(args, "no_model", False):
        return None
    if getattr(args, "replay", False):
        return model.build(repo, replay=True)
    if not model.model_ready():
        if not (_hinted or quiet):
            print(model.model_setup_hint() + "\n", file=sys.stderr)
            _hinted = True
        return None
    return model.live_client(recording_path(repo))


def stats_from(signals) -> dict | None:
    """The counts behind a verdict, named as `API.md` names them."""
    if signals is None:
        return None
    return {
        "outsider_attempts": signals.outsider_threads,
        "outsider_merged": signals.outsider_merged,
        "distinct_outsiders": signals.distinct_outsider_authors,
        "first_time_merged_authors": signals.distinct_merged_authors,
        "no_reply": signals.outsider_ignored,
        "median_first_response_hours": signals.median_first_response_hours,
        "bot_share": signals.bot_share,
    }


def emit_markdown(text: str) -> None:
    """Rendered on a terminal, plain Markdown when piped or redirected.

    `holt analyze x > report.md` still writes a file you can paste into an
    issue; only a person looking at a terminal gets the formatting. `rich` is
    already installed with the interface, but a missing one is not an error.
    """
    if sys.stdout.isatty() and not os.environ.get("HOLT_PLAIN"):
        try:
            from rich.console import Console
            from rich.markdown import Markdown

            Console().print(Markdown(text, hyperlinks=True))
            return
        except ImportError:
            pass
    print(text)


def emit_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def add_entry_points(assessment, repo: str, provider, args) -> None:
    """Attach a ranked reading order, or say nothing at all.

    Silent on failure by design: a missing issue fixture means we cannot rank,
    and a tool that invents an entry point when it has no issues is worse than
    one that omits the section.
    """
    try:
        issues = make_issue_provider(args.live, as_of_from(args)).fetch(repo)
    except FileNotFoundError:
        return
    # Recorded under its own directory, so the ranker's calls and the verdict's
    # calls replay independently and adding one never invalidated the other.
    if args.replay:
        path = model.TRAJECTORY_DIR / PATHFINDER_TRAJECTORIES / (repo.replace("/", "__") + ".jsonl")
        client = model.ReplayModel(path)
    elif model.model_ready():
        client = model.live_client(recording_path(repo, PATHFINDER_TRAJECTORIES))
    else:
        # The ranking is written by a model. With none set up there is nothing
        # to rank with, and the report is complete without it.
        return
    ranked = entry.rank(repo, list(issues), list(provider.fetch(repo)), client)
    assessment.entry_points = [
        EntryPoint(r["evidence_id"], r["first_step"], r.get("why", "")) for r in ranked
    ]
    # The ranker runs on its own client, and `--stage pathfinder=` can point it
    # at a different model. The footer names every model that wrote something on
    # the page, so it has to hear about this one too.
    for name in client.usage.models:
        if name not in assessment.models:
            assessment.models.append(name)


def cmd_analyze(args: argparse.Namespace) -> int:
    repo = reponame.normalise(args.repo)
    choose_live(args, [repo])
    as_of = as_of_from(args)
    provider = make_provider(args.live, as_of)
    if args.live and not args.json:
        print(f"Reading recent pull requests for {repo} from GitHub…", file=sys.stderr)
    # Not built at all without a model: rules-only needs no key and spends
    # nothing, and constructing a live client would demand one.
    client = model_client(repo, args, quiet=args.json)
    if args.baseline and client is None:
        raise UserError("--baseline asks a model for its answer, so it needs one "
                        "set up. See: holt models")

    trace = None
    if args.baseline:
        assessment = baseline.assess(repo, provider, client)
    else:
        assessment, trace = pipeline.analyze(
            repo, provider, None if args.no_model else client,
            contributor_days=args.days, as_of=as_of,
        )
        if args.show_verification:
            print(
                f"<!-- findings before verification: {trace.before_verification}, "
                f"after: {trace.after_verification}, dropped: {len(trace.dropped)}, "
                f"unquoted: {len(trace.invented)} -->",
                file=sys.stderr,
            )
            for d in trace.dropped:
                print(f"<!-- DROPPED {d.field}={d.value!r} cited {list(d.evidence_ids)} -->",
                      file=sys.stderr)
            for d in trace.invented:
                print(f"<!-- UNQUOTED {d.field}={d.value!r} cited {list(d.evidence_ids)}: "
                      "the thread resolves and does not say this -->", file=sys.stderr)
    if not args.baseline and args.entry_points:
        add_entry_points(assessment, repo, provider, args)
    if args.json:
        emit_json(assessment.to_dict(
            stats=stats_from(getattr(trace, "signals", None)),
            mode="ai" if client is not None else "rules",
        ))
    else:
        emit_markdown(assessment.render())
    if not args.replay and client is not None:
        u = client.usage
        print(
            f"<!-- {u.input_tokens} in / {u.output_tokens} out tokens, "
            f"${u.cost_usd:.4f} -->",
            file=sys.stderr,
        )
    return 0


# A shortlist is the real situation. Nobody has one repository they are deciding
# about; they have five tabs open. This orders nothing -- the rows come out in the
# order they were asked for -- because ordering is a claim, and five capabilities
# have been cut here for making one that a cheap signal already made.
COMPARE_HEADERS = ("repository", "answer", "outsiders in", "first reply", "why")


def cmd_compare(args: argparse.Namespace) -> int:
    repos = [reponame.normalise(raw) for raw in args.repos]
    choose_live(args, repos)
    as_of = as_of_from(args)
    provider = make_provider(args.live, as_of)
    rows = []
    reports = []
    for repo in repos:
        if args.live and not args.json:
            print(f"Reading {repo}…", file=sys.stderr)
        client = model_client(repo, args, quiet=args.json)
        assessment, trace = pipeline.analyze(
            repo, provider, client, contributor_days=args.days, as_of=as_of
        )
        signals = trace.signals
        landed = f"{signals.outsider_merged}/{signals.outsider_threads}"
        reply = (f"{signals.median_first_response_hours:.1f}h"
                 if signals.median_first_response_hours is not None else "never")
        # The rule that fired, not a summary of the prose. If nothing fired the
        # verdict came from the default path and saying so is more honest than
        # inventing a reason.
        why = assessment.rules[0] if assessment.rules else "no rule fired"
        why = why if len(why) <= 58 else why[:57].rstrip(" ,;:") + "…"
        rows.append((repo, headline(assessment.verdict), landed, reply, why))
        reports.append(assessment.to_dict(
            stats=stats_from(signals), mode="ai" if client is not None else "rules"))

    if args.json:
        emit_json({"days": args.days, "reports": reports})
        return 0

    widths = [max(len(str(r[i])) for r in (*rows, COMPARE_HEADERS)) for i in range(5)]
    widths[4] = min(widths[4], 60)

    def line(cells) -> str:
        return "| " + " | ".join(
            str(c)[:widths[i]].ljust(widths[i]) for i, c in enumerate(cells)
        ) + " |"

    out = [f"# Comparison — for a contributor with {args.days} "
           f"day{'' if args.days == 1 else 's'}\n",
           line(COMPARE_HEADERS),
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]  # matches "| cell " padding
    out += [line(row) for row in rows]
    out += ["\n`outsiders in` counts pull requests merged from people with no prior "
            "merge, over the number who tried.",
            "Run `holt analyze <repo>` for the evidence behind any row."]
    emit_markdown("\n".join(out))
    # Declared `-> int` and every sibling returns one; falling off the end made
    # `compare` the one command whose exit status was an accident.
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    """Open the terminal interface.

    Textual is imported here and nowhere else. It ships in the default product
    install because bare `holt` opens this interface, while the lazy boundary
    keeps non-interface commands independent from UI startup.

    The interface runs the same `pipeline.analyze` the CLI runs. It is a way of
    watching a stage, never the only way of running one.
    """
    try:
        from holt.tui import env
        from holt.tui.app import run
        from holt.tui.session import RunOptions, missing_credentials
    except ImportError as exc:
        print(
            f"The terminal interface dependency is unavailable ({exc}).\n"
            "Reinstall Holt with: uv tool install --force holt-cli",
            file=sys.stderr,
        )
        return 2

    # Names only. A value read from `.env` is never printed.
    from_env_file = env.load()
    # Found now, so the interface only asks for a token when there truly is none.
    credentials.ensure_token()

    # The interface honours the user's chosen model, the same deliberate opt-in
    # `main` makes for the command line. The library still never reads it, so
    # the eval harness and the committed recordings stay on the pinned ids.
    model.enable_user_models_config()
    if from_env_file:
        print(f"Read {', '.join(from_env_file)} from .env", file=sys.stderr)

    # No repository: open on the list of what has already been assessed. This is
    # the ordinary way in, which is why it is what bare `holt` does.
    repo = getattr(args, "repo", None)
    if not repo:
        run(None)
        return 0

    options = RunOptions(
        repo=repo,
        replay=args.replay,
        live=args.live or (not args.replay and not has_fixture(repo)),
        entry_points=args.entry_points,
        contributor_days=args.days,
    )

    # Checked before the screen is taken over, so a missing credential reads as
    # a sentence in the terminal rather than a traceback behind a full-screen
    # app. A missing GitHub token is not on this list: the interface asks for
    # one itself.
    missing = missing_credentials(options)
    if missing:
        for item in missing:
            print(item, file=sys.stderr)
        return 2

    run(options)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Where this contributor might look next. One deterministic rule, no model."""
    from holt.agent import progression
    from holt.agent.signals import build_threads
    from holt.issues import open_at_cutoff

    repo = reponame.normalise(args.repo)
    choose_live(args, [repo])
    as_of = as_of_from(args)
    records = make_provider(args.live, as_of).fetch(repo)
    contributor = progression.history_for(args.as_login, build_threads(records))
    if not contributor.merged_count:
        print(f"{args.as_login} has no merged pull request in {repo} that Holt "
              "can see, so there is nothing to match open issues against. "
              f"Start with: holt analyze {repo}",
              file=sys.stderr)
        return 1
    try:
        issues = make_issue_provider(args.live, as_of).fetch(repo)
    except FileNotFoundError:
        print(f"Holt could not read the open issues of {repo}, so there is "
              "nothing to rank.", file=sys.stderr)
        return 1
    candidates = open_at_cutoff(issues)
    if not candidates:
        print(f"{repo} had no open issues on {as_of.date().isoformat()}, so "
              "there is nothing to rank.", file=sys.stderr)
        return 1
    ranked = progression.path_overlap_rank(contributor.files, candidates)
    print(progression.render_next(repo, contributor, ranked, candidates, top=args.top))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    from holt import profile as profile_mod

    stored = profile_mod.load()
    if any(getattr(args, f, None) for f in ("lang", "topic", "contribution", "days_flag")):
        args.days = args.days_flag
        updated = profile_mod.from_args(args, stored)
    else:
        updated = profile_mod.ask(stored)
    path = profile_mod.save(updated)
    print(f"Saved to {path}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    from holt import discover, profile as profile_mod

    args.days = args.days_flag
    if args.live or args.record:
        stated = profile_mod.from_args(args, profile_mod.load())
        if not (stated.languages or stated.topics):
            print("Tell Holt what to look for first, for example:\n"
                  "  holt discover --live --lang python\n"
                  "or save your interests once with: holt profile", file=sys.stderr)
            return 2
        require_github_token()
        out = discover.run_live(
            stated, limit=args.limit, max_analyze=args.max_analyze,
            record=args.record, progress=lambda s: print(s, file=sys.stderr),
        )
    else:
        # The free path: replay a recorded session. The default session ships
        # in the repository so the demo needs no token and no key.
        try:
            out = discover.run_replay(args.session, days=args.days_flag,
                                      max_analyze=args.max_analyze)
        except FileNotFoundError:
            print("Search GitHub for repositories that match what you want to "
                  "work on:\n  holt discover --live --lang python", file=sys.stderr)
            return 2
    print(out)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Where to start: starter issues in repositories that merge newcomers' work."""
    import json
    import os

    from holt import starter

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("`holt start` searches GitHub live and needs a GITHUB_TOKEN. "
              "Create one at https://github.com/settings/tokens (no scopes needed) "
              "and export it.", file=sys.stderr)
        return 2
    progress = (lambda s: None) if args.json else (lambda s: print(s, file=sys.stderr))
    try:
        if args.repo:
            from holt import reponame

            repo = reponame.normalise(args.repo)
            transport = starter.GitHub(token=token)
            as_of = datetime.now(UTC)
            landing = []
            try:
                # Where outsider work landed boosts issues that name it. Only a
                # bonus: if the screen fails, the issues still list.
                landing = starter.rules_screen(transport, as_of, args.days)(repo).landing
            except starter.RateLimited:
                raise
            except Exception as err:
                progress(f"Could not read pull-request history ({err}); listing issues only")
            issues = starter.starter_issues(repo, token, limit=args.limit, as_of=as_of,
                                            landing=landing,
                                            hacktoberfest=args.hacktoberfest,
                                            transport=transport)
            print(json.dumps({"repo": repo, "issues": [i.as_dict() for i in issues]},
                             indent=1) if args.json else starter.render_repo(repo, issues))
            return 0
        languages = [x for x in (args.lang or "").split(",") if x.strip()]
        topics = [x for x in (args.topic or "").split(",") if x.strip()]
        if not (languages or topics or args.hacktoberfest):
            print("Say what you want to work on: --lang python, --topic cli, "
                  "or --hacktoberfest. Or name a repository: holt start owner/repo.",
                  file=sys.stderr)
            return 2
        results = starter.find(languages, topics, args.hacktoberfest, token,
                               limit=args.limit, progress=progress, days=args.days)
    except starter.RateLimited as err:
        print(f"holt: {err}", file=sys.stderr)
        return 1
    except (starter.RepoNotFound, ValueError) as err:
        print(f"holt: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"results": [r.as_dict() for r in results]}, indent=1))
    else:
        describe = ", ".join(languages + topics + (["Hacktoberfest"] if args.hacktoberfest else []))
        print(starter.render_find(results, describe))
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Show or change which model answers, per provider. The default stays the
    pinned OpenAI ids the benchmark was measured on."""
    if args.reset:
        path = model.models_config_path()
        if path.exists():
            path.unlink()
        model.enable_user_models_config(model.ModelsConfig())
        print("Model configuration reset to the defaults.")
        return 0

    if args.provider or args.model_id or args.base_url or args.api_key_env or args.stage:
        current = model.load_models_config()
        if args.provider:
            if args.provider not in model.PROVIDER_PRESETS:
                print(f"Unknown provider {args.provider!r}. One of: "
                      f"{', '.join(sorted(model.PROVIDER_PRESETS))}", file=sys.stderr)
                return 2
            current.provider = args.provider
        if args.model_id:
            current.model = args.model_id
        if args.base_url:
            current.base_url = args.base_url
        if args.api_key_env:
            current.api_key_env = args.api_key_env
        for spec in args.stage or []:
            stage, _, model_id = spec.partition("=")
            if not model_id or stage not in model.STAGE_MODELS:
                print(f"--stage wants <stage>=<model> with stage one of: "
                      f"{', '.join(sorted(model.STAGE_MODELS))}", file=sys.stderr)
                return 2
            current.stages[stage] = model_id
        path = model.save_models_config(current)
        model.enable_user_models_config(current)
        print(f"Saved to {path}\n")

    config = model.active_config()
    print(f"provider     {config.provider}")
    if config.resolved_base_url():
        print(f"base_url     {config.resolved_base_url()}")
    print(f"api key env  {config.resolved_key_env()}"
          f"{'' if model.model_ready(config) else '  (not set: reports are rules-only)'}")
    print()
    print(f"{'stage':<18}{'model':<28}{'pricing':<24}")
    for stage in model.STAGE_MODELS:
        resolved = model.model_for(stage)
        # The rate itself, not the word "known". Someone reading this is about
        # to spend money and the number is the thing they came for.
        rates, exact = model.resolve_price(resolved)
        if rates is None:
            priced = "unknown ($0 recorded)"
        else:
            priced = f"${rates[0]:g} / ${rates[1]:g} per M"
            if not exact:
                # Priced through a floating alias, which can be repointed.
                priced += " (alias)"
        print(f"{stage:<18}{resolved:<28}{priced:<24}")
    if not config.is_default():
        print(
            "\nNot the defaults. Committed trajectories and benchmark results "
            "were recorded under the default models; `--replay` of those "
            "recordings will fail loudly under this configuration rather than "
            "serve another model's answers. `holt models --reset` restores the "
            "defaults. Recordings you make now will replay under this "
            "configuration."
        )
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    """Save a GitHub token, asked for without echoing it."""
    if args.show:
        source = credentials.ensure_token()
        print(f"Using the GitHub token from {source}." if source
              else credentials.missing_token_message())
        return 0 if source else 2
    import getpass

    print("Holt reads public pull requests, so the token needs no permissions.\n"
          f"Create one (leave every box unticked): {credentials.TOKEN_URL}\n")
    try:
        token = getpass.getpass("Paste the token (it will not be shown): ")
    except (EOFError, KeyboardInterrupt):
        print("\nNothing saved.", file=sys.stderr)
        return 1
    try:
        path = credentials.save_token(token)
    except ValueError as exc:
        raise UserError(f"{exc} Nothing was saved. Try again: holt token") from exc
    print(f"Saved to {path} (readable only by you).\n"
          "Try it: holt analyze pallets/flask")
    return 0


def friendly_error(exc: BaseException, repo: str | None = None) -> str:
    """What went wrong, in a sentence, with the command that fixes it.

    Matched on type where the type says enough and on the message where only
    the message does. The engine's typed GitHub errors are matched by class name
    so this keeps working as they are added. Anything unrecognised is still one
    readable line plus where to report it — never a traceback.
    """
    import httpx

    target = normalise(repo) if isinstance(repo, str) and repo else "owner/name"
    text = str(exc)
    name = type(exc).__name__
    lowered = text.lower()
    retry = f"holt analyze {target}"

    from holt.evidence import errors as gh

    if isinstance(exc, UserError):
        return text
    if isinstance(exc, gh.RepoNotFound):
        return (f"Holt could not find {target} on GitHub. Check the spelling "
                "(it is owner/name, as in the repository's URL). Private "
                "repositories are not supported.")
    if isinstance(exc, gh.AuthError):
        return ("GitHub did not accept your token (it may have expired or "
                f"been revoked). Create a new one at {credentials.TOKEN_URL}\n"
                "then save it with: holt token")
    if isinstance(exc, gh.RateLimited):
        return f"{text} Then run: {retry}"
    if isinstance(exc, gh.UpstreamError):
        return f"{text} Run: {retry}"
    if isinstance(exc, ValueError) and reponame.EXAMPLE in text:
        return text  # `reponame.normalise` already says what to type instead
    if "GITHUB_TOKEN" in text and "not set" in text:
        return credentials.missing_token_message()
    if name in {"RepoNotFound", "NotFound"} or "not found or not public" in lowered:
        return (f"Holt could not find {target} on GitHub. Check the spelling "
                "(it is owner/name, as in the repository's URL). Private "
                "repositories are not supported.")
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            return ("GitHub did not accept your token (it may have expired or "
                    f"been revoked). Create a new one at {credentials.TOKEN_URL}\n"
                    "then save it with: holt token")
        if code in (403, 429):
            return ("GitHub's rate limit was reached for your token. Wait a few "
                    f"minutes, then run: {retry}")
        if code >= 500:
            return f"GitHub is having trouble right now ({code}). Try again shortly: {retry}"
        return f"GitHub answered with an error ({code}). Try again: {retry}"
    if name in {"RateLimited", "RateLimitError"} or "rate limit" in lowered \
            or "rate_limited" in lowered:
        if "openai" in type(exc).__module__ or "anthropic" in type(exc).__module__:
            return ("The AI model's rate limit was reached. Wait a minute, or get "
                    f"the free rules-only report now: {retry} --no-model")
        return ("GitHub's rate limit was reached for your token. Wait a few "
                f"minutes, then run: {retry}")
    if name in {"AuthError", "BadCredentials"} or "bad credentials" in lowered:
        return ("GitHub did not accept your token. Create a new one at "
                f"{credentials.TOKEN_URL}\nthen save it with: holt token")
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return ("Holt could not reach GitHub. Check your internet connection, "
                f"then try again: {retry}")
    if isinstance(exc, httpx.HTTPError):
        return f"Talking to GitHub failed ({text or name}). Try again: {retry}"
    module = type(exc).__module__
    if module.startswith(("openai", "anthropic")):
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            return ("Your AI model provider did not accept the API key. Check it, "
                    "or see: holt models\n"
                    f"The free rules-only report needs no key: {retry} --no-model")
        return ("The AI model call failed "
                f"({name}). The free rules-only report still works: {retry} --no-model")
    if isinstance(exc, RuntimeError) and " is not set" in text:
        return text  # a missing model key; `model.missing_key_message` wrote it
    if isinstance(exc, FileNotFoundError) or isinstance(exc, KeyError):
        return ("Holt has no saved copy of that run on this machine. Read GitHub "
                f"now instead: holt analyze {target} --live")
    return (f"Something went wrong: {name}: {text}\n"
            f"Please report it at {ISSUES_URL} (run again with HOLT_DEBUG=1 for details).")


def main(argv: list[str] | None = None) -> int:
    # The one place the user's model configuration takes effect. Library and
    # eval code resolve against the pinned defaults, always.
    model.enable_user_models_config()
    parser = argparse.ArgumentParser(
        prog="holt",
        description=__doc__,
        epilog=(
            "Start here:\n"
            "  holt token                     save a GitHub token (once)\n"
            "  holt analyze pallets/flask     is this repository worth your time?\n"
            "  holt                           the interactive interface\n"
            "\nNo AI model is needed. Add one for a written explanation: holt models"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Not required: bare `holt` opens the interface. Every existing invocation
    # keeps working unchanged, and the eval harness calls `holt analyze`
    # explicitly, so the reproduction path is unaffected either way.
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="assess one repository")
    analyze.add_argument("repo", help="owner/name or a github.com URL")
    # For contributors to Holt itself: the benchmark's comparison baseline and
    # the recorded model output that ships in a clone. Hidden from --help,
    # which is read by people deciding where to contribute, not by us.
    analyze.add_argument("--baseline", action="store_true", help=argparse.SUPPRESS)
    analyze.add_argument("--replay", action="store_true", help=argparse.SUPPRESS)
    analyze.add_argument(
        "--days",
        type=int,
        default=7,
        help="how many days you actually have; everything time-shaped scales from it",
    )
    analyze.add_argument(
        "--entry-points",
        action="store_true",
        help="also suggest issues to start with (experimental; needs a model, "
             "and GitHub's `good first issue` label does as well)",
    )
    analyze.add_argument(
        "--no-model",
        action="store_true",
        help="rules-only report: the verdict and the numbers, free, no AI "
             "write-up. The default when no model is set up",
    )
    analyze.add_argument("--show-verification", action="store_true",
                         help=argparse.SUPPRESS)
    analyze.add_argument(
        "--live",
        action="store_true",
        help="read GitHub now (the default outside a clone of Holt)",
    )
    analyze.add_argument(
        "--as-of",
        help="only use pull requests up to this date (YYYY-MM-DD). Defaults to today",
    )
    analyze.add_argument("--json", action="store_true",
                         help="print the report as JSON instead of text")
    analyze.set_defaults(func=cmd_analyze)

    compare = sub.add_parser(
        "compare", help="assess several repositories and show them side by side"
    )
    compare.add_argument("repos", nargs="+", help="owner/name or github.com URLs")
    compare.add_argument("--replay", action="store_true", help=argparse.SUPPRESS)
    compare.add_argument("--days", type=int, default=7,
                         help="how many days you actually have")
    compare.add_argument("--live", action="store_true",
                         help="read GitHub now (the default outside a clone of Holt)")
    compare.add_argument("--no-model", action="store_true",
                         help="rules-only: free, no AI write-up")
    compare.add_argument(
        "--as-of",
        help="only use pull requests up to this date (YYYY-MM-DD). Defaults to today",
    )
    compare.add_argument("--json", action="store_true",
                         help="print the reports as JSON instead of a table")
    compare.set_defaults(func=cmd_compare)

    next_p = sub.add_parser(
        "next",
        help="after your first merged pull request: which open issues are "
             "closest to the files you already changed",
    )
    next_p.add_argument("repo", help="owner/name or a github.com URL")
    next_p.add_argument("--as", dest="as_login", required=True,
                        help="the contributor's GitHub login")
    next_p.add_argument("--top", type=int, default=10,
                        help="how many issues to show")
    next_p.add_argument("--live", action="store_true",
                        help="read GitHub now (the default outside a clone of Holt)")
    next_p.add_argument(
        "--as-of",
        help="only use pull requests up to this date (YYYY-MM-DD). Defaults to today",
    )
    next_p.set_defaults(func=cmd_next)

    profile_p = sub.add_parser(
        "profile",
        help="say once what you want to work on; `holt discover` reads it",
    )
    profile_p.add_argument("--lang", help="comma-separated languages")
    profile_p.add_argument("--topic", help="comma-separated GitHub topics")
    profile_p.add_argument("--contribution",
                           help="comma-separated: docs, tests, ci, code")
    profile_p.add_argument("--days", dest="days_flag", type=int,
                           help="how many days you actually have")
    profile_p.set_defaults(func=cmd_profile)

    discover_p = sub.add_parser(
        "discover",
        help="search GitHub for repositories that match what you want to work "
             "on, and check each one",
    )
    discover_p.add_argument("--lang", help="comma-separated languages")
    discover_p.add_argument("--topic", help="comma-separated GitHub topics")
    discover_p.add_argument("--contribution",
                            help="comma-separated: docs, tests, ci, code")
    discover_p.add_argument("--days", dest="days_flag", type=int,
                            help="how many days you actually have")
    discover_p.add_argument("--limit", type=int, default=25,
                            help="how many candidates to source")
    discover_p.add_argument("--max-analyze", type=int, default=8,
                            help="full analyses to run at most; survivors past "
                                 "the cap are listed, not silently dropped")
    discover_p.add_argument("--live", action="store_true",
                            help="search GitHub now (needs a GitHub token)")
    discover_p.add_argument("--record", help=argparse.SUPPRESS)
    discover_p.add_argument("--session", default="demo", help=argparse.SUPPRESS)
    discover_p.set_defaults(func=cmd_discover)

    start_p = sub.add_parser(
        "start",
        help="find open starter issues in repositories that merge newcomers' work",
    )
    start_p.add_argument("repo", nargs="?",
                         help="owner/name or a github.com URL: list starter issues "
                              "in this one repository")
    start_p.add_argument("--lang", help="comma-separated languages")
    start_p.add_argument("--topic", help="comma-separated GitHub topics (any of them)")
    start_p.add_argument("--hacktoberfest", action="store_true",
                         help="only issues and repositories taking part in Hacktoberfest")
    start_p.add_argument("--limit", type=int, default=10,
                         help="how many repositories (or issues, for one repository)")
    start_p.add_argument("--days", type=int, default=7,
                         help="how many days you actually have")
    start_p.add_argument("--json", action="store_true",
                         help="print the API's JSON shape instead of text")
    start_p.set_defaults(func=cmd_start)

    models_p = sub.add_parser(
        "models",
        help="set up the AI model that writes the explanation (optional; "
             "Gemini has a free tier)",
    )
    models_p.add_argument("--provider",
                          help="gemini, openrouter, anthropic, openai, ollama, "
                               "or openai-compatible")
    models_p.add_argument("--model", dest="model_id",
                          help="model id for every stage (e.g. claude-opus-5, "
                               "llama3.3)")
    models_p.add_argument("--base-url",
                          help="endpoint for an openai-compatible server")
    models_p.add_argument("--api-key-env",
                          help="environment variable holding the API key")
    models_p.add_argument("--stage", action="append",
                          help="per-stage override, <stage>=<model>; repeatable")
    models_p.add_argument("--reset", action="store_true",
                          help="delete the configuration and restore defaults")
    models_p.set_defaults(func=cmd_models)

    token_p = sub.add_parser(
        "token",
        help="save a GitHub token so every command can read GitHub",
    )
    token_p.add_argument("--show", action="store_true",
                         help="say where the token in use comes from")
    token_p.set_defaults(func=cmd_token)




    tui = sub.add_parser(
        "tui",
        help="open the terminal interface; also what bare `holt` does",
    )
    tui.add_argument(
        "repo",
        nargs="?",
        help="owner/name or a github.com URL. Omit to open on what you have "
             "already assessed",
    )
    tui.add_argument("--replay", action="store_true", help=argparse.SUPPRESS)
    tui.add_argument(
        "--live",
        action="store_true",
        help="read GitHub now (the default outside a clone of Holt)",
    )
    tui.add_argument(
        "--days",
        type=int,
        default=7,
        help="how many days you actually have; everything time-shaped scales from it",
    )
    tui.add_argument(
        "--entry-points",
        action="store_true",
        help="also suggest issues to start with (experimental; needs a model)",
    )
    tui.set_defaults(func=cmd_tui)

    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        # No subcommand. Open the interface on what has already been assessed,
        # which is what someone typing `holt` almost always wants.
        args = parser.parse_args(["tui"])

    # Replay reproduces a recording, so it resolves against the ids that made
    # the recording -- the pinned defaults -- and not against whatever the
    # reader has since chosen with `holt models`. Without this, selecting a
    # model turned every documented `--replay` command into a replay miss,
    # because the chosen id is part of a call's identity. The user's choice
    # governs calls that actually reach a provider, which is where it means
    # something.
    replaying = getattr(args, "replay", False) or (
        args.func is cmd_discover and not getattr(args, "live", False)
    )
    if replaying:
        model.enable_user_models_config(model.ModelsConfig())

    # Every failure a person can hit ends as a sentence saying what to do,
    # never as a traceback. See `friendly_error`.
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - reworded, never swallowed silently
        if os.environ.get("HOLT_DEBUG"):
            raise
        print(friendly_error(exc, getattr(args, "repo", None)), file=sys.stderr)
        return 2 if isinstance(exc, UserError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
