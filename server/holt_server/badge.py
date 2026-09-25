"""The README badge: `Holt | newcomer-friendly`, shields.io style."""

from __future__ import annotations

from html import escape

LABEL = "Holt"

# Opaque fills on both halves, dark label, white text: readable on light and
# dark README backgrounds alike. Each colour holds white text at 4.5:1 or better.
LABEL_COLOR = "#555"
MESSAGES = {
    "viable": ("newcomer-friendly", "#1a7f37"),
    "not_viable": ("not newcomer-friendly", "#bc4c00"),
    "insufficient_evidence": ("not enough evidence", "#57606a"),
    None: ("not checked yet", "#57606a"),
}

# Verdana 11px advance widths, roughly. Enough to size a badge; shields.io does
# the same with a measured table.
_NARROW = set("fijlrt1 .,:;'!|()-")
_WIDE = set("mwMW@%")


def text_width(text: str) -> int:
    width = 0.0
    for ch in text:
        if ch in _NARROW:
            width += 4.0
        elif ch in _WIDE:
            width += 10.0
        elif ch.isupper() or ch.isdigit():
            width += 7.5
        else:
            width += 6.6
    return int(round(width))


def render(verdict: str | None, link: str) -> str:
    message, color = MESSAGES.get(verdict, MESSAGES[None])
    lw = text_width(LABEL) + 12
    mw = text_width(message) + 12
    total = lw + mw
    title = escape(f"{LABEL}: {message}")
    link = escape(link, quote=True)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total}" height="20" role="img" aria-label="{title}">
<title>{title}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
<a xlink:href="{link}" href="{link}" target="_blank">
<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="{LABEL_COLOR}"/><rect x="{lw}" width="{mw}" height="20" fill="{color}"/><rect width="{total}" height="20" fill="url(#s)"/></g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{LABEL}</text><text x="{lw / 2:.1f}" y="14">{LABEL}</text>
<text x="{lw + mw / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{escape(message)}</text><text x="{lw + mw / 2:.1f}" y="14">{escape(message)}</text>
</g>
</a>
</svg>
"""
