"""The record behind an evidence id.

Opened from a claim. This is the screen that makes the report checkable: a
reader who does not believe a sentence presses enter on it and reads the record
it was drawn from, with its source, its timestamp and its url.

Resolution goes through the evidence the session has. For a run that is the
provider the run used, so what is shown is what Stage D saw. For an assessment
reopened out of the store it is the records stored with it, which are the ones
the run read, and the screen says under the record where it came from rather
than leaving a reader to assume.

There are three outcomes and they are three different sentences, because
collapsing them would be a lie in at least one case:

* the record resolved, and is shown, labelled with where it was read from
* the id does not resolve against the evidence, which is why a claim citing it
  would have been dropped
* nothing could be looked up at all — an assessment stored before records were
  kept, or a fixture no longer on disk — and the screen says which, and what
  to do
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer

from holt.tui import animation, theme
from holt.tui.visual import Line
from holt.tui.widgets.evidence import EvidenceDetail, cite


class InspectorScreen(Screen):
    BINDINGS = [
        ("escape", "back", "back"),
        ("o", "open_on_github", "open on GitHub"),
        ("q", "quit", "quit"),
    ]

    def __init__(
        self,
        evidence_id: str,
        record,
        resolvable: bool = True,
        note: str = "",
        provenance: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.evidence_id = evidence_id
        self.record = record
        #: False when nothing could be looked up. Keeps the screen from
        #: reporting "does not resolve" about an id nobody asked about.
        self.resolvable = resolvable
        #: Why nothing was looked up, in the session's own words.
        self.note = note
        #: Where a shown record was read from, when that is worth saying.
        self.provenance = provenance

    def compose(self) -> ComposeResult:
        with Horizontal(id="chrome"):
            yield Line("holt · evidence", id="chrome-left")
            yield Line(self._status(), id="chrome-right")
        yield Line("─" * 240, classes="rule")
        with VerticalScroll(id="record"):
            if self.record is None and not self.resolvable:
                yield Line(cite(self.evidence_id))
                yield Line("")
                yield Line(
                    Text(self.note or _NOTHING_LOADED, style=theme.FAINT),
                    classes="empty",
                )
            else:
                yield EvidenceDetail(self.record)
                if self.record is not None and self.provenance:
                    yield Line("")
                    yield Line(Text(self.provenance, style=theme.FAINT))
        yield Line("─" * 240, classes="rule")
        yield Footer()

    def on_mount(self) -> None:
        animation.reveal(self.query_one("#record", VerticalScroll))

    def _status(self) -> Text:
        if self.record is not None:
            return Text("resolved", style=theme.FAINT)
        if not self.resolvable:
            return Text("not loaded", style=theme.FAINT)
        return Text("does not resolve", style=theme.DROP)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_open_on_github(self) -> None:
        from holt.report import evidence_url
        from holt.tui.screens.token import open_url

        url = getattr(self.record, "url", "") or evidence_url(self.evidence_id)
        if url:
            open_url(url)

    def action_quit(self) -> None:
        self.app.exit()


#: Only reached if a caller gives no reason of its own. The session always has
#: one; this keeps the screen from rendering a blank where a sentence belongs.
_NOTHING_LOADED = (
    "No evidence is loaded for this assessment, so this id has not been looked "
    "up. Re-run it to read the record behind it."
)
