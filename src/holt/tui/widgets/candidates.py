"""Candidates a search turned up, and what free screening made of them.

Screening is the cheap half: it runs no model, so it can look at everything and
throw most of it away before anything is spent. That is the fact the list has to
communicate, which is why the ones that were cut stay on screen with the reason
attached. A discovery tool that shows only its survivors is asking to be trusted
about the ones it hid.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import ListItem, ListView

from holt.tui import theme
from holt.tui.discovery import cut_reason
from holt.tui.visual import Line
from holt.tui.widgets.scrolling import KeepsHighlightVisible


class CandidateRow(ListItem):
    def __init__(self, row: Any, **kwargs) -> None:
        super().__init__(**kwargs)
        self.row = row

    def compose(self):
        row = self.row
        head = Text()
        head.append(f"{_slug(row.slug):<38}", style="" if row.survived else theme.FAINT)
        if row.survived:
            head.append("survived screening", style=theme.verdict_colour(row.verdict))
        else:
            head.append(cut_reason(row.category), style=theme.FAINT)
        yield Line(head)

        detail = Text("  ")
        if row.language:
            detail.append(f"{row.language}  ", style=theme.FAINT)
        if row.stars:
            detail.append(f"{row.stars:,}★  ", style=theme.FAINT)
        if row.description:
            detail.append(row.description[:70], style=theme.FAINT)
        yield Line(detail)


def _slug(slug: str, width: int = 37) -> str:
    if len(slug) <= width:
        return slug
    owner, sep, name = slug.partition("/")
    if not sep:
        return slug[: width - 1] + "…"
    if sep and len(name) + 2 <= width:
        return f"…/{name}"
    return "…/" + name[: width - 3] + "…"


class CandidateList(KeepsHighlightVisible, ListView):
    def __init__(self, rows: list | None = None, **kwargs) -> None:
        rows = list(rows or [])
        super().__init__(*[CandidateRow(r) for r in rows], **kwargs)
        self.rows = rows

    def add(self, row: Any) -> CandidateRow:
        """Append one candidate that has just been screened.

        A live sweep reads a page of pull-request threads per candidate, so the
        list is built a row at a time rather than handed over complete. The
        widget's own `rows` is kept in step with what is on screen; a count
        taken from a list that disagrees with the display is a count that lies.
        """
        item = CandidateRow(row)
        self.rows.append(row)
        self.append(item)
        return item

    @property
    def selected(self) -> Any | None:
        return getattr(self.highlighted_child, "row", None)
