"""holt — is this repository worth your time?"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from holt import baseline, model, reponame
from holt.agent import entry, pipeline
from holt.evidence.fixtures import FixtureProvider
from holt.evidence.provider import EvidenceProvider
from holt.report import EntryPoint
from holt.types import T_CUTOFF, Window

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
    path = model.TRAJECTORY_DIR / PATHFINDER_TRAJECTORIES / (repo.replace("/", "__") + ".jsonl")
    client = model.ReplayModel(path) if args.replay else model.live_client(path)
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
    as_of = as_of_from(args)
    provider = make_provider(args.live, as_of)
    # Not built at all under --no-model: the mode's whole claim is that it needs
    # no key and spends nothing, and constructing a live client would demand one.
    client = None if args.no_model else model.build(repo, replay=args.replay)

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
    print(assessment.render())
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
COMPARE_HEADERS = ("repository", "verdict", "outsiders in", "first reply", "why")


def cmd_compare(args: argparse.Namespace) -> int:
    as_of = as_of_from(args)
    provider = make_provider(args.live, as_of)
    rows = []
    for raw in args.repos:
        repo = reponame.normalise(raw)
        client = model.build(repo, replay=args.replay)
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
        rows.append((repo, assessment.verdict.value, landed, reply, why))

    widths = [max(len(str(r[i])) for r in (*rows, COMPARE_HEADERS)) for i in range(5)]
    widths[4] = min(widths[4], 60)

    def line(cells) -> str:
        return "| " + " | ".join(
            str(c)[:widths[i]].ljust(widths[i]) for i, c in enumerate(cells)
        ) + " |"

    print(f"# Comparison — for a contributor with {args.days} "
          f"day{'' if args.days == 1 else 's'}\n")
    print(line(COMPARE_HEADERS))
    print("|" + "|".join("-" * (w + 2) for w in widths) + "|")  # matches "| cell " padding
    for row in rows:
        print(line(row))
    print("\n`outsiders in` counts pull requests merged from people with no prior "
          "merge, over the number who tried.")
    print("Run `holt analyze <repo>` for the evidence behind any row.")
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
        repo=reponame.normalise(repo),
        replay=args.replay,
        live=args.live,
        entry_points=args.entry_points,
        contributor_days=args.days,
    )

    # Checked before the screen is taken over, so a missing key reads as a
    # sentence in the terminal rather than a traceback behind a full-screen app.
    missing = missing_credentials(options)
    if missing:
        print("This run needs:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        return 2

    if not options.replay:
        print(
            f"Recording this run to {options.recording(options.repo, 'verdict').parent}"
            " — the committed fixtures are not written to.",
            file=sys.stderr,
        )

    run(options)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Where this contributor might look next. One deterministic rule, no model."""
    from holt.agent import progression
    from holt.agent.signals import build_threads
    from holt.issues import open_at_cutoff

    repo = reponame.normalise(args.repo)
    as_of = as_of_from(args)
    records = make_provider(args.live, as_of).fetch(repo)
    contributor = progression.history_for(args.as_login, build_threads(records))
    if not contributor.merged_count:
        print(f"`{args.as_login}` has no merged pull request in {repo} in this "
              "evidence, so path overlap has nothing to work from. "
              "`holt analyze` answers the question that comes before this one.",
              file=sys.stderr)
        return 1
    try:
        issues = make_issue_provider(args.live, as_of).fetch(repo)
    except FileNotFoundError:
        print(f"No issue evidence for {repo}; nothing to rank.", file=sys.stderr)
        return 1
    candidates = open_at_cutoff(issues)
    if not candidates:
        print(f"No issue in the evidence was open at {as_of.date().isoformat()}; "
              "nothing to rank.", file=sys.stderr)
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
            print("Nothing to search for. Run `holt profile` once, or pass "
                  "--lang/--topic.", file=sys.stderr)
            return 2
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
            print(f"No recorded discovery session named {args.session!r}. "
                  "Run with --live for a fresh search (needs GITHUB_TOKEN and "
                  "OPENAI_API_KEY).", file=sys.stderr)
            return 2
    print(out)
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
    print(f"api key env  {config.resolved_key_env()}")
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


