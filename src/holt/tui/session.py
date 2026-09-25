"""Running an analysis, and getting told about it.

This is the only file in the TUI that touches `holt.agent`, `holt.model` or the
evidence layer. Screens read a `Session`; they never build a provider, never
choose a model, and never call the pipeline. Moving the engine's entry point
therefore breaks one file rather than every screen.

The run happens on a worker thread and reports through a queue, so the interface
stays responsive while a live run spends a minute on the network, and needs no
cooperation from the engine to do it.

A session can also be *restored* from a stored assessment, in which case no
thread starts and nothing is spent. That path exists so that opening this
morning's result and running a new one are the same object to every screen.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from holt import credentials, paths
from holt import model as model_module
from holt.agent import entry, pipeline
from holt.evidence.fixtures import FixtureProvider, redact_records
from holt.evidence.provider import EvidenceProvider
from holt.report import VERDICT_HEADLINES, EntryPoint
from holt.tui import events, store
from holt.tui.observe import ObservingModel, ObservingProvider, RunCancelled
from holt.types import Window

# Mirrors `holt.cli`. Imported from there rather than restated so that the TUI
# reads the same fixtures the CLI and the eval harness read.
from holt.cli import ISSUE_ROOT, PATHFINDER_TRAJECTORIES, normalise


@dataclass
class RunOptions:
    repo: str
    #: Which evidence this run reads, stated at every call site rather than
    #: defaulted. The default used to be `True`: build a `RunOptions` without
    #: thinking about the question and you got committed fixtures, rendered as
    #: an assessment with no sign that is what they were. Reading a recording
    #: is a choice. It is never what you get for not making one.
    replay: bool
    live: bool = False
    #: Off by default, matching `holt analyze`. The ranking does not beat
    #: GitHub's `good first issue` label, and the engine demoted it to opt-in;
    #: an interface that turned it back on would be quietly overriding a
    #: measured decision.
    entry_points: bool = False
    contributor_days: int = 7
    #: Where a live model run records its calls: the user data directory
    #: (`~/.local/share/holt/runs` on Linux), never the current directory and
    #: never the committed recordings the eval harness replays.
    run_root: Path = field(default_factory=paths.runs_dir)
    #: Stamped once so every call in a run lands in the same file.
    started: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )

    @property
    def rules_only(self) -> bool:
        """No model will be called: none is set up, and this is not a replay.

        Decided when asked rather than stored, so setting up a model in the
        models screen takes effect on the very next run.
        """
        return not self.replay and not model_module.model_ready()

    @property
    def mode(self) -> str:
        """What this run *is*, in one word, for display and for cache keys.

        `replay` reads a recording. `recorded` makes real model calls over the
        committed fixtures. `live` additionally reads GitHub.
        """
        if self.replay:
            return "replay"
        return "live" if self.live else "recorded"

    def recording(self, repo: str, kind: str) -> Path:
        slug = repo.replace("/", "__")
        return self.run_root / slug / self.started / f"{kind}.jsonl"


@dataclass
class Session:
    """One analysis: its options, its event stream, and its result."""

    options: RunOptions
    log: list[events.Event] = field(default_factory=list)
    assessment: Any = None
    trace: Any = None
    error: str | None = None
    #: Set when this session is a stored assessment rather than a fresh run.
    #: Every screen showing a result checks it, because a reader must never have
    #: to wonder whether what they are looking at was just computed.
    restored_from: Any = None
    started_at: float = 0.0
    finished_at: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    #: The provider the run used. Evidence lookups from the interface go
    #: through it rather than through a fresh one, so a reader checking a claim
    #: sees exactly what Stage D saw — a new provider has fetched nothing and
    #: would report every id as unresolvable.
    provider: Any = None
    #: The provider a reading order read, when one ran. Kept for the same
    #: reason as `provider`: the ids under the reading order come from here and
    #: nowhere else, so storing the records behind them needs this too.
    issue_provider: Any = None
    #: Built on demand for a stored assessment, which has no run behind it.
    #: See `StoredEvidence` and `ReopenedEvidence`.
    _reopened: Any = None
    _reopen_tried: bool = False
    #: The stage the run is in, for anything showing progress without showing
    #: the stream. Set from the events, so it cannot disagree with them.
    stage: str = ""
    #: Set when the run was stopped on purpose. Distinct from `error`: a stop
    #: is not a failure, and nothing about it should read like one.
    cancelled: bool = False
    _queue: queue.Queue = field(default_factory=queue.Queue)
    _thread: threading.Thread | None = None
    _cancel: threading.Event = field(default_factory=threading.Event)
    #: Stages that finished before a stop landed. Recorded on the worker thread,
    #: which is the only thread that writes it.
    _completed: list[str] = field(default_factory=list)

    # ─── construction ───────────────────────────────────────────────────────

    @classmethod
    def restored(cls, stored: Any) -> "Session":
        """A finished session backed by a stored assessment. Nothing runs."""
        options = RunOptions(
            repo=stored.repo,
            replay=stored.mode == "replay",
            live=stored.mode == "live",
            contributor_days=stored.contributor_days,
        )
        session = cls(options=options)
        session.assessment = stored.assessment
        session.restored_from = stored
        session.started_at = stored.created_at
        session.finished_at = stored.created_at + stored.duration_seconds
        session.cost_usd = stored.cost_usd
        # The run's own stream, as it was stored. Every screen that renders a
        # trace renders it from the log, so a stored run and a live one are the
        # same thing to look at — a restored session simply has its log already
        # full instead of filling as the events arrive.
        session.log = list(getattr(stored, "events", []) or [])
        return session

    # ─── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("session already started")
        if self.restored_from is not None:
            raise RuntimeError("a restored session has nothing to run")
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Ask the run to stop. It stops at the next model call or evidence read.

        Cannot be undone, and deliberately does not join: the caller is a key
        binding, and blocking the interface until a live model call returns
        would freeze the very screen that has to say `stopping`.
        """
        self._cancel.set()

    @property
    def running(self) -> bool:
        """A worker is alive and has not yet produced an outcome."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def stopping(self) -> bool:
        """Stopped by the reader, but the worker has not wound down yet."""
        return self._cancel.is_set() and self.running

    def drain(self) -> list[events.Event]:
        """Every event that arrived since the last call. Never blocks."""
        out: list[events.Event] = []
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            self.log.append(event)
            if isinstance(event, events.RunFinished):
                self.assessment, self.trace = event.assessment, event.trace
                self.finished_at = time.time()
            elif isinstance(event, events.RunFailed):
                self.error = event.error
                self.finished_at = time.time()
            elif isinstance(event, events.RunCancelled):
                self.cancelled = True
                self.finished_at = time.time()
            elif isinstance(event, events.StageStarted):
                self.stage = event.stage
            elif isinstance(event, events.UsageUpdated):
                self.input_tokens = event.input_tokens
                self.output_tokens = event.output_tokens
                # Cost, but only when a call was actually paid for. A replay
                # reports the token counts the *original* run recorded, and
                # those price out to a real number; carrying it here would let
                # any screen render spend for a run that bought nothing.
                if not self.options.replay:
                    self.cost_usd = event.cost_usd
            out.append(event)
        return out

    @property
    def finished(self) -> bool:
        """Nothing more will arrive: it produced a report, failed, or was stopped."""
        return self.assessment is not None or self.error is not None or self.cancelled

    @property
    def duration(self) -> float:
        if not self.started_at:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    def evidence(self) -> Any:
        """Where evidence lookups from the interface go, or None.

        A run hands over the provider it used, so the inspector shows exactly
        what Stage D saw. A stored assessment has no run behind it and reads its
        evidence back on first use — see `StoredEvidence`, which is why
        reopening this morning's report and pressing enter on a claim reads the
        record rather than apologising for not having one.
        """
        if self.provider is not None:
            return self.provider
        if self.restored_from is None:
            return None
        if not self._reopen_tried:
            self._reopen_tried = True
            self._reopened = reopen_evidence(self.restored_from)
        return self._reopened

    def resolve(self, evidence_id: str):
        """The record behind an id, or None. Read-only, and never raises."""
        source = self.evidence()
        if source is None:
            return None
        try:
            return source.resolve(evidence_id)
        except Exception:  # noqa: BLE001 - the inspector reports it, not this
            return None

    @property
    def evidence_note(self) -> str:
        """Why nothing could be looked up, or "" when a lookup is possible.

        An id that was asked about and did not resolve is a statement about the
        evidence, and the inspector says so in its own words. This is the other
        case: nobody asked, and the reason is worth a sentence rather than a
        shrug — every one of them ends in something the reader can do.
        """
        source = self.evidence()
        if source is None:
            if self.restored_from is not None:
                return (
                    "This assessment read GitHub live and was stored before "
                    "holt kept the records behind its claims, which exist "
                    "nowhere else. Re-run it — ctrl+r on the report — to read "
                    "the record behind this id."
                )
            return (
                "No evidence was loaded for this session, so there is nothing "
                "to look this id up in."
            )
        return getattr(source, "unavailable", "")

    @property
    def evidence_provenance(self) -> str:
        """Where a record shown to the reader came from, when that is not the
        run itself. Empty for a session that still has its own provider."""
        return getattr(self.evidence(), "provenance", "")

    def wait(self, timeout: float | None = None) -> None:
        """Block until the worker exits. Used by tests."""
        if self._thread is not None:
            self._thread.join(timeout)
        self.drain()

    def to_entry(self) -> Any:
        """This session as something the store can keep, if it produced anything.

        A restored session returns nothing: re-saving it would move its
        timestamp forward and make a stored answer look freshly computed.
        """
        if self.assessment is None or self.restored_from is not None:
            return None
        return store.Entry(
            repo=self.options.repo,
            mode=self.options.mode,
            created_at=self.started_at or time.time(),
            assessment=self.assessment,
            contributor_days=self.options.contributor_days,
            duration_seconds=self.duration,
            cost_usd=self.cost_usd,
            events=list(self.log),
            evidence=self.evidence_for_storage(),
        )

    def evidence_for_storage(self) -> list[Any]:
        """The records behind this assessment's ids, to be stored with it.

        Only the ids the report itself carries — every claim, and every row of
        the reading order. A run reads thousands of records and storing all of
        them would put megabytes next to every report, while the interface can
        only ever look up an id that is printed on the page. What it stores is
        therefore bounded by the report, not by the repository.

        Read back out of the providers the run is still holding, which keep
        every record they fetched. That costs no network even in live mode, and
        it means the record stored is the record the run had rather than a
        fresh read of a window that has since moved.

        Credentials are stripped on the way out, the same way `write_fixture`
        strips them: this is evidence landing on disk, and it does not matter
        that the directory is a local one.
        """
        assessment = self.assessment
        if assessment is None:
            return []
        wanted = [c.evidence_id for c in assessment.claims if c.evidence_id]
        wanted += [
            point.evidence_id
            for point in (getattr(assessment, "entry_points", None) or [])
            if point.evidence_id
        ]
        found: dict[str, Any] = {}
        for evidence_id in wanted:
            if evidence_id in found:
                continue
            record = self._record_behind(evidence_id)
            if record is not None:
                found[evidence_id] = record
        records, _ = redact_records(found.values())
        return records

    def _record_behind(self, evidence_id: str) -> Any:
        """One record out of the run's own providers, or None. Never raises.

        Deliberately not through the observing wrapper: see
        `ObservingProvider.inner`. An id that cannot be looked up is stored as
        nothing at all, which the inspector already has a sentence for — better
        than taking the whole write down over one record.
        """
        for source in (self.provider, self.issue_provider):
            if source is None:
                continue
            try:
                record = getattr(source, "inner", source).resolve(evidence_id)
            except Exception:  # noqa: BLE001 - a report is worth storing regardless
                continue
            if record is not None:
                return record
        return None

    # ─── the run ────────────────────────────────────────────────────────────

    def _emit(self, event: events.Event) -> None:
        if isinstance(event, events.StageFinished):
            self._completed.append(event.stage)
        self._queue.put(event)

    def _run(self) -> None:
        opts = self.options
        repo = normalise(opts.repo)
        try:
            provider = ObservingProvider(
                _provider(opts.live), self._emit, self._cancel.is_set
            )
            self.provider = provider
            inner = _client(repo, opts, "verdict")
            # None is the rules-only run: the verdict and the counts, no model
            # call anywhere. Nothing to observe, so nothing is wrapped.
            client = (
                None
                if inner is None
                else ObservingModel(inner, self._emit, repo, self._cancel.is_set)
            )
            self._emit(events.RunStarted(repo=repo, replayed=opts.replay))

            assessment, trace = pipeline.analyze(
                repo, provider, client, contributor_days=opts.contributor_days
            )

            # Stage D's drops are recovered from the trace rather than guessed
            # from the resolution stream: the engine already decided, and the
            # view must show what it decided, not a reconstruction of it.
            for dropped in trace.dropped:
                self._emit(
                    events.FindingDropped(
                        field=dropped.field,
                        value=dropped.value,
                        cited=tuple(dropped.evidence_ids),
                        reason="unresolved",
                    )
                )
            for invented in trace.invented:
                self._emit(
                    events.FindingDropped(
                        field=invented.field,
                        value=invented.value,
                        cited=tuple(invented.evidence_ids),
                        reason="unquoted",
                    )
                )
            self._emit(
                events.StageFinished(
                    stage="verify",
                    seconds=0.0,
                    summary=(
                        f"{trace.before_verification} findings → "
                        f"{trace.after_verification} kept, {len(trace.dropped)} dropped"
                        + (f", {len(trace.invented)} unquoted" if trace.invented else "")
                    ),
                )
            )
            self._emit(
                events.StageFinished(
                    stage="verdict",
                    seconds=0.0,
                    summary=VERDICT_HEADLINES.get(
                        assessment.verdict, assessment.verdict.value
                    ),
                )
            )

            if opts.entry_points:
                self._rank(assessment, repo, provider, opts)

            self._emit(events.RunFinished(assessment=assessment, trace=trace))
        except RunCancelled:
            # Caught ahead of `Exception`: a stop the reader asked for must not
            # be reported as a defect, and nothing partial is stored.
            self._emit(events.RunCancelled(completed_stages=tuple(self._completed)))
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI, not swallowed
            self._emit(events.RunFailed(error=readable(exc, repo)))

    def _rank(self, assessment, repo: str, provider, opts: RunOptions) -> None:
        """Attach a reading order, or say nothing.

        Silent on a missing fixture for the same reason `holt.cli` is silent:
        a tool that invents an entry point when it has no issues is worse than
        one that omits the section.
        """
        issue_provider = _issue_provider(opts.live)
        try:
            issues = issue_provider.fetch(repo)
        except FileNotFoundError:
            return
        # Held on the session, not just locally: the reading order's ids resolve
        # against this and nothing else, and they are stored with the report.
        self.issue_provider = issue_provider
        try:
            client = _client(repo, opts, PATHFINDER_TRAJECTORIES)
            if client is None:
                # The ranking is model-written; rules-only has nothing to rank with.
                return
            self._emit(
                events.StageStarted(
                    stage="pathfinder", model=model_module.model_for("pathfinder")
                )
            )
            ranked = entry.rank(repo, list(issues), list(provider.fetch(repo)), client)
        except FileNotFoundError:
            return
        assessment.entry_points = [
            EntryPoint(r["evidence_id"], r["first_step"], r.get("why", ""))
            for r in ranked
        ]
        # Same reason as `holt.cli.add_entry_points`: the ranker has its own
        # client and can be pointed at its own model, and the footer names every
        # model that wrote something on the page.
        for name in client.usage.models:
            if name not in assessment.models:
                assessment.models.append(name)
        self._emit(
            events.StageFinished(
                stage="pathfinder", seconds=0.0, summary=f"{len(ranked)} issues ranked"
            )
        )


class StoredEvidence:
    """The records stored with an assessment, as something to look ids up in.

    A report is only checkable while the records under it can be read, and for
    a live run those records exist nowhere but the process that fetched them.
    So the ids the report prints are stored with it — see
    `Session.evidence_for_storage` — and this is what reads them back. Opening
    this morning's live report and pressing enter on a claim shows the record
    Stage D saw, which is the whole point of citing one.

    A fixture-backed run additionally keeps its original source, used only for
    an id the stored set does not have. `provenance` follows whichever answered,
    because "the run held this" and "this was read off disk just now" are
    different statements and the reader is owed the true one.
    """

    #: What the inspector prints under a record that came from the stored set.
    STORED = "stored with this assessment, as the run read it"

    def __init__(self, records: list[Any], fallback: Any = None) -> None:
        self._records = {
            r.evidence_id: r for r in records if getattr(r, "evidence_id", "")
        }
        #: Consulted only for an id the stored records do not cover.
        self._fallback = fallback
        #: Nothing to report: there are records, so lookups are possible.
        self.unavailable = ""
        self.provenance = self.STORED

    def resolve(self, evidence_id: str):
        record = self._records.get(evidence_id)
        if record is not None:
            self.provenance = self.STORED
            return record
        if self._fallback is None:
            return None
        record = self._fallback.resolve(evidence_id)
        # Set after the lookup, and read by the inspector after it too, so the
        # line under the record names the source that actually produced it.
        self.provenance = getattr(self._fallback, "provenance", "")
        return record


class ReopenedEvidence:
    """The source a stored assessment was built from, opened again.

    Second in line behind `StoredEvidence`, and reached only for an id the
    records stored with the report do not cover. For a replay or a recorded run
    that source is a committed fixture — reading it again reads the same bytes
    Stage D read, so the record the inspector shows is still the record the
    claim was drawn from.

    Two things this is careful about:

    * **Nothing is read until a claim is opened.** Reopening a report stays
      instant; the fixture load happens on the first `resolve`.
    * **A live run is not re-crawled.** Its records came off GitHub, and a
      remote crawl on the interface's own thread against a window that has
      moved since would not be the run's evidence however it were labelled.
      A live report is checked against the records stored with it, and an old
      one that has none gets no source at all and says so.
    """

    def __init__(self, repo: str, providers: list[Any]) -> None:
        self.repo = repo
        #: In lookup order. The first is where the report's claims came from;
        #: any others (issue evidence, behind the reading order) are extra, and
        #: their absence is ordinary rather than something to report.
        self._providers = providers
        self._loaded = False
        #: Set when the primary source could not be read at all. Shown by the
        #: inspector in place of "does not resolve", which would blame the
        #: evidence for a file that is simply not there any more.
        self.unavailable = ""
        #: Where a record shown from here actually came from. The inspector
        #: prints it under the record, because "the run held this" and "this
        #: was read back off disk just now" are different statements and only
        #: one of them is true here.
        self.provenance = ""

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for index, provider in enumerate(self._providers):
            try:
                provider.fetch(self.repo)
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                if index == 0:
                    self.unavailable = (
                        f"The evidence this assessment was built from cannot be "
                        f"read back: {readable(exc)}"
                    )

    def resolve(self, evidence_id: str):
        self._load()
        for provider in self._providers:
            try:
                record = provider.resolve(evidence_id)
            except Exception:  # noqa: BLE001 - one dead source is not the end
                continue
            if record is not None:
                return record
        return None


def reopen_evidence(stored: Any) -> Any:
    """The sources a stored assessment can be checked against, or None.

    The records the report cites are stored with it, so they come first and are
    all a live assessment ever has — its crawl is on no disk anywhere else. A
    fixture-backed one keeps its original source behind them, for an id the
    stored set happens not to cover.

    None is returned only for an assessment written before records were kept
    *and* produced live. That is the one case with nothing to read, and the
    session says which rather than blaming the evidence.
    """
    records = list(getattr(stored, "evidence", None) or [])
    fallback = _original_source(stored)
    if records:
        return StoredEvidence(records, fallback)
    return fallback


def _original_source(stored: Any) -> ReopenedEvidence | None:
    """The source the run itself read, opened again, or None if it cannot be.

    Keyed off the mode the assessment was produced in, because that is what
    decides where its ids came from. A live run is not re-crawled: see
    `ReopenedEvidence`.
    """
    if getattr(stored, "mode", "") == "live":
        return None
    repo = normalise(stored.repo)
    primary = FixtureProvider(Window.PRE_T)
    source = ReopenedEvidence(
        repo,
        # Issue evidence second: it is where the reading order's ids live, and
        # a repository without an issue fixture is ordinary rather than broken.
        [primary, FixtureProvider(Window.PRE_T, root=Path(ISSUE_ROOT))],
    )
    source.provenance = (
        f"read back from {primary.path_for(repo)}, the fixture this assessment "
        "was built from"
    )
    return source


def readable(exc: BaseException, repo: str | None = None) -> str:
    """Turn an exception into something a person can act on.

    The same wording the command line uses — `holt.cli.friendly_error` — so a
    failure reads the same sentence whichever way Holt was opened.
    """
    from holt.cli import friendly_error

    return friendly_error(exc, repo)


def _client(repo: str, opts: RunOptions, kind: str):
    """The model client for one part of a run, or None for rules-only.

    Replay reads the committed trajectory, exactly as the CLI does. A live run
    uses whichever provider `holt models` chose (`model.live_client`), and when
    no model is set up at all the run is rules-only rather than a failure.
    Recordings go under the user data directory, never the committed ones.
    """
    if opts.replay:
        directory = (
            model_module.TRAJECTORY_DIR
            if kind == "verdict"
            else model_module.TRAJECTORY_DIR / kind
        )
        return model_module.ReplayModel(directory / (repo.replace("/", "__") + ".jsonl"))
    if opts.rules_only:
        return None
    return model_module.live_client(opts.recording(repo, kind))


def missing_credentials(opts: RunOptions) -> list[str]:
    """What a run needs before it is worth starting.

    Only a GitHub token, for a run that reads GitHub. A model is never
    required: without one the run is rules-only. Looked for the same way the
    command line looks (environment, saved token, `gh auth token`).
    """
    if opts.live and not credentials.ensure_token():
        return [credentials.missing_token_message()]
    return []


def token_missing(opts: RunOptions) -> bool:
    """A live run with no GitHub token anywhere: the interface should ask."""
    return bool(missing_credentials(opts))


def recordings_available() -> bool:
    """Whether this is a clone of Holt, with recorded runs to replay."""
    try:
        return model_module.TRAJECTORY_DIR.is_dir()
    except OSError:
        return False


def has_recording(repo: str) -> bool:
    """Whether this repository can be replayed for free."""
    try:
        return (
            model_module.TRAJECTORY_DIR / (repo.replace("/", "__") + ".jsonl")
        ).is_file()
    except OSError:
        return False


def _provider(live: bool) -> EvidenceProvider:
    if not live:
        return FixtureProvider(Window.PRE_T)
    from holt.evidence.github_graphql import LiveGitHubProvider

    return LiveGitHubProvider(Window.PRE_T)


def _issue_provider(live: bool) -> EvidenceProvider:
    if not live:
        return FixtureProvider(Window.PRE_T, root=Path(ISSUE_ROOT))
    from holt.evidence.github_graphql import LiveGitHubIssueProvider

    return LiveGitHubIssueProvider(Window.PRE_T)
