"""Where the interface opens.

The first question on reopening a tool like this is almost never "assess
something new" — it is "what did it say about the thing I ran earlier". So the
screen leads with an input you can type into immediately, and everything you
have already assessed sits underneath it, readable without spending anything.

Three behaviours worth stating, because they are the ones that make it usable:

* **Typing filters the list.** The same keystrokes that name a new repository
  narrow the ones you already have, so you find out you already assessed it
  instead of paying to learn that. What you typed is normalised before it is
  matched, so a pasted `github.com` URL finds the same row `owner/name` does —
  they are the same repository and the list must not claim otherwise.
* **A recent enough answer is reused, and says so.** Pressing enter on a
  repository assessed four minutes ago opens that assessment rather than
  spending a minute and some money reproducing it. Its age is on screen and
  re-running is one key.
* **The mode is visible before you commit.** Live reads GitHub; with no model
  set up it is rules-only and free, and the chrome says so. Replay exists only
  in a clone of Holt, where recordings ship. You should never discover which
  one you were in by watching the bill.
* **Runs still going sit at the top of the same list.** Starting an assessment
  and coming back here does not stop it, so the list has to show it: enter
  rejoins it, ctrl+x stops it after asking. A run you cannot see is one you
  cannot get back to, and would be indistinguishable from one that died.
* **Everything here is reachable from the keyboard.** The input holds focus the
  whole time — that is where you type — so ↑↓ are handled by the screen and
  move the highlight through the recent list underneath it, running rows
  included. Nothing on this screen requires a mouse, and nothing requires
  guessing that tab exists.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input

from holt import model as model_module
from holt.cli import normalise
from holt.tui import animation, session as session_module, store, theme
from holt.tui.visual import Line
from holt.tui.widgets.masthead import Masthead
from holt.tui.widgets.recent import RecentList, RecentRow, RunningRow

#: Shown in the empty state. A live rules-only run, which is free and works
#: from a PyPI install: it needs a GitHub token and nothing else.
SUGGESTION = "pallets/flask"

#: Suggested instead when in replay mode, which only exists in a clone of Holt.
#: Must have a committed recording — `tests/test_tui_screens.py` holds it to that.
REPLAY_SUGGESTION = "home-assistant/core"

#: The standing hint under the input. Present by default rather than only in the
#: footer, because the question this screen has to answer immediately is "what
#: do I press", and a keybinding you have to go looking for is one you do not
#: know about.
#: `enter` spelled out rather than ⏎: the glyph renders as a box or as the
#: wrong arrow in several terminal fonts, and a hint nobody can read is worse
#: than one that takes five more columns.
HINT = (
    "enter assess    ↑↓ past ones    ctrl+f find one    "
    "ctrl+l models    ? help    ctrl+q quit"
)

#: How often the in-flight rows redraw. Slower than the event pump on purpose:
#: this is an elapsed clock and a stage name, and nothing on it changes faster
#: than a person reads.
RUNNING_TICK_SECONDS = 0.5


class HomeScreen(Screen):
    # Every key here has to survive a focused `Input`, which is where the
    # cursor sits the whole time. `ctrl+d` is the input's own delete, `ctrl+p`
    # is Textual's command palette, and a bare `q` never arrives at all — all
    # three would have been keys the footer advertised and nothing did.
    BINDINGS = [
        # ↑↓ are handled here rather than by the list, because the list never
        # holds focus — the input does, so that typing keeps working while you
        # are looking through what you already have. Hidden from the footer:
        # the hint under the input already says it, and two arrow rows would
        # crowd out the keys that are not otherwise discoverable.
        Binding("down", "browse_down", "recent", show=False),
        Binding("up", "browse_up", "recent", show=False),
        ("ctrl+f", "discover", "find a repository"),
        ("ctrl+o", "profile", "profile"),
        ("ctrl+l", "models", "models"),
        ("ctrl+r", "rerun", "re-run"),
        ("ctrl+t", "toggle_mode", "mode"),
        ("ctrl+x", "stop", "stop run"),
        ("escape", "clear", "clear"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Always live: that is what assessing a new repository means, and with
        # no model set up it is rules-only and free rather than impossible.
        # Replay is a ctrl+t away in a clone of Holt, where recordings exist.
        self.mode = "live"
        self._entries: list = []
        self._notice = ""
        #: True once ↑↓ has moved the highlight, false again as soon as anything
        #: is typed. It is the whole of what enter means on this screen: in the
        #: box, enter assesses what you wrote; in the list, enter opens the
        #: assessment you highlighted. Without it, arrowing to a row and
        #: pressing enter would run the text still sitting in the box.
        self._browsing = False
        #: What is typed in the box, kept so a rebuild triggered by a run
        #: starting or ending does not throw away the reader's filter.
        self._filter = ""

    # ─── layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="chrome"):
            yield Line("holt", id="chrome-left")
            yield Line("", id="chrome-right")
        yield Line("─" * 240, classes="rule")

        with Vertical(id="home-body"):
            yield Masthead()
            yield Line(
                Text("Assess a repository", style=theme.DIM), classes="section-label"
            )
            yield Input(
                placeholder="owner/name, or a github.com URL",
                id="repo-input",
            )
            yield Line(Text(HINT, style=theme.FAINT), id="home-notice")
            yield Line(Text("RECENT", style=theme.DIM), classes="section-label")
            yield Line("", id="home-empty", classes="empty")
            with VerticalScroll(id="recent-scroll"):
                yield RecentList([], id="recent")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_entries()
        self.query_one("#repo-input", Input).focus()
        self._paint_chrome()
        self.set_interval(RUNNING_TICK_SECONDS, self._tick_running)

    def _tick_running(self) -> None:
        """Keep the in-flight rows honest, and rebuild only when the set changes.

        Redrawing the rows costs nothing; rebuilding the list moves the reader's
        cursor. So the clock and the stage name are updated in place, and the
        list is rebuilt only when a run appears or ends.
        """
        listing = self.query_one("#recent", RecentList)
        shown = [row.session for row in listing.running_rows()]
        if [s.options.repo for s in shown] != [
            s.options.repo for s in self._in_flight()
        ]:
            self.call_later(self.refresh_entries, self._filter)
            return
        for row in listing.running_rows():
            row.refresh_row()

    def _in_flight(self) -> list:
        """In-flight runs, in a stable order so the list does not shuffle."""
        return sorted(
            self.app.in_flight, key=lambda s: (s.started_at, s.options.repo)
        )

    # ─── state ──────────────────────────────────────────────────────────────

    async def refresh_entries(self, filter_text: str = "") -> None:
        """Rebuild the recent list, optionally narrowed by what is typed.

        The list is emptied and refilled rather than replaced, because two
        widgets cannot share an id and the removal of the old one does not
        complete before the new one mounts.

        The needle is `normalise`d first. Pasting a repository's URL is the
        commonest way of naming one, and matching the raw text meant a URL
        filtered the list to nothing and then announced "nothing assessed
        matches that" about a repository sitting in the store — while enter on
        the same text opened the stored answer. Both cannot be right.
        """
        needle = normalise(filter_text).lower()
        self._filter = filter_text
        entries = [
            e for e in self.app.store.all() if not needle or needle in e.repo.lower()
        ]
        self._entries = entries
        running = [
            s
            for s in self._in_flight()
            if not needle or needle in s.options.repo.lower()
        ]

        listing = self.query_one("#recent", RecentList)
        await listing.clear()
        listing.entries = entries
        # In flight first: it is the only part of this list that is changing,
        # and the only part with something you can still act on.
        for session in running:
            await listing.append(RunningRow(session))
        for index, stored in enumerate(entries):
            row = RecentRow(stored)
            await listing.append(row)
            animation.reveal(row, delay=animation.stagger(index))

        # Something is always highlighted when there is something to highlight.
        # A list with no highlight has no keyboard position to move from, which
        # is what made the mouse the only way into it. Running rows count — they
        # are at the top, and rejoining one is the thing you are most likely to
        # have come back here to do.
        listing.index = 0 if (running or entries) else None

        self._paint_empty(entries or running, bool(needle))
        self._paint_chrome()

    def _paint_empty(self, entries: list, filtered: bool) -> None:
        widget = self.query_one("#home-empty", Line)
        if entries:
            widget.update("")
            widget.display = False
            return
        widget.display = True
        if filtered:
            message = "Nothing assessed matches that. Press enter to assess it."
        elif self.mode == "replay":
            message = (
                f"Nothing assessed yet. Type a repository above — "
                f"{REPLAY_SUGGESTION} has a recording, so it costs nothing — "
                "and press enter."
            )
        else:
            message = (
                f"Nothing assessed yet. Type a repository above and press enter — "
                f"try {SUGGESTION}. It reads GitHub and needs no AI key."
            )
        widget.update(Text(message, style=theme.FAINT))
        animation.reveal(widget)

    def _paint_chrome(self) -> None:
        count = len(self._entries)
        left = "holt"
        right = Text()
        if count:
            right.append(f"{count} assessed   ", style=theme.FAINT)
        right.append(self.mode, style=theme.DIM)
        # Whether a model will write the explanation. Beside the mode, not in
        # the notice line: the notice is where the keys are advertised.
        if self.mode != "replay":
            if model_module.model_ready():
                config = model_module.active_config()
                right.append(f"  {config.provider} model", style=theme.FAINT)
            else:
                right.append("  rules only · ctrl+l to add AI", style=theme.FAINT)
        self.query_one("#chrome-left", Line).update(Text(left, style=theme.DIM))
        self.query_one("#chrome-right", Line).update(right)

    def notice(self, message: str, tone: str = "") -> None:
        """One line under the input.

        Clearing it restores the hint rather than leaving a gap: the space is
        there either way, and an empty line teaches nobody anything.
        """
        self._notice = message
        widget = self.query_one("#home-notice", Line)
        widget.update(Text(message or HINT, style=tone or theme.FAINT))
        animation.reveal(widget)

    # ─── input ──────────────────────────────────────────────────────────────

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.value == "?":
            # The box always has focus, so `?` arrives here as a character.
            # Alone it cannot be a repository name, so it means help.
            event.input.value = ""
            self.app.action_help()
            return
        await self.refresh_entries(event.value)
        # Typing puts you back in the box, and clears any complaint about what
        # was typed before it.
        self._browsing = False
        self._describe_typed(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter belongs to the list when ↑↓ put the cursor there, and to the box
        # otherwise. Either way the row under the cursor may be a run in flight
        # rather than a stored answer, in which case enter rejoins it.
        if self._browsing or not event.value.strip():
            if self._open_highlighted():
                return
            if self._browsing:
                return

        typed = event.value.strip()
        if not typed:
            # Nothing typed and nothing to open. Doing nothing at all would read
            # as the key not working, but there is nothing honest to do here.
            return
        self.run_repo(typed)

    def _open_highlighted(self) -> bool:
        """Open whatever the cursor is on. False when it is on nothing."""
        listing = self.query_one("#recent", RecentList)
        session = listing.selected_session
        if session is not None:
            self.app.watch_run(session)
            return True
        selected = listing.selected
        if selected is not None:
            self.app.open_stored(selected)
            return True
        return False

    def on_list_view_selected(self, event) -> None:
        session = getattr(event.item, "session", None)
        if session is not None:
            self.app.watch_run(session)
            return
        entry = getattr(event.item, "entry", None)
        if entry is not None:
            self.app.open_stored(entry)

    # ─── moving through what you already have ───────────────────────────────

    def action_browse_down(self) -> None:
        self._browse(1)

    def action_browse_up(self) -> None:
        self._browse(-1)

    def _browse(self, delta: int) -> None:
        """Move the highlight without taking focus off the input."""
        listing = self.query_one("#recent", RecentList)
        # The rows, not `self._entries`: runs in flight sit above the stored
        # ones in the same list, and counting only the stored ones would make
        # the last rows unreachable by keyboard.
        total = len(listing.children)
        if not total:
            return
        current = listing.index
        if current is None:
            index = 0 if delta > 0 else total - 1
        else:
            index = max(0, min(total - 1, current + delta))
        listing.index = index
        self._browsing = True
        self._describe_highlighted()

    def _describe_highlighted(self) -> None:
        """Say what enter will do now, since it no longer means what it did.

        Once ↑↓ has moved the highlight, enter opens a stored assessment rather
        than assessing whatever is in the box. That is a change of meaning, and
        an interface that changes what a key does without saying so is one you
        have to learn by being surprised.
        """
        listing = self.query_one("#recent", RecentList)
        session = listing.selected_session
        if session is not None:
            # A run in flight is not a stored answer, and enter does a different
            # thing to it. Saying "assessed 2 min ago" about one would be wrong
            # twice over: it is not finished, and it is not being reused.
            self.notice(
                f"enter rejoins the run on {session.options.repo}.    "
                "ctrl+x stops it    esc back to the box"
            )
            return
        entry = listing.selected
        if entry is None:
            return
        age = store.describe_age(entry.age_seconds)
        self.notice(
            f"enter opens {entry.repo} — assessed {age}, {entry.mode}.    "
            "ctrl+r assesses it again    esc back to the box"
        )

    def _describe_typed(self, typed: str) -> None:
        """Whether what is in the box is something already assessed.

        The filtered list shows the row, but a row in a list is easy to read as
        "something like this exists" rather than "this exact thing exists and
        enter will hand it back to you free". So it is said in words, and it is
        said accurately: only a stored answer this mode can actually reuse is
        described as one enter will open.
        """
        repo = normalise(typed)
        match = next((e for e in self._entries if e.repo == repo), None)
        if match is None:
            self.notice("")
            return
        age = store.describe_age(match.age_seconds)
        reusable = self.app.store.fresh(repo, self.mode, match.contributor_days)
        if reusable is not None:
            self.notice(
                f"Already assessed {age} ({match.mode}). "
                "enter opens that answer rather than paying for it again; "
                "ctrl+r assesses it again."
            )
        else:
            # Present in history but too old to reuse, or stored under the other
            # mode. Enter will genuinely run something, and says so.
            self.notice(
                f"Assessed {age} ({match.mode}) — too old to reuse in {self.mode}. "
                "enter assesses it again; ↑↓ then enter re-opens what you have."
            )

    # ─── actions ────────────────────────────────────────────────────────────

    def run_repo(self, typed: str, force: bool = False) -> None:
        """Assess a repository, or open a recent enough answer for it."""
        repo = normalise(typed)
        if not _looks_like_repo(repo):
            self.notice(
                f"“{typed}” is not an owner/name or a github.com URL.", theme.DROP
            )
            return

        options = session_module.RunOptions(
            repo=repo, replay=self.mode == "replay", live=self.mode == "live"
        )

        if options.replay and not session_module.has_recording(repo):
            self.notice(
                f"No recording for {repo}. Press ctrl+t to switch to live.", theme.DROP
            )
            return

        # Already being assessed: rejoin it. Checked before the cache, because
        # a stored answer from this morning is not what someone asking for a
        # repository they are watching right now is asking for.
        in_flight = self.app.running_for(repo)
        if in_flight is not None:
            self.app.watch_run(in_flight)
            return

        if not force:
            cached = self.app.store.fresh(repo, options.mode, options.contributor_days)
            if cached is not None:
                self.app.open_stored(cached)
                return

        # First live run with no token anywhere: ask for one, then carry on.
        self.app.with_token(options, lambda: self.app.start_run(options))

    def action_rerun(self) -> None:
        """Assess again, ignoring anything stored."""
        listing = self.query_one("#recent", RecentList)
        if self._browsing and listing.selected_session is not None:
            # Already running. Re-running it would be asking the same question
            # twice and paying for both answers.
            self.notice("That one is still running. ctrl+x stops it.")
            return
        selected = listing.selected
        if self._browsing and selected is not None:
            # The highlight is what you are looking at, so it is what ctrl+r
            # acts on — the same thing enter would open.
            self.run_repo(selected.repo, force=True)
            return
        typed = self.query_one("#repo-input", Input).value.strip()
        if typed:
            self.run_repo(typed, force=True)
            return
        if selected is not None:
            self.run_repo(selected.repo, force=True)

    def action_discover(self) -> None:
        """For when you cannot name a repository, which is the usual case."""
        self.app.push_screen("discover")

    def action_profile(self) -> None:
        self.app.push_screen("profile")

    def action_models(self) -> None:
        """Which model answers, and whether it can be reached."""
        self.app.push_screen("models")

    def action_toggle_mode(self) -> None:
        if self.mode == "live" and not session_module.recordings_available():
            # An install from PyPI ships no recordings, so there is nothing to
            # switch to. Saying so beats a mode that fails on every repository.
            self.notice("Holt reads GitHub live in this install; there is no other mode.")
            return
        self.mode = "replay" if self.mode == "live" else "live"
        self._paint_chrome()
        if self.mode == "replay":
            self.notice("replay reads a committed recording: free, and only where one exists.")
        elif model_module.model_ready():
            self.notice("live reads GitHub and calls your model. Costs a few cents per run.")
        else:
            self.notice("live reads GitHub. No model is set up, so it is rules-only and free.")

    def action_clear(self) -> None:
        box = self.query_one("#repo-input", Input)
        box.value = ""
        box.focus()
        self._browsing = False
        self.notice("")

    def action_stop(self) -> None:
        """Stop the run under the cursor, after asking."""
        session = self.query_one("#recent", RecentList).selected_session
        if session is None:
            running = self._in_flight()
            if len(running) != 1:
                self.notice(
                    "Select a running assessment with ↑↓ to stop it."
                    if running
                    else "Nothing is running."
                )
                return
            # Exactly one thing is running: there is no ambiguity to resolve.
            session = running[0]
        self.app.confirm_stop(session)

    def action_quit(self) -> None:
        # Through the app, so a run still in flight is named before it dies.
        self.app.action_quit()


def _looks_like_repo(repo: str) -> bool:
    """`owner/name`, and nothing sillier.

    Catches the paste that went wrong before it becomes a network error with a
    worse message: an empty box, a bare word, a URL to something that is not a
    repository.
    """
    parts = repo.split("/")
    if len(parts) != 2:
        return False
    return all(part and not part.isspace() for part in parts)
