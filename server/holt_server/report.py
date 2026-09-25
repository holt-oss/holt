"""Assessment + Trace -> the Report object in API.md.

The engine's `Assessment` is shaped for a terminal: rendered Markdown lines for
the landing section, claims flattened to text. This rebuilds what the web needs
from the same sources: landing from the records the run actually read (the same
`landing.compute` the engine renders from), and evidence URLs from those
records, so every item links to GitHub.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from holt.agent import landing as landing_mod
from holt.agent.pipeline import MODEL_NOTE_LABEL
from holt.agent.signals import Signals, Thread, build_threads, newcomer_threads
from holt.agent.verdict import headline
from holt.report import Assessment
from holt.types import EvidenceRecord

RULES_ONLY_UNKNOWN = (
    "No AI read the conversations for this report, so it doesn't say how "
    "maintainers talk to newcomers or what kind of project this is. The verdict "
    "and the numbers are counted straight from GitHub and don't need an AI."
)
NO_OUTSIDERS_UNKNOWN = (
    "We found no pull requests from first-time contributors in the period we "
    "read, so there was nothing to count."
)
ALL_DROPPED_UNKNOWN = (
    "Every statement the AI wrote was removed because the evidence didn't back "
    "it up. The verdict and the numbers don't depend on the AI and still stand."
)

_OUTCOME = re.compile(r"^(?P<outcome>[^—“]+?) — “(?P<quote>.*)”$", re.S)
_NOTHING = re.compile(r"^(?P<outcome>.+), nothing said$", re.S)
# `field words: value`, optionally `(AI's reading, not a quote: note)`.
_FIELD = re.compile(
    r"^(?P<field>[a-z][a-z ]*?): (?P<value>.*?)"
    rf"(?: \({re.escape(MODEL_NOTE_LABEL)}: (?P<note>.*)\))?$", re.S)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def url_for(evidence_id: str, records: dict[str, EvidenceRecord]) -> str | None:
    record = records.get(evidence_id)
    if record is not None and record.url:
        return record.url
    # Built from the id when the record is not at hand. The id grammar is
    # `pr:owner/repo#123:...`, `issue:owner/repo#123:...`, `repo:owner/repo:...`.
    kind, _, rest = evidence_id.partition(":")
    slug = rest.split("#", 1)[0].split(":", 1)[0]
    if "/" not in slug:
        return None
    base = f"https://github.com/{slug}"
    number = re.match(r"[^#]*#(\d+)", rest)
    if kind == "pr" and number:
        return f"{base}/pull/{number.group(1)}"
    if kind == "issue" and number:
        return f"{base}/issues/{number.group(1)}"
    return base


def evidence_item(text: str, evidence_id: str | None,
                  records: dict[str, EvidenceRecord]) -> dict[str, Any] | None:
    if not evidence_id:
        return None
    url = url_for(evidence_id, records)
    if not url:
        return None  # API.md: every evidence item must be clickable.
    kind, value, body, quote = "claim", None, text, None
    if m := _OUTCOME.match(text):
        kind, value, quote = "outcome", m["outcome"].strip(), m["quote"].strip() or None
        body = value.capitalize()
    elif m := _NOTHING.match(text):
        kind, value = "outcome", m["outcome"].strip()
        body = f"{value.capitalize()}, with nothing said"
    elif m := _FIELD.match(text):
        kind, value = m["field"].strip().replace(" ", "_"), m["value"].strip()
        body = (m["note"] or "").strip() or f"{m['field'].capitalize()}: {value}"
    if kind == "outcome" and value:
        value = value.replace(" ", "_")
    return {"id": evidence_id, "url": url, "kind": kind, "value": value,
            "text": body, "quote": quote}


RULES_EVIDENCE_EACH = 4


def counted_examples(threads: dict[str, Thread],
                     records: dict[str, EvidenceRecord]) -> list[dict[str, Any]]:
    """Recent first-timer pull requests behind the counts, for a report with no AI.

    Without a model the engine cites nothing, which leaves a beginner with
    numbers and no way to look for themselves. These are picked by arithmetic
    only (newest merged, newest with no reply), so they say nothing the counts
    do not already say; they just make the counts clickable.
    """
    outsiders = sorted(newcomer_threads(threads), key=lambda t: t.opened_at, reverse=True)
    picks = [("merged", t) for t in outsiders if t.merged][:RULES_EVIDENCE_EACH]
    picks += [("no_reply", t) for t in outsiders
              if not t.merged and not t.engaged][:RULES_EVIDENCE_EACH]
    out = []
    for value, t in picks:
        evidence_id = f"{t.key}:opened"
        url = url_for(evidence_id, records)
        if not url:
            continue
        title = (records.get(evidence_id).payload.get("title") or "").strip() \
            if evidence_id in records else ""
        what = "was merged" if value == "merged" else "had no reply from anyone when we looked"
        text = f"First-time contributor's pull request #{t.number} {what}"
        out.append({"id": evidence_id, "url": url, "kind": "outsider_pr", "value": value,
                    "text": text + (f": “{title}”" if title else ""), "quote": None})
    return out


def split_limits(limits: str) -> list[str]:
    out = []
    for line in (limits or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if line:
            out.append(line)
    return out


def stats(signals: Signals) -> dict[str, Any]:
    return {
        "outsider_attempts": signals.outsider_threads,
        "outsider_merged": signals.outsider_merged,
        "distinct_outsiders": signals.distinct_outsider_authors,
        "first_time_merged_authors": signals.distinct_merged_authors,
        "no_reply": signals.outsider_ignored,
        "median_first_response_hours": signals.median_first_response_hours,
        "bot_share": round(signals.bot_share, 3),
    }


def build(
    *,
    repo: str,
    mode: str,
    assessment: Assessment,
    signals: Signals,
    records: Iterable[EvidenceRecord],
    cost: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    by_id = {r.evidence_id: r for r in records}
    threads = build_threads(by_id.values())
    where = landing_mod.compute(threads)

    evidence = []
    for claim in assessment.claims:
        item = evidence_item(claim.text, claim.evidence_id, by_id)
        if item is not None:
            evidence.append(item)
    if mode == "rules":
        evidence += counted_examples(threads, by_id)

    unknowns: list[str] = []
    if mode == "ai":
        unknowns += split_limits(assessment.limits)
        if not assessment.claims and assessment.dropped_claims:
            unknowns.insert(0, ALL_DROPPED_UNKNOWN)
    else:
        unknowns.append(RULES_ONLY_UNKNOWN)
    if not signals.outsider_threads:
        unknowns.append(NO_OUTSIDERS_UNKNOWN)

    return {
        "repo": repo,
        "mode": mode,
        "days": assessment.contributor_days,
        "verdict": assessment.verdict.value,
        "headline": headline(assessment.verdict),
        "summary": (assessment.summary or None) if mode == "ai" else None,
        "stats": stats(signals),
        "decided_by": [str(r) for r in assessment.rules],
        "unknowns": unknowns,
        "landing": [{"path": a.path, "merged": a.landed, "attempted": a.attempted}
                    for a in where.landed],
        "never_landed": [{"path": a.path, "attempted": a.attempted} for a in where.never],
        "evidence": evidence,
        "evidence_until": iso(assessment.as_of),
        "generated_at": iso(generated_at or datetime.now(UTC)),
        "cost": cost if mode == "ai" else None,
    }
