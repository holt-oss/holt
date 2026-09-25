"""Asking for a GitHub token, once.

The first thing a beginner hits is that GitHub's API wants a token even for
public data. Instead of a sentence telling them to go and set an environment
variable, the interface asks: here is the link, paste it here. It is saved to
the config directory with 0600 permissions (`holt.credentials`) and never shown
again — the input is a password field, and nothing echoes its value.

Escape skips. Skipping is allowed because a clone of Holt can still open past
assessments without one, and a prompt you cannot get out of is a trap.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input

from holt import credentials
from holt.tui import theme
from holt.tui.visual import Line


class TokenScreen(ModalScreen[bool]):
    """Dismisses True once a token has been saved, False if skipped."""

    BINDINGS = [
        ("escape", "skip", "skip"),
        ("ctrl+o", "open_link", "open the link"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="token-box"):
            yield Line(Text("Connect to GitHub", style=theme.DIM))
            yield Line(
                Text(
                    "Holt reads a repository's recent pull requests, and GitHub "
                    "asks for a token even to read public data. It needs no "
                    "permissions: leave every box unticked.",
                    style=theme.FAINT,
                )
            )
            yield Line("")
            yield Line(Text(f"1. Create one:  {credentials.TOKEN_URL}"))
            yield Line(Text("   (ctrl+o opens it in your browser)", style=theme.FAINT))
            yield Line(Text("2. Paste it below and press enter."))
            yield Input(
                placeholder="ghp_… or github_pat_…",
                password=True,
                id="token-input",
            )
            yield Line("", id="token-error")
            yield Line(
                Text(
                    "Saved on this computer only, readable only by you.    "
                    "esc skip",
                    style=theme.FAINT,
                )
            )

    def on_mount(self) -> None:
        self.query_one("#token-error", Line).display = False
        self.query_one("#token-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            credentials.save_token(event.value)
        except (ValueError, OSError) as exc:
            error = self.query_one("#token-error", Line)
            error.update(Text(f"{exc} Try pasting it again.", style=theme.DROP))
            error.display = True
            return
        self.dismiss(True)

    def action_open_link(self) -> None:
        open_url(credentials.TOKEN_URL)

    def action_skip(self) -> None:
        self.dismiss(False)


def open_url(url: str) -> bool:
    """Open a link in the browser. False when there is no browser to open."""
    import webbrowser

    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 - a missing browser is not a crash
        return False
