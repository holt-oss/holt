"""A -> B -> C -> D -> verdict -> E.

The ordering that matters: the verdict is computed *before* narration and handed
to Stage E as an input it cannot alter. If the report and verdict.py could
disagree, the determinism claim would be worth nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from holt.agent import landing, stages
from holt.agent.findings import Finding, Findings
from holt.agent.signals import MIN_AGE_HOURS, Signals, build_threads, compute
from holt.agent.verdict import classify as decide
from holt.agent.verdict import contested_kind, hours_phrase, headline, legacy_trace
from holt.agent.verify import check_quotes, verify
from holt.evidence.provider import EvidenceProvider
from holt.model import ModelClient
from holt.report import Assessment, Claim

MAX_CLAIM_CHARS = 240
MAX_QUOTE_CHARS = 180

# A model's rationale is its reading of the evidence, not the evidence. Where
# one is shown next to a verified citation it says so, so a reader cannot take
# the model's words for something the record says.
MODEL_NOTE_LABEL = "AI's reading, not a quote"

# Assessment fields written by a model in the full pipeline. Everything else --
# the verdict, the rules, the counts, the landing table, the citations -- is
# computed. Carried on the Trace so a front end can label these as AI-written.
MODEL_WRITTEN_FIELDS = ("summary", "bottom_line", "limits")

# Called with a plain-English stage and overall progress from 0 to 1. The web
# server streams these to the browser as they happen.
Progress = Callable[[str, float], None]


def _reporter(progress: Progress | None) -> Progress:
    """Never let a broken progress callback break an analysis."""
    if progress is None:
        return lambda stage, fraction: None

    def report(stage: str, fraction: float) -> None:
        try:
            progress(stage, max(0.0, min(1.0, fraction)))
        except Exception:  # noqa: BLE001 - a display hook must not fail the run
            pass

    return report


def _min_age(provider: EvidenceProvider, min_age_hours: float | None) -> float:
    """The "too new to judge" window: on for live reads, off for frozen captures."""
    if min_age_hours is not None:
        return min_age_hours
    return MIN_AGE_HOURS if getattr(provider, "judges_recency", True) else 0.0


def clip(text: str, limit: int) -> str:
    """Cut on a word boundary. Cutting mid-word reads as a bug, because it is one."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = max(head.rfind(" "), head.rfind(". "))
    return (head[:cut] if cut > limit // 2 else head).rstrip(" ,;:.") + "…"


@dataclass(slots=True)
class Trace:
    """What happened, for the demo and the trajectory record."""

    signals: Signals
    before_verification: int = 0
    after_verification: int = 0
    dropped: list[Finding] = field(default_factory=list)
    # Findings whose id resolved but whose quotation is not in the record.
    invented: list[Finding] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    # Which Assessment fields a model wrote; empty when no model ran.
    model_written: tuple[str, ...] = ()


def analyze(
    repo: str,
    provider: EvidenceProvider,
    model: ModelClient | None,
    contributor_days: int = 7,
    as_of: datetime | None = None,
    progress: Progress | None = None,
    min_age_hours: float | None = None,
) -> tuple[Assessment, Trace]:
    """The full assessment. The web server and the CLI both call this.

    `progress`, if given, is called with a plain-English stage and a fraction
    from 0 to 1 as each stage starts, and with ("Done", 1.0) at the end.

    `min_age_hours` is how new an unanswered pull request can be before its
    silence counts as being ignored, measured back from `as_of` (or now). By
    default it applies to live evidence and not to committed fixtures, whose
    published numbers were computed without it.
    """
    if model is None:
        return analyze_without_model(
            repo, provider, contributor_days, as_of,
            progress=progress, min_age_hours=min_age_hours,
        )
    report = _reporter(progress)
    report("Fetching pull requests", 0.0)
    records = provider.fetch(repo)
    report("Counting replies and merges", 0.3)
    threads = build_threads(records)
    signals = compute(
        threads, as_of or datetime.now(UTC), _min_age(provider, min_age_hours)
    )

    findings = Findings()
    report("Working out what kind of project this is", 0.35)
    stages.classify(repo, records, threads, model, findings)
    report("Reading the contributing guide", 0.45)
    stages.assess_opportunity(repo, records, model, findings)
    report("Reading threads", 0.55)
    stages.read_outcomes(repo, threads, model, findings)

    report("Checking evidence", 0.75)
    before = len(findings)
    findings, dropped = verify(findings, provider)

    # `repo_kind` is the only model-derived field that can decide the answer by
    # itself, and Stage D cannot check it -- an id resolving says nothing about
    # whether a classification is true. Where the evidence contradicts the
    # reason the kind rule would give, the field is dropped before it decides
    # anything and the disagreement is printed. See eval/PREREGISTRATION-4.md.
    meta = next((r for r in records if r.evidence_id.endswith(":meta")), None)
    contested = contested_kind(findings, signals, meta.payload if meta else None)
    if contested:
        findings.drop("repo_kind")

    verdict, rules = decide(findings, signals, contributor_days)
    if contested:
        rules.insert(0, contested)
    # The narration prompt is deliberately held to the signal fields that existed
    # when the trajectories were recorded. New signals reach the *verdict*
    # immediately but only reach the prose on the next re-record, so adding one
    # does not invalidate every committed trajectory and break replay for a judge.
    # When a new signal changes the outcome it still reaches the narrator, via
    # the rule trace.
    narrated_signals = {
        k: v for k, v in signals.as_dict().items()
        if k not in ("reviewed_share", "merge_rate", "merged_files_median",
                     "merged_dirs_median", "merged_with_files")
    }
    # Likewise the rule trace: the reader sees plain sentences, and the narrator
    # is handed the wording the recordings were made with.
    narrated_signals = {
        k: v for k, v in narrated_signals.items()
        if k not in ("outsider_awaiting_reply", "outsider_answered")
    }
    report("Writing the report", 0.85)
    narrated = stages.narrate(
        repo, verdict.value, legacy_trace(rules), findings, narrated_signals, model
    )

    # The evidence list is built from verified findings, not written by the
    # model. Stage E supplies prose; it cannot introduce a citation.
    #
    # The quote check runs here rather than inside Stage D on purpose. A claim
    # whose id does not resolve is worthless to everyone, narrator included, so
    # `verify` removes it before anything else runs. A claim whose id resolves
    # but whose words are not in the record is a different failure: the thread
    # is real and the outcome may well be right, and what must not reach the
    # reader is the quotation. Filtering the claim list is exactly that, and it
    # leaves the narration prompt byte-identical, so every committed trajectory
    # still replays -- a guarantee that would otherwise cost a re-record of the
    # frozen benchmark to buy.
    quoting, invented = check_quotes(findings, records)
    claims: list[Claim] = []
    for item in quoting:
        if item.field == "thread_outcome":
            outcome = item.value["outcome"].replace("_", " ")
            quote = (item.value.get("quote") or "").strip()
            # An empty quote used to render as a pair of quotation marks with
            # nothing between them, which reads as a bug because it is one.
            text = (f"{outcome} — “{clip(quote, MAX_QUOTE_CHARS)}”" if quote
                    else f"{outcome}, nothing said")
        else:
            text = f"{item.field.replace('_', ' ')}: {item.value}" + (
                f" ({MODEL_NOTE_LABEL}: {clip(item.note, MAX_CLAIM_CHARS)})"
                if item.note else "")
        claims.append(Claim(text=text, evidence_id=item.evidence_ids[0]))

    assessment = Assessment(
        repo=repo,
        verdict=verdict,
        summary=narrated["what_the_evidence_shows"],
        bottom_line=narrated["bottom_line"],
        limits=narrated["what_could_not_be_determined"],
        rules=list(rules),
        contributor_days=contributor_days,
        as_of=as_of,
        landing=landing.render(landing.compute(threads)),
        claims=claims,
        method="holt (A classify, B opportunity, C outcomes, D verify, deterministic verdict, E narrate)",
        replayed=model.replayed,
        models=list(model.usage.models),
        dropped_claims=len(dropped) + len(invented),
    )
    report("Done", 1.0)
    return assessment, Trace(
        signals=signals,
        before_verification=before,
        after_verification=len(findings),
        dropped=dropped,
        invented=invented,
        rules=rules,
        model_written=MODEL_WRITTEN_FIELDS,
    )


# --- degraded mode -----------------------------------------------------------
#
# The project measured its own model stages at +0.01 MCC over the arithmetic
# (Iteration 22). A finding that large about your own architecture should change
# the architecture, not just the write-up: if the rules decide the verdict, the
# verdict must be obtainable without a model, and the reader must be told what
# they lost. That is this function.
#
# It is not a second implementation of the verdict. It calls the same `decide`
# on the same `Signals`, so the two modes cannot disagree about a repository
# they both have findings for -- a test asserts exactly that over the pool.
# What it does not do is write: Stages A, B, C and E never run, so there are no
# thread quotes, no narration, and no `repo_kind`. That absence is the point of
# `eval/evidence_integrity.py`'s yield column, and it is stated on the report
# rather than left for the reader to notice.

NO_MODEL_METHOD = (
    "holt --no-model (deterministic verdict from arithmetic; "
    "stages A, B, C and E did not run)"
)


def analyze_without_model(
    repo: str,
    provider: EvidenceProvider,
    contributor_days: int = 7,
    as_of: datetime | None = None,
    progress: Progress | None = None,
    min_age_hours: float | None = None,
) -> tuple[Assessment, Trace]:
    """The verdict, with no model call anywhere and the cost of that printed.

    `progress` and `min_age_hours` behave as in `analyze`.
    """
    report = _reporter(progress)
    report("Fetching pull requests", 0.0)
    records = provider.fetch(repo)
    report("Counting replies and merges", 0.6)
    threads = build_threads(records)
    signals = compute(
        threads, as_of or datetime.now(UTC), _min_age(provider, min_age_hours)
    )

    findings = Findings()
    # `is_archived` is a structured GitHub field. Stage A was asking a model to
    # read a boolean the provider already had, which is the clearest single
    # illustration of why the model stages measured +0.01: some of what they
    # were doing did not need a model at all. Here it is taken from the record
    # and cited to it.
    meta = next((r for r in records if r.evidence_id.endswith(":meta")), None)
    if meta is not None and meta.payload.get("is_archived"):
        findings.add("is_archived", True, (meta.evidence_id,),
                     "GitHub reports this repository as archived")

    report("Applying the rules", 0.9)
    verdict, rules = decide(findings, signals, contributor_days)

    s = signals.as_dict()
    if signals.outsider_threads:
        summary = (
            f"{s['outsider_merged']} of {s['outsider_threads']} pull requests from "
            f"newcomers were merged, by {s['distinct_merged_authors']} of the "
            f"{s['distinct_outsider_authors']} people who tried."
        )
        if s["median_first_response_hours"] is not None:
            summary += (
                f" Of the {s['outsider_answered']} that got a reply, half heard "
                f"back within {hours_phrase(s['median_first_response_hours'])}."
            )
        summary += f" {s['outsider_ignored']} got no reply at all."
        if s["outsider_awaiting_reply"]:
            summary += (
                f" {s['outsider_awaiting_reply']} are too new to have had a reply "
                "yet and weren't counted as ignored."
            )
        summary += " These are counts from the pull request history, not an AI's judgement."
    else:
        summary = (
            "Nobody from outside the project opened a pull request in the period "
            "we looked at, so there was nothing to count."
        )
    deciding = next((r for r in rules if getattr(r, "code", "") != "awaiting_reply"),
                    rules[0] if rules else "")

    return Assessment(
        repo=repo,
        verdict=verdict,
        summary=summary,
        bottom_line=f"{headline(verdict)}. " + deciding,
        limits=(
            "No model ran. This answer comes from counting the pull request "
            "history, so it can't tell you what specific threads said, who was "
            "welcoming, or what kind of project this is, and it cites no specific "
            "threads, where a full AI report cites about 12. In our testing on "
            "repositories it hadn't seen, counting alone predicted how newcomers "
            "would fare a little less well than the full report (a score of 0.55 "
            "against 0.63, where 1 is perfect). Ask for the AI report for "
            "something you can check thread by thread."
        ),
        rules=list(rules),
        contributor_days=contributor_days,
        as_of=as_of,
        landing=landing.render(landing.compute(threads)),
        claims=[
            Claim(text=f"{i.field.replace('_', ' ')}: {i.value}", evidence_id=i.evidence_ids[0])
            for i in findings
        ],
        method=NO_MODEL_METHOD,
        replayed=False,
        models=[],
        dropped_claims=0,
    ), _done(report, Trace(signals=signals, rules=rules))


def _done(report: Progress, trace: Trace) -> Trace:
    report("Done", 1.0)
    return trace