def main(argv: list[str] | None = None) -> int:
    # The one place the user's model configuration takes effect. Library and
    # eval code resolve against the pinned defaults, always.
    model.enable_user_models_config()
    parser = argparse.ArgumentParser(prog="holt", description=__doc__)
    # Not required: bare `holt` opens the interface. Every existing invocation
    # keeps working unchanged, and the eval harness calls `holt analyze`
    # explicitly, so the reproduction path is unaffected either way.
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="assess one repository")
    analyze.add_argument("repo", help="owner/name or a github.com URL")
    analyze.add_argument(
        "--baseline",
        action="store_true",
        help="run the baseline solution: a single prompt over README and metadata",
    )
    analyze.add_argument(
        "--replay",
        action="store_true",
        help="replay recorded model output; no API key, no spend",
    )
    analyze.add_argument(
        "--days",
        type=int,
        default=7,
        help="how many days you actually have; everything time-shaped scales from it",
    )
    analyze.add_argument(
        "--entry-points",
        action="store_true",
        help="append the prototype issue ranking. Off by default: it does not beat "
             "GitHub's `good first issue` label, and the reason is that it never sees "
             "who is asking. See `eval/PATHFINDER-DESIGN.md`",
    )
    analyze.add_argument(
        "--no-model",
        action="store_true",
        help="decide with the rules alone: no API key, no spend, no model call. "
             "MCC +0.60 against the pipeline's +0.61 in sample and +0.55 against "
             "+0.63 out of sample; the report loses every citable statement",
    )
    analyze.add_argument(
        "--show-verification",
        action="store_true",
        help="print the findings Stage D dropped and why",
    )
    analyze.add_argument(
        "--live",
        action="store_true",
        help="read GitHub directly instead of committed fixtures (needs GITHUB_TOKEN)",
    )
    analyze.add_argument(
        "--as-of",
        help="only use evidence up to this date (YYYY-MM-DD). Defaults to today "
             "for --live and to the benchmark cutoff for fixtures",
    )
    analyze.set_defaults(func=cmd_analyze)

    compare = sub.add_parser(
        "compare", help="assess several repositories and show them side by side"
    )
    compare.add_argument("repos", nargs="+", help="owner/name or github.com URLs")
    compare.add_argument("--replay", action="store_true",
                         help="replay recorded model output; no API key, no spend")
    compare.add_argument("--days", type=int, default=7,
                         help="how many days you actually have")
    compare.add_argument("--live", action="store_true",
                         help="read GitHub directly instead of committed fixtures")
    compare.add_argument(
        "--as-of",
        help="only use evidence up to this date (YYYY-MM-DD). Defaults to today "
             "for --live and to the benchmark cutoff for fixtures",
    )
    compare.set_defaults(func=cmd_compare)

    next_p = sub.add_parser(
        "next",
        help="rank a repository's open issues for someone who has merged work "
             "there. Deterministic, no model call; the measured numbers print "
             "with the ranking",
    )
    next_p.add_argument("repo", help="owner/name or a github.com URL")
    next_p.add_argument("--as", dest="as_login", required=True,
                        help="the contributor's GitHub login")
    next_p.add_argument("--top", type=int, default=10,
                        help="how many issues to show")
    next_p.add_argument("--live", action="store_true",
                        help="read GitHub directly instead of committed fixtures")
    next_p.add_argument(
        "--as-of",
        help="only use evidence up to this date (YYYY-MM-DD). Defaults to today "
             "for --live and to the benchmark cutoff for fixtures",
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
        help="search GitHub for candidates, screen them for free, analyse the "
             "survivors",
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
                            help="search GitHub now (needs GITHUB_TOKEN and "
                                 "OPENAI_API_KEY)")
    discover_p.add_argument("--record",
                            help="record this live session under a name so it "
                                 "replays with no credentials (implies --live)")
    discover_p.add_argument("--session", default="demo",
                            help="which recorded session to replay "
                                 "(default: demo)")
    discover_p.set_defaults(func=cmd_discover)

    models_p = sub.add_parser(
        "models",
        help="show or change which model answers; defaults to the pinned ids "
             "the benchmark was measured on",
    )
    models_p.add_argument("--provider",
                          help="openai, anthropic, ollama, gemini, or "
                               "openai-compatible")
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
    tui.add_argument(
        "--replay",
        action="store_true",
        help="replay recorded model output; no API key, no spend",
    )
    tui.add_argument(
        "--live",
        action="store_true",
        help="read GitHub directly instead of committed fixtures (needs GITHUB_TOKEN)",
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
        help="include the prototype issue ranking. Off by default, matching "
             "`holt analyze`: it does not beat GitHub's `good first issue` label",
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

    # A missing fixture or trajectory is a thing the reader can act on -- capture
    # it, or use `--replay` -- and the message already says so. A traceback buries
    # that under twenty frames of our internals, so print the message and stop.
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"holt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
