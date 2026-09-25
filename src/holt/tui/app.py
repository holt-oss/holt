"""The application shell.

It owns five things and nothing else: the screen registry, the global
keybindings, the store of past assessments, the runs currently in flight, and
the session being looked at. It contains no rendering and no engine knowledge,
so a new view is a new file plus one line in `holt.tui.screens.REGISTRY`.

Navigation is deliberately shallow. Home holds everything you have; a run or a
stored result is one push deep; the evidence behind a claim is two. There is no
state you can get into where the way back is unclear, because every screen binds
escape to the thing above it.

**A run belongs to the app, not to the screen watching it.** The pump that
drains every in-flight session lives here and ticks whether or not anyone is
looking, so walking away from a run leaves it running. It used to live on the
live screen, which meant popping that screen stopped the only thing consuming
the run's events: the worker thread carried on spending, its result was never
absorbed, and the assessment it produced was silently thrown away. A run now
ends for exactly one reason — it finished, it failed, or someone stopped it.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.await_complete import AwaitComplete
from textual.screen import Screen

from holt.cli import normalise
from holt.tui import mascot, store, theme
from holt.tui.commands import HoltCommands
from holt.tui.screens import REGISTRY
from holt.tui.screens.assessment import AssessmentScreen
from holt.tui.screens.confirm import ConfirmScreen
from holt.tui.screens.inspector import InspectorScreen
from holt.tui.screens.live import LiveScreen
from holt.tui.session import RunOptions, Session

#: How often the app absorbs what the running sessions have emitted. The same
#: interval the live screen redraws on: the screen renders what this has already
#: collected, so a slower pump here would show as a laggy stream.
PUMP_SECONDS = 0.05


class HoltApp(App):
    CSS = theme.CSS
    SCREENS = REGISTRY
    TITLE = "holt"

    #: One provider, not a union with `App.COMMANDS`. It yields holt's commands
    #: and then the framework's, so the order is written down rather than
    #: decided by set iteration and a race between concurrent providers.
    COMMANDS = {HoltCommands}

    BINDINGS = [
        ("ctrl+c", "quit", "quit"),
        # `q` quits every screen that has no text box on it. Home does have
        # one, and the input takes the key as a character, so a bare `q` never
        # arrives there — which left the front screen as the only one in the
        # app with no visible way out. `ctrl+q` works everywhere, including
        # while you are typing, and being app-level it is on every footer.
        ("ctrl+q", "quit", "quit"),
        # `?` everywhere a text box is not focused; home, whose box always is,
        # catches a lone `?` typed into it instead. f1 works regardless.
        ("question_mark", "help", "help"),
        Binding("f1", "help", "help", show=False),
    ]

    def __init__(
        self,
        options: RunOptions | None = None,
        assessments: store.Store | None = None,
    ) -> None:
        super().__init__()
        #: Chosen once, at launch, and worn only by the cat and the masthead.
        #: The colours that mean something -- verdict, evidence, drops -- are
        #: fixed in `theme`, so a different accent each session changes how the
        #: interface looks and never what it says.
        self.accent = mascot.pick_accent()
        self.store = assessments or store.Store()
        #: Set when the interface was launched with a repository to assess.
        #: Without one it opens on home, which is the ordinary case.
        self.initial = options
        self.session: Session | None = None
        #: Runs in flight, keyed by repository. One run per repository: asking
        #: for one that is already running reattaches to it rather than paying
        #: twice for the same answer.
        self.runs: dict[str, Session] = {}

    def on_mount(self) -> None:
        self.set_interval(PUMP_SECONDS, self.pump)
        self.push_screen("home")
        if self.initial is not None:
            initial = self.initial
            self.with_token(initial, lambda: self.start_run(initial))

    # ─── first run ──────────────────────────────────────────────────────────

    def with_token(self, options: RunOptions, then) -> None:
        """Run `then` once a live run has a GitHub token to read with.

        The first live run on a machine with no token anywhere opens the
        prompt instead of failing; the run starts as soon as a token is saved.
        Skipping the prompt starts nothing, and the home screen says why.
        """
        from holt.tui.session import token_missing

        if not token_missing(options):
            then()
            return
        from holt.tui.screens.token import TokenScreen

        def done(saved: bool | None) -> None:
            if saved:
                then()
            else:
                home = self._home()
                if home is not None:
                    home.notice(
                        "Holt needs a GitHub token to read a repository. "
                        "Press enter on it again when you have one.",
                        theme.DROP,
                    )

        self.push_screen(TokenScreen(), done)

    def _home(self):
        for screen in self.screen_stack:
            if hasattr(screen, "run_repo"):
                return screen
        return None

    def action_help(self) -> None:
        """The keys on the screen you are looking at, and what Holt is."""
        from holt.tui.screens.help import HelpScreen

        screen = self.screen
        if isinstance(screen, HelpScreen):
            return
        bindings = list(getattr(type(screen), "BINDINGS", [])) + list(self.BINDINGS)
        name = type(screen).__name__.removesuffix("Screen").lower() or "holt"
        self.push_screen(HelpScreen(bindings, title=name))

    # ─── the pump ───────────────────────────────────────────────────────────

    def pump(self) -> None:
        """Absorb what every in-flight run has emitted, and keep its result.

        Runs regardless of which screen is up. A session that has produced an
        outcome is stored and unregistered here — never by a screen, because a
        screen that has been popped cannot store anything.
        """
        for repo, session in list(self.runs.items()):
            session.drain()
            if session.finished:
                self.remember(session)
                self.runs.pop(repo, None)

    @property
    def in_flight(self) -> list[Session]:
        """Runs that are still working, newest last."""
        return [s for s in self.runs.values() if not s.finished]

    def running_for(self, repo: str) -> Session | None:
        return self.runs.get(normalise(repo))

    # ─── navigation ─────────────────────────────────────────────────────────

    def push_screen(self, screen, *args, **kwargs):
        """Open a screen — or go back to it, when it is already open.

        A screen opened by name is the *installed instance*: `push_screen(
        "discover")` hands back the same object every time. Pushing one that is
        already in the stack therefore puts a single `Screen` at two depths at
        once, and that is not merely untidy. Every screen here is
        `background: transparent`, so Textual renders the whole stack beneath
        the current screen as its background — and a screen that appears twice
        in that stack renders itself inside itself until Python runs out of
        stack. The interface died with a `RecursionError` out of the
        compositor, from a path as ordinary as ctrl+f, ctrl+o, and then "find a
        repository" off the palette.

        Going back to it is also what the key meant. `go_home` already pops
        rather than pushing a second home, for the same reason: one screen, one
        place in the stack.
        """
        open_already = self._open_already(screen)
        if open_already is None:
            return super().push_screen(screen, *args, **kwargs)
        return self._return_to(open_already)

    def _open_already(self, screen) -> Screen | None:
        """The instance this push would open, if the stack already holds it.

        Identity, not type. Two `AssessmentScreen`s are two reports and both
        belong on the stack; what cannot happen is one object appearing twice.
        """
        if isinstance(screen, str):
            try:
                screen = self.get_screen(screen)
            except KeyError:
                return None
        if not isinstance(screen, Screen):
            return None
        return screen if any(open_ is screen for open_ in self.screen_stack) else None

    def _return_to(self, screen: Screen) -> AwaitComplete:
        """Pop back down to a screen already open. A no-op if it is on top."""
        popped: AwaitComplete | None = None
        while self.screen is not screen and len(self.screen_stack) > 1:
            popped = self.pop_screen()
        return popped if popped is not None else AwaitComplete()

    def start_run(self, options: RunOptions) -> None:
        """Assess a repository, and watch it happen.

        Reattaches if that repository is already being assessed. Two runs of the
        same repository would produce two answers to one question, and on live
        they would be paid for separately.
        """
        repo = normalise(options.repo)
        existing = self.runs.get(repo)
        if existing is not None:
            self.watch_run(existing)
            return
        session = Session(options)
        self.runs[repo] = session
        self.session = session
        session.start()
        self.push_screen(LiveScreen())

    def watch_run(self, session: Session) -> None:
        """Reopen the live view on a run already in progress.

        The screen rebuilds from the session's log, so a run joined half way
        through shows everything it has done, not only what happens next.
        """
        self.session = session
        self.push_screen(LiveScreen())

    def open_stored(self, entry) -> None:
        """Open an assessment that has already been produced. Nothing runs."""
        self.session = Session.restored(entry)
        self.push_screen(AssessmentScreen())

    def show_assessment(self) -> None:
        if self.session is not None and self.session.assessment is not None:
            self.push_screen(AssessmentScreen())

    def inspect(self, evidence_id: str) -> None:
        """Resolve an id and show the record behind it.

        The lookup goes through the session's own evidence — the provider the
        run used, or, for an assessment reopened out of the store, the fixture
        that run read, opened again. Either way the interface cannot show a
        reader something Stage D did not have access to.

        When there is nothing to look an id up in at all, the screen says that
        and why, rather than claiming the id does not resolve — a very
        different statement, and only one of them would be true.
        """
        session = self.session
        record = session.resolve(evidence_id) if session else None
        note = session.evidence_note if session else ""
        self.push_screen(
            InspectorScreen(
                evidence_id,
                record,
                resolvable=not note,
                note=note,
                provenance=session.evidence_provenance if session else "",
            )
        )

    def go_home(self) -> None:
        """Back to the list, however deep the current screen is.

        Leaves any run alone. Escape means "stop looking at this", never "stop
        doing this" — stopping has its own key and its own confirmation.
        """
        # Home sits at index 1, above Textual's own base screen. Popping to
        # exactly that leaves home on top however deep the stack got.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        home = self.screen
        if hasattr(home, "refresh_entries"):
            # Coroutine: scheduled rather than awaited, because the caller is a
            # key binding and the list catching up a frame later is invisible.
            home.call_later(home.refresh_entries)

    # ─── stopping ───────────────────────────────────────────────────────────

    def confirm_stop(self, session: Session) -> None:
        """Ask before stopping. A stopped run keeps nothing it had computed."""
        if session is None or session.finished:
            return
        self.push_screen(
            ConfirmScreen(
                f"stop {session.options.repo}?",
                _spent(session),
                yes="y stop",
                no="n keep running",
            ),
            lambda confirmed: self._stop(session, bool(confirmed)),
        )

    def _stop(self, session: Session, confirmed: bool) -> None:
        if confirmed:
            session.cancel()

    def action_quit(self) -> None:
        """Quit, but never silently discard a run that is still working."""
        running = self.in_flight
        if not running:
            self.exit()
            return
        detail = "   ".join(f"{s.options.repo} {_spent(s)}" for s in running)
        self.push_screen(
            ConfirmScreen(
                f"{len(running)} run{'s' if len(running) > 1 else ''} still in flight",
                f"{detail}\nquitting stops {'them' if len(running) > 1 else 'it'}.",
                yes="y quit",
                no="n go back",
            ),
            lambda confirmed: self.exit() if confirmed else None,
        )

    # ─── persistence ────────────────────────────────────────────────────────

    def remember(self, session: Session) -> None:
        """Keep a finished assessment so the next launch opens on it."""
        entry = session.to_entry()
        if entry is not None:
            self.store.save(entry)


def _spent(session: Session) -> str:
    """Elapsed, and money if any was actually spent."""
    minutes, seconds = divmod(int(session.duration), 60)
    text = f"{minutes}:{seconds:02d}"
    if session.cost_usd:
        text += f"   ${session.cost_usd:.4f}"
    return text


def run(options: RunOptions | None = None) -> None:
    HoltApp(options).run()
