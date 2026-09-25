"""Every colour in the interface, and what each one is for.

Colour is used to mean something or it is not used. Three jobs:

1. **verdict state** — viable, not viable, insufficient evidence
2. **evidence resolution** — an id that resolves against the provider, or one
   that does not
3. **Stage D drops** — the one place red appears

Everything else is the terminal's own foreground and two greys. There is no
background colour anywhere in the stylesheet: the app sits on whatever ground
the user's terminal already has, which is both the restrained choice and the
reason it reads correctly on a light and a dark profile without a theme switch.

`not_viable` is clay rather than red on purpose. It is a finding about a
repository, not a failure of the tool, and colouring it like an error would
misreport it. `insufficient_evidence` is grey on purpose too: an absence of
evidence has not earned a colour.

The one consequence of having no background colour: **a list cannot show where
the keyboard is by lighting a row.** Textual's own idiom for that is a `$boost`
background, and boost is a translucent overlay — over `transparent` it
composites to nothing, so every list in the app rendered with no visible
selection and had to be driven with a mouse. Selection is therefore a rail in
the margin, in `CITE`, the same colour and the same shape as the rail that marks
a focused input. The column is reserved on every row so moving the selection
does not shift the text sideways.

Both `.-highlight` and `.--highlight` are listed on every one of those rules.
Textual renamed the class between versions this project supports, and a
stylesheet that names only one of them silently stops highlighting anything —
which is not a failure any test of *text* can see.
"""

from __future__ import annotations

# ─── tokens ─────────────────────────────────────────────────────────────────

DIM = "#8a8a8a"  # labels, chrome, secondary prose
FAINT = "#585858"  # counts, timings, read only if you look for them
RULE = "#444444"  # hairlines
RAIL = "#767676"  # the measured-result rail: quiet, but meant to be seen

VIABLE = "#5faf87"
NOT_VIABLE = "#d7875f"
INSUFFICIENT = "#8a8a8a"
DROP = "#af5f5f"
CITE = "#5fafaf"

#: Verdicts are looked up, never matched exhaustively. `holt.report.Verdict`
#: owns the enum; a member added there renders in the neutral tone instead of
#: raising, so the TUI never has to be edited in lockstep with the engine.
VERDICT_COLOURS: dict[str, str] = {
    "viable": VIABLE,
    "not_viable": NOT_VIABLE,
    "insufficient_evidence": INSUFFICIENT,
}
VERDICT_FALLBACK = DIM


def verdict_colour(value: str) -> str:
    return VERDICT_COLOURS.get(value, VERDICT_FALLBACK)


def verdict_label(value: str) -> str:
    """`not_viable` reads as "not viable". Spelled out, never abbreviated."""
    return value.replace("_", " ")


