"""Finding a repository when you do not have one in mind.

The rest of the interface assumes you can name what you want assessed. Often you
cannot — that is the actual starting position — and this is the screen for it.

**It opens on a choice, not on a list.** It used to open on a recorded search
that shipped in the repository: twenty-five repositories somebody else's profile
turned up, on a date in the past, presented exactly as a result would be. As a
demo of the screening rule that is honest; as the first thing `ctrl+f` does it
is not, because those repositories are not an answer to *your* question and no
amount of labelling makes them one. So the recording is still here, still free,
and now something you ask for. What the screen offers first is a live search.

Live search is free in the sense that matters: `screen_records` runs no model,
so a sweep costs GitHub API quota and about a minute of waiting. Rows are drawn
as they land rather than after the last one, because a minute of blank screen
reads as a hang. The model cost is where it always was — pressing enter on a row
starts an ordinary assessment run.

Two things it will not do:

* **Hide what it rejected.** Nine of twenty-five candidates being cut for free
  is the interesting result, not an implementation detail. They stay listed.
* **Reorder survivors.** Screening says a candidate is worth a closer look; it
  does not say one is better than another, and sorting them would assert that it
  did. They keep the order the search returned them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, ListItem, ListView

from holt import profile as profile_mod
from holt.profile import Profile
from holt.tui import animation, discovery, session as session_module, theme
from holt.tui.visual import Line
from holt.tui.widgets.candidates import CandidateList

#: How often the screen picks up rows the search thread has finished. The sweep
#: is network-bound and lands a row every few seconds, so this is about not
#: looking frozen rather than about frame rate.
POLL_SECONDS = 0.1

START_HINT = "enter choose    ctrl+o change what you are looking for    esc back"
SEARCH_HINT = "enter assess this one    ctrl+x stop searching    esc back"
DONE_HINT = "enter assess this one    ctrl+o change what you are looking for    esc back"


@dataclass(slots=True)
class Choice:
    """One way out of the start screen."""

    action: str
    title: str
    detail: str


class ChoiceItem(ListItem):
    def __init__(self, choice: Choice, **kwargs) -> None:
        super().__init__(**kwargs)
        self.choice = choice

    def compose(self):
        yield Line(Text(self.choice.title))
        yield Line(Text(f"  {self.choice.detail}", style=theme.FAINT))


class ChoiceList(ListView):
    def __init__(self, choices: list[Choice], **kwargs) -> None:
        super().__init__(*[ChoiceItem(c) for c in choices], **kwargs)
        self.choices = choices


class DiscoverScreen(Screen):
    BINDINGS = [
        ("ctrl+o", "profile", "change what you want"),
        ("ctrl+x", "stop", "stop searching"),
        ("escape", "home", "home"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, session: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        # Not `self.name`: Textual widgets already own that, and assigning to it
        # raises inside the screen's constructor, where the failure surfaces as
        # a screen that simply never appears.
        #
        # `None` means "start on the choice". A name means the caller asked for
        # that recording specifically, which is how the demo is still reachable.
        self.session_name = session
        self.session: discovery.Session | None = None
        self.search: discovery.Search | None = None
        self.error = ""
        #: How many of the search's rows are already on screen.
        self._cursor = 0
        self._timer = None

    # ─── layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        if self.session_name is not None:
            self._load_recording(self.session_name)

        with Horizontal(id="chrome"):
            yield Line("holt · discover", id="chrome-left")
            yield Line(self._provenance(), id="chrome-right")
        yield Line("─" * 240, classes="rule")

        with Vertical(id="discover-body"):
            if self.error:
                yield Line(Text(self.error, style=theme.DROP), classes="empty")
            else:
                # Both panes are built once and shown one at a time. Tearing a
                # pane down and building another in its place mid-search is a
                # race against the poll timer that has nothing to gain.
                with Vertical(id="discover-start"):
                    yield Line("", id="start-looking", classes="section-label")
                    yield Line(
                        Text(START_HINT, style=theme.FAINT), id="start-hint"
                    )
                    yield ChoiceList(self._choices(), id="choices")
                with Vertical(id="discover-results"):
                    yield Line("", id="results-looking", classes="section-label")
                    yield Line("", id="results-counts", classes="section-label")
                    yield Line("", id="discover-hint")
                    with VerticalScroll(id="candidate-scroll"):
                        yield CandidateList(id="candidates")
        yield Footer()

    def on_mount(self) -> None:
        if self.error:
            return
        if self.session is not None:
            self._present_recording()
        else:
            self._show_start()

    def check_action(self, action: str, parameters):
        """Stopping is only offered while there is something to stop.

        The footer is read as a statement of what the screen can do right now,
        and advertising a key that does nothing on the start screen made the
        choice look like a search that was already running.
        """
        if action == "stop":
            return self.search is not None and self.search.running
        return True

    def on_screen_resume(self) -> None:
        """Coming back from the profile screen must not show the old profile."""
        if self.error or self.search is not None or self.session is not None:
            return
        # Resume can arrive before the first mount, when there is nothing on
        # screen to bring up to date and nothing to report either.
        try:
            self.query_one("#start-looking", Line).update(self._looking())
        except NoMatches:
            return

    # ─── the choice ─────────────────────────────────────────────────────────

    def _choices(self) -> list[Choice]:
        choices = [
            Choice(
                "live",
                "Search GitHub for repositories",
                "reads GitHub directly and screens every candidate for free",
            ),
            Choice(
                "profile",
                "Change what you are looking for",
                "languages, topics, the kind of work, how long you will wait",
            ),
        ]
        # Offered only when it exists, and described as what it is. A recorded
        # search presented without its date is a result presented as current.
        if discovery.manifest_path_exists():
            choices.append(
                Choice(
                    "replay",
                    "Replay the recorded example search",
                    "somebody else's profile, screened from committed fixtures",
                )
            )
        return choices

    def _show_start(self) -> None:
        self.query_one("#discover-start").display = True
        self.query_one("#discover-results").display = False
        self.query_one("#start-looking", Line).update(self._looking())
        choices = self.query_one("#choices", ChoiceList)
        for index, item in enumerate(choices.children):
            animation.reveal(item, delay=animation.stagger(index))
        choices.focus()

    def _looking(self) -> Text:
        stored = profile_mod.load()
        if stored is None:
            return Text(
                "No profile saved — a search would look for any active repository. "
                "Change what you are looking for to narrow it.",
                style=theme.DIM,
            )
        return Text(f"Looking for {stored.describe()}", style=theme.DIM)

    def _profile(self) -> Profile:
        """What to search for. An unsaved profile is a broad search, not a
        refusal: `build_queries` handles an empty one and returns a real query."""
        return profile_mod.load() or Profile()

    # ─── the live search ────────────────────────────────────────────────────

    def _start_live(self) -> None:
        missing = discovery.missing_token()
        if missing:
            # Ask for one, and start the search as soon as it is saved. The
            # choice stays put either way, with the reason under it.
            self.query_one("#start-hint", Line).update(Text(missing, style=theme.DROP))
            from holt.tui.screens.token import TokenScreen

            self.app.push_screen(
                TokenScreen(), lambda saved: self._start_live() if saved else None
            )
            return

        self.search = discovery.Search(profile=self._profile())
        self.search.start()

        self.query_one("#discover-start").display = False
        self.query_one("#discover-results").display = True
        self.query_one("#results-looking", Line).update(self._looking())
        self.query_one("#results-counts", Line).update(
            Text(self.search.describe(), style=theme.FAINT)
        )
        self.query_one("#discover-hint", Line).update(
            Text(SEARCH_HINT, style=theme.FAINT)
        )
        self.query_one("#chrome-right", Line).update(self._provenance())
        self.query_one("#candidates", CandidateList).focus()
        self._timer = self.set_interval(POLL_SECONDS, self._pump)
        self.refresh_bindings()

    def _pump(self) -> None:
        """Draw whatever the worker has screened since the last tick."""
        search = self.search
        if search is None:
            return

        candidates = self.query_one("#candidates", CandidateList)
        pending = search.rows[self._cursor :]
        self._cursor = len(search.rows)
        for row in pending:
            animation.reveal(candidates.add(row))
        if pending and candidates.index is None:
            # Nothing is highlighted until the list has something in it, and
            # without this the first row arrives with no cursor on it.
            candidates.index = 0

        self.query_one("#results-counts", Line).update(
            Text(search.describe(), style=theme.FAINT)
        )

        if search.finished and self._cursor == len(search.rows):
            self._finish()

    def _finish(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.refresh_bindings()
        search = self.search
        if search is None:
            return
        self.query_one("#chrome-right", Line).update(self._provenance())
        if search.error:
            self.query_one("#discover-hint", Line).update(
                Text(search.error, style=theme.DROP)
            )
            return
        if not search.rows:
            self.query_one("#discover-hint", Line).update(
                Text(
                    "Nothing came back. Widening the languages or topics is the "
                    "next thing to try — ctrl+o.",
                    style=theme.DROP,
                )
            )
            return
        self.query_one("#discover-hint", Line).update(
            Text(DONE_HINT, style=theme.FAINT)
        )

    # ─── the recording ──────────────────────────────────────────────────────

    def _load_recording(self, name: str) -> None:
        try:
            self.session = discovery.load(name)
        except FileNotFoundError:
            self.error = (
                f"No recorded search named {name!r}. "
                "`holt discover --live --record <name>` makes one."
            )
        except Exception as exc:  # noqa: BLE001 - reported, never a traceback
            self.error = session_module.readable(exc)

    def _present_recording(self) -> None:
        found = self.session
        if found is None:
            return
        self.query_one("#discover-start").display = False
        self.query_one("#discover-results").display = True
        self.query_one("#results-looking", Line).update(
            Text(f"Looking for {found.profile_description}", style=theme.DIM)
        )
        self.query_one("#results-counts", Line).update(
            Text(self._counts(), style=theme.FAINT)
        )
        self.query_one("#discover-hint", Line).update(
            Text(DONE_HINT, style=theme.FAINT)
        )
        candidates = self.query_one("#candidates", CandidateList)
        for index, row in enumerate(found.rows):
            animation.reveal(candidates.add(row), delay=animation.stagger(index))
        if found.rows:
            candidates.index = 0
        # The list, not the scroll box around it. Focus landed on the container
        # by default, where ↑↓ scrolled past the candidates and enter did
        # nothing — the only way to assess one was to click it.
        candidates.focus()

    def _counts(self) -> str:
        found = self.session
        if found is None:
            return ""
        total, survived = len(found.rows), len(found.survivors)
        text = (
            f"{total} candidates screened at no model cost · "
            f"{survived} worth a closer look · {total - survived} cut"
        )
        if found.skipped:
            text += f" · {len(found.skipped)} had no recorded evidence"
        return text

    def _provenance(self) -> Text:
        text = Text()
        if self.session is not None:
            text.append(f"{self.session.name}   ", style=theme.FAINT)
            text.append(
                f"recorded {self.session.as_of.date().isoformat()}", style=theme.FAINT
            )
        elif self.search is not None:
            when = "searching" if self.search.running else "live"
            text.append(when, style=theme.FAINT)
            if self.search.as_of is not None:
                text.append(
                    f"   {self.search.as_of.date().isoformat()}", style=theme.FAINT
                )
        return text

    # ─── actions ────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event) -> None:
        choice = getattr(event.item, "choice", None)
        if choice is not None:
            self._choose(choice)
            return
        row = getattr(event.item, "row", None)
        if row is not None:
            self._assess(row)

    def _choose(self, choice: Choice) -> None:
        if choice.action == "live":
            self._start_live()
        elif choice.action == "profile":
            self.action_profile()
        elif choice.action == "replay":
            self._load_recording(discovery.DEFAULT_SESSION)
            if self.error:
                self.query_one("#start-hint", Line).update(
                    Text(self.error, style=theme.DROP)
                )
                self.error = ""
                return
            self.session_name = discovery.DEFAULT_SESSION
            self.query_one("#chrome-right", Line).update(self._provenance())
            self._present_recording()

    def _assess(self, row) -> None:
        """Assess this candidate the way the search that found it read GitHub.

        **The mode follows the search, not the disk.** It used to be
        `replay = has_recording(row.slug)`: search GitHub live, press enter on
        a result, and if a trajectory happened to be sitting in `fixtures/` you
        were handed a recorded answer from June instead of an assessment of
        what you had just found. Nothing on screen said so. Which evidence a
        run reads is a choice, and it is not one the contents of a directory
        get to make on the reader's behalf.

        So: rows from a live sweep are assessed live, rows from a recorded
        session are replayed, and a recorded row with no trajectory says that
        rather than quietly going live and asking for credentials.
        """
        replay = self.session_name is not None
        if replay and not session_module.has_recording(row.slug):
            self._hint(
                f"No recording of an assessment of {row.slug}, so it cannot be "
                "replayed. Assess it live from the home screen."
            )
            return
        options = session_module.RunOptions(
            repo=row.slug, replay=replay, live=not replay
        )
        cached = self.app.store.fresh(
            row.slug, options.mode, options.contributor_days
        )
        if cached is not None:
            self.app.open_stored(cached)
            return
        self.app.with_token(options, lambda: self.app.start_run(options))

    def _hint(self, message: str) -> None:
        self.query_one("#discover-hint", Line).update(Text(message, style=theme.DROP))

    def action_profile(self) -> None:
        """The profile is what this search was built from, so it is edited here."""
        self.app.push_screen("profile")

    def action_stop(self) -> None:
        """Stop the sweep. Rows already screened stay: they were free, they are
        still true, and throwing them away would punish impatience."""
        if self.search is not None and self.search.running:
            self.search.cancel()
            self.refresh_bindings()

    def action_home(self) -> None:
        self.app.go_home()

    def action_quit(self) -> None:
        self.app.exit()
