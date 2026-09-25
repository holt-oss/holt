"""The shared output shape.

The baseline solution and the full pipeline must produce the same thing, or the
comparison is not the same task. Both emit an Assessment; only the method of
arriving at one differs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Verdict(str, Enum):
    """Deliberately three-valued.

    A repository nobody has tried to contribute to is not the same as one that
    turns contributors away, and flattening them would hide the distinction the
    whole project is about. Saying so is a valid answer, not a failure.
    """

    VIABLE = "viable"
    NOT_VIABLE = "not_viable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


# The verdict word alone tells a reader almost nothing. These say what it means
# for the decision they are actually making.
VERDICT_HEADLINES = {
    Verdict.VIABLE: "Worth your time",
    Verdict.NOT_VIABLE: "Not worth your time",
    Verdict.INSUFFICIENT_EVIDENCE: "Not enough evidence to say",
}


def evidence_url(evidence_id: str) -> str:
    """The github.com page an evidence id points at, or "" if it names none.

    Ids look like `pr:owner/name#123:opened` or `issue:owner/name#45:closed`;
    anything else that names a repository (`repo:owner/name:meta`, a README)
    links to the repository itself. Derived from the id rather than looked up,
    so a report can be made clickable without the records that back it.
    """
    kind, _, rest = (evidence_id or "").partition(":")
    slug, hashed, tail = rest.partition("#")
    slug = slug.split(":", 1)[0].strip("/")
    if slug.count("/") != 1 or not all(slug.split("/")):
        return ""
    base = f"https://github.com/{slug}"
    number = "".join(c for c in tail.split(":", 1)[0] if c.isdigit()) if hashed else ""
    if not number:
        return base
    return f"{base}/{'pull' if kind == 'pr' else 'issues'}/{number}"


def evidence_label(evidence_id: str) -> str:
    """`pull request #123`, `issue #45`, or the repository name."""
    kind, _, rest = (evidence_id or "").partition(":")
    _, hashed, tail = rest.partition("#")
    number = "".join(c for c in tail.split(":", 1)[0] if c.isdigit()) if hashed else ""
    if number:
        return f"{'pull request' if kind == 'pr' else 'issue'} #{number}"
    return rest.split(":", 1)[0] or evidence_id


def cite(evidence_id: str) -> str:
    """An evidence id as a Markdown link a reader can click."""
    url = evidence_url(evidence_id)
    return f"[{evidence_label(evidence_id)}]({url})" if url else f"`{evidence_id}`"


@dataclass(frozen=True, slots=True)
class Claim:
    """A statement with the evidence id that backs it.

    Stage D drops any claim whose id does not resolve. A claim without a
    resolvable id never reaches the reader.
    """

    text: str
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class EntryPoint:
    """One suggested place to start, with the issue it points at.

    Carried separately from `Claim` because it is a *suggestion* rather than a
    statement of fact, and the two must not be rendered as if they had the same
    standing. Claims are verified against evidence; this is a ranking whose
    measured precision is printed next to it.
    """

    evidence_id: str
    first_step: str
    why: str = ""


@dataclass(slots=True)
class Assessment:
    repo: str
    verdict: Verdict
    summary: str
    claims: list[Claim] = field(default_factory=list)
    method: str = "holt"
    replayed: bool = False
    entry_points: list[EntryPoint] = field(default_factory=list)
    # Added, never replacing: `summary` still holds the prose. A reader deciding
    # where to spend a week needs the answer before the reasoning, and the rules
    # are printed because "which rule fired" is a question a chat answer cannot
    # be asked.
    bottom_line: str = ""
    limits: str = ""
    rules: list[str] = field(default_factory=list)
    contributor_days: int = 7
    # Rendered markdown lines from `holt.agent.landing`. Arithmetic over the file
    # lists we already crawl; the model never sees or writes this section.
    landing: list[str] = field(default_factory=list)
    # The date evidence was cut at. Stated in the output because a reader cannot
    # otherwise tell a quiet repository from one whose recent months were excluded.
    as_of: datetime | None = None
    # How many claims were removed before the reader saw them, by either check
    # in Stage D. Carried so the report can tell two situations apart that look
    # identical on the page: a run that found nothing to say, and a run whose
    # every statement was thrown out. `psf/requests` was the second one, and it
    # read like the first.
    dropped_claims: int = 0
    # The models that actually answered, in first-use order. Printed because the
    # model-written sections degrade with the model behind them while the counts
    # and the verdict do not, and a report that does not name its model leaves a
    # reader unable to tell those two halves apart. On a replay these are the ids
    # from the recording.
    models: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"# {self.repo}", ""]
        if self.replayed:
            lines += [
                "> Replaying recorded model output. No model was called for this run.",
                "",
            ]
        budget = f"for a contributor with {self.contributor_days} day"
        budget += "" if self.contributor_days == 1 else "s"
        lines += [f"**{VERDICT_HEADLINES[self.verdict]}** — {budget}.", ""]
        if self.as_of:
            lines += [f"*Evidence up to {self.as_of.date().isoformat()}.*", ""]
        if not self.claims and self.dropped_claims:
            # Above the prose, not below it. A reader who is told at the bottom
            # of the page that nothing on it was backed has already read it.
            lines += [
                f"> **No claim in this report survived verification.** All "
                f"{self.dropped_claims} were dropped: the evidence cited did not "
                "resolve, or the thread did not say what the claim said. The "
                "verdict and the counts below are computed without a model and "
                "still stand; nothing written in prose here is backed by a "
                "record you can check.",
                "",
            ]
        if self.bottom_line:
            lines += [self.bottom_line, ""]
        if self.summary:
            lines += ["## What the evidence shows", "", self.summary, ""]
        if self.rules:
            # The deterministic part, shown rather than described. `verdict.py`
            # decided this and the prose above could not have changed it.
            lines += ["## What decided it", ""]
            lines += [f"- {rule}" for rule in self.rules]
            lines.append("")
        if self.limits:
            lines += ["## What could not be determined", "", self.limits, ""]
        if self.landing:
            lines += self.landing + [""]
        if self.claims:
            lines += ["## Evidence", ""]
            for claim in self.claims:
                where = f" — {cite(claim.evidence_id)}" if claim.evidence_id else ""
                lines.append(f"- {claim.text}{where}")
        if self.entry_points:
            # The disclaimer is emitted by the renderer, not by the caller, so
            # there is no code path that prints a ranking without the number that
            # says how well it works. A test holds this.
            from holt.agent.entry import DISCLAIMER

            lines += ["", "## Where to start", "", DISCLAIMER, ""]
            for point in self.entry_points:
                lines.append(f"- **{point.first_step}** — {cite(point.evidence_id)}")
                if point.why:
                    lines.append(f"  {point.why}")
        lines += ["", f"*{self.method}*"]
        if self.models:
            lines += [f"*Model output from {', '.join(self.models)}.*"]
        return "\n".join(lines).rstrip() + "\n"

    def to_dict(self, stats: dict | None = None, mode: str = "") -> dict:
        """The report as JSON, shaped like the Report object in `API.md`.

        Fields the command line cannot know (cost, a server's generated time
        zone conventions) are filled as best it can; `stats` comes from the
        run's signals, which the assessment itself does not carry.
        """
        from datetime import UTC, datetime

        from holt.agent.verdict import headline

        return {
            "repo": self.repo,
            "mode": mode or ("ai" if self.models else "rules"),
            "days": self.contributor_days,
            "verdict": self.verdict.value,
            "headline": headline(self.verdict),
            "bottom_line": self.bottom_line or None,
            "summary": self.summary or None,
            "stats": stats,
            "decided_by": list(self.rules),
            "unknowns": [self.limits] if self.limits else [],
            "evidence": [
                {"id": c.evidence_id, "url": evidence_url(c.evidence_id or ""),
                 "text": c.text}
                for c in self.claims
            ],
            "entry_points": [
                {"id": p.evidence_id, "url": evidence_url(p.evidence_id),
                 "first_step": p.first_step, "why": p.why}
                for p in self.entry_points
            ],
            "evidence_until": self.as_of.isoformat() if self.as_of else None,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "models": list(self.models),
            "dropped_claims": self.dropped_claims,
        }
