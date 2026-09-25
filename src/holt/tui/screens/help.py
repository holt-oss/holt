"""The `?` overlay: every key on the screen underneath, and what Holt is.

Built from the bindings of the screen it was opened over, so it cannot drift
from what the keys actually do. The footer shows the same keys, but truncates
them on a narrow terminal, and a first-time reader also needs the one paragraph
saying what the three answers mean.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen

from holt.tui import theme
from holt.tui.visual import Line

ABOUT = (
    "Holt reads a repository's recent pull requests and tells you whether "
    "people from outside the project get replies and get their work merged. "
    "The answer is one of: Worth your time, Not worth your time, or Not "
    "enough evidence. Rules decide it; an AI model, if you set one up, only "
    "writes the explanation."
)

#: Key names Textual uses, as a person would type them.
_KEY_NAMES = {
    "question_mark": "?",
    "escape": "esc",
    "enter": "enter",
    "up": "↑",
    "down": "↓",
}


def _key(name: str) -> str:
    return ", ".join(_KEY_NAMES.get(k, k) for k in name.split(","))


def describe(bindings) -> list[tuple[str, str]]:
    """`(key, what it does)` for every binding with a description."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in bindings:
        if isinstance(item, Binding):
            key, description = item.key, item.description
        else:
            key, _action, description = (*item, "")[:3]
        if not description or key in seen:
            continue
        seen.add(key)
        rows.append((_key(key), description))
    return rows


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "close", "close"),
        ("question_mark", "close", "close"),
        ("q", "close", "close"),
    ]

    def __init__(self, bindings, title: str = "keys", **kwargs) -> None:
        super().__init__(**kwargs)
        self.rows = describe(bindings)
        self.title_text = title

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Line(Text("What Holt does", style=theme.DIM))
            yield Line(Text(ABOUT, style=theme.FAINT))
            yield Line("")
            yield Line(Text(f"Keys on this screen ({self.title_text})", style=theme.DIM))
            for key, description in self.rows:
                row = Text()
                row.append(f"{key:<12}")
                row.append(description, style=theme.FAINT)
                yield Line(row)
            yield Line("")
            yield Line(Text("esc or ? closes this", style=theme.FAINT))

    def action_close(self) -> None:
        self.dismiss(None)