CSS = f"""
Screen {{
    background: transparent;
    color: $foreground;
}}

/* chrome ------------------------------------------------------------------ */

#chrome {{
    height: 1;
    color: {DIM};
    padding: 0 1;
}}
#chrome-left {{
    width: 1fr;
}}
#chrome-right {{
    width: auto;
    color: {FAINT};
    text-align: right;
}}
.rule {{
    height: 1;
    color: {RULE};
}}
Footer {{
    background: transparent;
    color: {FAINT};
}}
Footer > .footer--key {{
    background: transparent;
    color: {DIM};
}}
Footer > .footer--description {{
    background: transparent;
    color: {FAINT};
}}

/* stages ------------------------------------------------------------------ */

StageList {{
    /* `auto`, not the container default of `1fr`. As a fraction it expanded to
       fill the screen and left a block of dead space between the last stage and
       the stream of findings. */
    height: auto;
    padding: 0 0 1 0;
}}
#stream {{
    height: 1fr;
    scrollbar-size: 1 1;
}}
StageRow {{
    height: 1;
    padding: 0 1;
}}
.stage-mark {{ color: {FAINT}; width: 3; }}
.stage-name {{ color: {DIM}; width: 16; }}
.stage-pending {{ color: {FAINT}; }}
.stage-running {{ color: {DIM}; }}

/* findings as they stream -------------------------------------------------- */

.finding {{
    padding: 0 1 0 6;
    height: auto;
}}
.finding-note {{ color: {FAINT}; }}

/* the drop ---------------------------------------------------------------- */

DroppedFinding {{
    height: auto;
    padding: 1 1 1 6;
}}
.drop-mark {{ color: {DROP}; }}
.drop-reason {{ color: {FAINT}; padding-left: 2; }}
.drop-id {{ color: {DROP}; text-style: strike; }}

/* evidence ---------------------------------------------------------------- */

.cite {{ color: {CITE}; text-style: underline; }}
.cite-broken {{ color: {DROP}; text-style: strike; }}

EvidenceDetail {{
    height: auto;
    padding: 0 1;
}}
.record-meta {{ color: {FAINT}; }}
.record-key {{ color: {DIM}; width: 17; }}

/* claims ------------------------------------------------------------------ */

ClaimList {{
    /* `auto`, not `1fr`. Inside the scrolling page, a fractional height
       resolves against whatever space a long summary has left over, which on a
       verbose repository collapses the whole list to a single row. The page
       scrolls; the list should be as tall as it has claims. */
    height: auto;
    background: transparent;
    border: none;
    scrollbar-size: 1 1;
}}
ClaimList > ListItem {{
    background: transparent;
    padding: 0 1;
    border-left: outer transparent;
}}
ClaimList > ListItem.-highlight, ClaimList > ListItem.--highlight {{
    border-left: outer {CITE};
}}

/* verdict ----------------------------------------------------------------- */

#verdict {{
    height: auto;
    padding: 1 1 0 1;
    text-style: bold;
}}
#verdict-budget {{
    height: auto;
    padding: 0 1 1 1;
}}
#bottom-line {{
    height: auto;
    padding: 0 1 1 1;
}}
.prose {{
    height: auto;
    padding: 0 1 1 1;
}}
.rule-line {{
    height: auto;
    padding: 0 1 0 2;
}}
.landing-line {{
    height: auto;
    padding: 0 1 0 2;
}}
#report {{
    height: 1fr;
    scrollbar-size: 1 1;
}}

/* masthead ----------------------------------------------------------------- */

Masthead {{
    /* `auto`, not the widget default of `1fr`. As a fraction it filled the
       screen and pushed the input, the hint and the whole recent list off the
       bottom. */
    height: auto;
}}
#masthead {{
    height: auto;
    padding: 1 1 0 1;
}}
#cat {{
    width: 13;
    height: 1;
}}
.chrome-cat {{
    width: 12;
    height: 1;
}}
#masthead-text {{
    width: 1fr;
    height: auto;
}}
.masthead-name {{
    text-style: bold;
}}
.masthead-fact {{
    color: {FAINT};
}}

/* home --------------------------------------------------------------------- */

#home-body {{
    height: 1fr;
    padding: 0 1;
}}
#home-notice {{
    height: auto;
    /* No top padding: the input already carries a bottom margin, and both
       together left two blank lines between the box and its own hint. */
    padding: 0 1 0 2;
}}
#recent-scroll {{
    height: 1fr;
    scrollbar-size: 1 1;
}}
RecentList {{
    height: auto;
    background: transparent;
    border: none;
}}
RecentList > ListItem {{
    background: transparent;
    padding: 0 1;
    border-left: outer transparent;
}}
RecentList > ListItem.-highlight, RecentList > ListItem.--highlight {{
    border-left: outer {CITE};
}}

/* the measured result ------------------------------------------------------ */

MeasuredResult {{
    height: auto;
    padding: 0 1;
    border-left: outer {RAIL};
}}
.measured-lede {{ text-style: bold; }}
.measured-row {{ color: {DIM}; }}
.measured-row-ours {{ color: $foreground; }}
.measured-check {{ color: {DIM}; }}

/* reading order ------------------------------------------------------------ */

EntryPointRow {{
    height: auto;
    padding: 1 1 0 1;
}}
.entry-index {{ color: {FAINT}; width: 4; }}
.entry-why {{ color: {FAINT}; padding-left: 4; }}

/* discover, profile, what-next ---------------------------------------------- */

#models-body {{
    height: 1fr;
    padding: 0 1;
}}
#provider-scroll, #model-scroll {{
    height: auto;
    max-height: 12;
    scrollbar-size: 1 1;
}}
#providers, #models {{
    height: auto;
    background: transparent;
    border: none;
}}
#model-count {{
    height: auto;
    padding: 0 1 0 2;
}}
#providers > ListItem, #models > ListItem {{
    background: transparent;
    padding: 0 1;
    border-left: outer transparent;
}}
#providers > ListItem.-highlight, #models > ListItem.-highlight,
#providers > ListItem.--highlight, #models > ListItem.--highlight {{
    border-left: outer {CITE};
}}
#models-notice {{
    height: auto;
    padding: 1 1 0 2;
}}
#models-warning {{
    height: auto;
    padding: 1 1 0 2;
    border-left: outer {RAIL};
}}

#discover-body, #profile-body, #next-body {{
    height: 1fr;
    padding: 0 1;
}}
#candidate-scroll, #next-results {{
    height: 1fr;
    scrollbar-size: 1 1;
}}
CandidateList {{
    height: auto;
    background: transparent;
    border: none;
}}
CandidateList > ListItem {{
    background: transparent;
    padding: 0 1 1 1;
    border-left: outer transparent;
}}
CandidateList > ListItem.-highlight, CandidateList > ListItem.--highlight {{
    border-left: outer {CITE};
}}
#discover-hint {{
    height: auto;
    padding: 1 1 1 1;
}}
Input {{
    /* Every input in the app, marked by a rail rather than boxed in. The
       default border draws three lines around one line of text, which on a
       screen made of hairlines is the loudest thing on it. */
    background: transparent;
    border: none;
    border-left: outer {RULE};
    padding: 0 1;
    height: 1;
    margin: 0 0 1 0;
}}
Input:focus {{
    border-left: outer {CITE};
}}
.field-note {{
    color: {FAINT};
    padding: 0 1 0 2;
}}
#profile-notice, #next-notice {{
    height: auto;
    padding: 1 1 0 2;
}}
.next-row {{
    height: auto;
    padding: 0 1 1 1;
}}

.section-label {{
    color: {DIM};
    padding: 1 1 0 1;
}}
.empty {{
    color: {FAINT};
    padding: 1 1;
}}

/* A run in flight, in the list on home. */
.running-row {{ color: {DIM}; }}

/* The one modal: stopping a run, and quitting with runs still going. */
ConfirmScreen {{
    align: center middle;
}}
#confirm-box {{
    width: 64;
    height: auto;
    padding: 1 3;
    border: round {RULE};
    background: $surface;
}}
/* Explicit, because a `Static` inside an auto-width box measures as zero and
   the whole question renders as an empty frame. */
#confirm-question, #confirm-detail, #confirm-keys {{ width: 100%; }}
#confirm-question {{ color: {DIM}; }}
#confirm-detail {{ color: {FAINT}; padding: 1 0 0 0; }}
#confirm-keys {{ color: {FAINT}; padding: 1 0 0 0; }}

/* The first-run token prompt and the ? help overlay: the same boxed modal. */
TokenScreen, HelpScreen {{ align: center middle; }}
#token-box, #help-box {{
    width: 76;
    max-width: 100%;
    height: auto;
    max-height: 90%;
    padding: 1 3;
    border: round {RULE};
    background: $surface;
}}
#token-box Line, #help-box Line {{ width: 100%; }}
#token-input {{ margin: 1 0 0 0; }}
#token-error {{ color: {DROP}; }}

/* The command palette.
 *
 * Textual's own styling is a full-width panel between two heavy `hkey` bars,
 * with a magnifying-glass emoji floating above its input. Everything else in
 * holt is a narrow column between hairlines, so the palette is brought into
 * line: same width discipline, same rules, no box.
 *
 * A box is not available anyway. The results list is `overlay: screen`, so it
 * escapes any border drawn on the container and the frame would close above
 * the commands it is meant to contain. Hairlines above and below each part
 * read as one surface without needing to enclose anything. */
CommandPalette > Vertical {{
    margin-top: 4;
    width: 76;
    height: auto;
    /* Textual hides the container and shows only its children, so the panel
       has no background of its own and home reads through the gaps. */
    visibility: visible;
    background: $surface;
}}
CommandPalette #--input {{
    height: auto;
    border: none;
    border-top: solid {RULE};
    border-bottom: solid {RULE};
    background: $surface;
}}
CommandPalette #--input.--list-visible {{
    border-bottom: solid {RULE};
}}
/* The emoji. It sits on its own line, out of line with the text it labels,
   and the placeholder already says what the box is for. */
CommandPalette SearchIcon {{
    display: none;
}}
CommandPalette #--results {{
    background: $surface;
}}
CommandPalette CommandList {{
    background: $surface;
    border: none;
    border-bottom: solid {RULE};
    padding: 0 1;
    max-height: 22;
}}
/* The selection has to be visible while the *input* holds focus, which is the
   whole time the palette is open. Textual falls back to its blurred cursor
   tokens there, and blurred on this surface is no cursor at all — up and down
   moved something invisible. The focused tokens are used instead: they are the
   theme's own, so this stays right on a light terminal as well as a dark one. */
CommandPalette CommandList > .option-list--option-highlighted {{
    color: $block-cursor-foreground;
    background: $block-cursor-background;
    text-style: $block-cursor-text-style;
}}
CommandPalette > .command-palette--help-text {{
    color: {FAINT};
    text-style: none;
}}
CommandPalette > .command-palette--highlight {{
    color: {RAIL};
    text-style: bold;
}}
"""
