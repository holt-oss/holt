"""User-directed discovery: source candidates, screen them for free, analyse survivors.

The claim discipline is the whole point of this module:

* **We claim the filter.** Screening applies the same rules as `verdict.py` —
  rubber-stamp (validated out of sample: specificity 0.83 on a pool drawn after
  the rule was written), hostile, slow-response against the user's stated day
  budget, and the outsider-merge floor. On the trap repositories the rules
  reject 4 of 5 in every recorded run.
* **We do not claim the sourcing or the ordering.** Candidates come from GitHub
  repository search and the output says so. Rows come out in screening order.
* Screening runs at reduced crawl depth (the newest page of pull-request
  threads) so its numbers are noisier than the benchmark's; survivors are
  re-crawled at full depth before anything is asserted about them.

The structural fact that makes screening free: `verdict.py` needs exactly one
model-derived input, `repo_kind`. Every other rule is arithmetic over crawled
signals. So screening runs **no model at all**; the one thing it cannot do is
tell a registry from a software project, and the full analysis of the survivors
is where that gets caught.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from holt import model
from holt.agent import landing as landing_mod
from holt.agent.findings import Findings
from holt.agent.pipeline import analyze
from holt.agent.signals import Signals, build_threads, compute
from holt.agent.verdict import classify
from holt.evidence.fixtures import FixtureProvider, write_fixture
from holt.evidence.provider import EvidenceProvider
from holt.profile import CONTRIBUTION_AREAS, Profile
from holt.report import Verdict
from holt.types import EvidenceRecord, Window

DISCOVER_ROOT = Path("fixtures/discover")
DISCOVER_TRAJECTORIES = "discover"

# Screening reads one page of pull-request threads; the full analysis reads up
# to eight. Both numbers are printed, not implied.
SCREEN_PAGES = 1
FULL_PAGES = 8

# Sourcing recency: a repository nobody pushed to in this window has no fresh
# threads to screen. A sourcing choice, disclosed in the printed query.
RECENT_PUSH_DAYS = 60

CAT_ARCHIVED = "archived"
CAT_NO_LANDING = "nobody outside has landed work in"
CAT_SLOW = "replies too slow for the day budget"
CAT_RUBBER_STAMP = "work merged without review (the rubber-stamp rule)"
CAT_HOSTILE = "outsider attempts went unanswered"


@dataclass(slots=True)
class Candidate:
    slug: str
    description: str | None = None
    stars: int = 0
    language: str | None = None
    pushed_at: str | None = None
    #: Open issues carrying a beginner label, as counted by GitHub at search
    #: time. Orders candidates for screening; it never decides a verdict.
    good_first_issues: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"slug": self.slug, "description": self.description, "stars": self.stars,
                "language": self.language, "pushed_at": self.pushed_at,
                "good_first_issues": self.good_first_issues}


@dataclass(slots=True)
class Screened:
    candidate: Candidate
    verdict: Verdict
    trace: list[str]
    signals: Signals
    category: str | None  # None means the candidate survived


def build_queries(profile: Profile, as_of: datetime) -> list[str]:
    """One search query per language and per topic.

    GitHub ANDs repeated qualifiers: `language:a language:b` or `topic:a topic:b`
    in one query asks for a repository that is both, which matches almost
    nothing. A person who says "cli, web" means either, so each pair is its own
    query and `source` merges the results.
    """
    pushed = (as_of - timedelta(days=RECENT_PUSH_DAYS)).date().isoformat()
    tail = [f"pushed:>{pushed}", "archived:false", "fork:false", "stars:>=10"]
    languages = [f"language:{lang}" for lang in profile.languages] or [None]
    topics = [f"topic:{t}" for t in profile.topics] or [None]
    return [" ".join(q for q in (lang, topic, *tail) if q)
            for lang in languages for topic in topics]


def source(transport, profile: Profile, as_of: datetime, limit: int) -> tuple[list[Candidate], list[str]]:
    """Candidates from GitHub repository search. Sourcing only — no claim.

    Within each query, repositories with more open beginner-labelled issues are
    taken first: someone arriving here wants somewhere to start, and a
    repository with none gives them nothing to do even if it is welcoming.
    """
    queries = build_queries(profile, as_of)
    per_query = max(1, limit // len(queries))
    seen: set[str] = set()
    out: list[Candidate] = []
    for q in queries:
        found: list[Candidate] = []
        for node in transport.search_repositories(q, max_pages=(per_query // 25) + 1):
            slug = node["nameWithOwner"]
            if slug in seen or node.get("isArchived") or node.get("isFork"):
                continue
            seen.add(slug)
            found.append(Candidate(
                slug=slug,
                description=node.get("description"),
                stars=node.get("stargazerCount") or 0,
                language=((node.get("primaryLanguage") or {}).get("name")),
                pushed_at=node.get("pushedAt"),
                good_first_issues=((node.get("goodFirstIssues") or {})
                                   .get("totalCount") or 0),
            ))
        # Stable, so search order still breaks ties.
        found.sort(key=lambda c: -c.good_first_issues)
        out.extend(found[:per_query])
    return out, queries


def screen_records(candidate: Candidate, records: list[EvidenceRecord],
                   days: int) -> Screened:
    """The free pass. Arithmetic over crawled signals; no model is called, so
    `repo_kind` is unknown here and the kind rules cannot fire."""
    signals = compute(build_threads(records))
    findings = Findings()
    for r in records:
        if r.evidence_id.endswith(":meta"):
            findings.add("is_archived", bool(r.payload.get("is_archived")),
                         (r.evidence_id,))
            break
    verdict, trace = classify(findings, signals, contributor_days=days)
    return Screened(candidate, verdict, trace, signals, _categorise(verdict, trace))


def _categorise(verdict: Verdict, trace: list[str]) -> str | None:
    """Bucket a rejection for the summary. Keyed to the wording `verdict.py`
    emits; a test walks every bucket so a rewording fails loudly here."""
    if verdict is Verdict.VIABLE:
        return None
    # Rules from verdict.py carry a stable `code`; plain strings fall back to
    # the wording they used to be matched on.
    codes = {getattr(r, "code", "") for r in trace}
    joined = " ".join(getattr(r, "legacy", r) for r in trace)
    if "archived" in codes or "archived" in joined:
        return CAT_ARCHIVED
    if "rubber_stamp" in codes or "waved through unread" in joined:
        return CAT_RUBBER_STAMP
    if "slow" in codes or "exceeds the" in joined:
        return CAT_SLOW
    if "ignored" in codes or "drew no response" in joined:
        return CAT_HOSTILE
    return CAT_NO_LANDING


class PrefetchedProvider(EvidenceProvider):
    """Serves records already fetched, so live discovery crawls each survivor
    once instead of once for the fixture and once for the analysis."""

    def __init__(self, window: Window, cutoff: datetime,
                 records: list[EvidenceRecord]) -> None:
        super().__init__(window, cutoff)
        self._records = records
        self._by_id = {r.evidence_id: r for r in records}

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        return self._records

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._by_id.get(evidence_id)


def screen_slug(slug: str, transport, as_of: datetime, days: int,
                candidate: Candidate | None = None
                ) -> tuple[Screened, list[EvidenceRecord]]:
    """Crawl one repository at screening depth and screen it. No model call.

    Returns the records too, so a caller can derive more from the same crawl
    (where outsider work landed) without fetching twice.
    """
    from holt.evidence.github_graphql import LiveGitHubProvider

    provider = LiveGitHubProvider(Window.PRE_T, cutoff=as_of, transport=transport,
                                  max_pages=SCREEN_PAGES)
    records = list(provider.fetch(slug))
    return screen_records(candidate or Candidate(slug=slug), records, days), records


def manifest_path(name: str) -> Path:
    return DISCOVER_ROOT / f"{name}.json"


def screen_root(name: str) -> Path:
    return DISCOVER_ROOT / name / "screen"


def full_root(name: str) -> Path:
    return DISCOVER_ROOT / name / "full"


def trajectory_for(slug: str) -> Path:
    return model.TRAJECTORY_DIR / DISCOVER_TRAJECTORIES / (slug.replace("/", "__") + ".jsonl")


@dataclass(slots=True)
class ScreenedStep:
    """One candidate's turn through screening, reported as it lands."""

    index: int
    total: int
    candidate: Candidate
    result: Screened | None = None
    #: Set when the candidate could not be read at all. Never a rejection —
    #: "we could not look" and "we looked and it failed" are different answers.
    error: str | None = None


@dataclass(slots=True)
class LiveSearch:
    """A live search, cut at the point where a caller wants to see progress.

    `source_live` is the one repository-search call, and carries everything
    needed to say what was searched for. `screen` is the free pass over the
    candidates, yielded one at a time so an interface can draw a row as it
    lands rather than after the last one does.

    Both `run_live` and the terminal interface walk this, so what survives is
    decided in one place. Nothing here decides it: `screen_records` does.
    """

    profile: Profile
    as_of: datetime
    queries: list[str]
    candidates: list[Candidate]
    transport: Any
    #: Session name to write fixtures under, or None. Recording is the caller's
    #: choice and changes nothing about what is screened.
    record: str | None = None

    def screen(self, should_stop: Callable[[], bool] = lambda: False
               ) -> Iterable[ScreenedStep]:
        """Screen each candidate at reduced crawl depth. No model is called.

        Stops between candidates when `should_stop` says so, which is how an
        interface cancels a sweep without waiting for the rest of it.
        """
        total = len(self.candidates)
        for index, cand in enumerate(self.candidates, 1):
            if should_stop():
                return
            try:
                result, records = screen_slug(cand.slug, self.transport, self.as_of,
                                              self.profile.days, cand)
            except Exception as err:  # a dead candidate must not abort the sweep
                yield ScreenedStep(index, total, cand, error=str(err))
                continue
            if self.record:
                write_fixture(cand.slug, Window.PRE_T, records,
                              root=screen_root(self.record), cutoff=self.as_of)
            yield ScreenedStep(index, total, cand, result=result)


def source_live(profile: Profile, limit: int = 25, *,
                as_of: datetime | None = None, transport: Any = None,
                record: str | None = None) -> LiveSearch:
    """GitHub repository search for the stated profile. Sourcing only.

    One network call, before any screening, so a caller can say what it
    searched for and how many it found while the slow half is still ahead.
    """
    from holt.evidence.github_graphql import GitHubGraphQL

    as_of = as_of or datetime.now(UTC)
    transport = transport or GitHubGraphQL()
    candidates, queries = source(transport, profile, as_of, limit)
    return LiveSearch(profile=profile, as_of=as_of, queries=queries,
                      candidates=candidates, transport=transport, record=record)


def contribution_notes(landing: landing_mod.Landing,
                       contributions: list[str]) -> list[str]:
    """Where the kind of work the user wants to do has actually merged.

    Matched against directories where outsider work landed, for the
    contribution types that map to directories. A count of this sample, not a
    promise.
    """
    notes: list[str] = []
    for want in contributions:
        hints = CONTRIBUTION_AREAS.get(want)
        if not hints:  # "code" and unmappable answers annotate nothing
            continue
        hits = [a for a in landing.landed
                if any(seg in hints for seg in a.path.lower().split("/"))]
        if hits:
            listed = ", ".join(f"`{a.path}` ({a.landed} merged)" for a in hits)
            notes.append(f"{want}: outsider work has merged in {listed}")
        else:
            notes.append(f"{want}: no outsider merge in a matching directory "
                         "in this sample")
    return notes


@dataclass(slots=True)
class SurvivorRow:
    slug: str
    verdict: str
    landed: str
    reply: str
    why: str
    notes: list[str]


def analyse_survivor(slug: str, provider: EvidenceProvider, client,
                     days: int, as_of: datetime) -> SurvivorRow:
    records = provider.fetch(slug)
    assessment, trace = analyze(slug, provider, client,
                                contributor_days=days, as_of=as_of)
    signals = trace.signals
    landing = landing_mod.compute(build_threads(records))
    why = assessment.rules[0] if assessment.rules else "no rule fired"
    return SurvivorRow(
        slug=slug,
        verdict=assessment.verdict.value,
        landed=f"{signals.outsider_merged}/{signals.outsider_threads}",
        reply=(f"{signals.median_first_response_hours:.1f}h"
               if signals.median_first_response_hours is not None else "never"),
        why=why if len(why) <= 58 else why[:57].rstrip(" ,;:") + "…",
        notes=[],  # filled by the caller, which knows the profile
    )


def render(profile: Profile, queries: list[str], screened: list[Screened],
           rows: list[SurvivorRow], *, replayed: bool, as_of: datetime,
           skipped: list[str], unanalysed: int,
           unanalysable: list[str] | None = None) -> str:
    lines = [f"# Discover — {profile.describe()}", ""]
    if replayed:
        lines += ["> Replaying a recorded discovery session captured "
                  f"{as_of.date().isoformat()}. No network, no model calls; "
                  "the query below is the recorded one, not a fresh search.", ""]
    lines += [f"Candidates come from GitHub repository search — "
              f"{'; '.join(f'`{q}`' for q in queries)} — "
              # Recorded sessions predate the ordering and are replayed as captured.
              f"{'in search order' if replayed else 'most beginner-labelled issues first, then search order'}. "
              "Holt claims the screening below, not the sourcing and not the "
              "ordering.", ""]

    rejected = [s for s in screened if s.category]
    survivors = [s for s in screened if not s.category]
    lines.append(
        f"Screened {len(screened)} candidates against the newest page of each "
        "repository's pull-request threads — arithmetic only, no model calls, "
        "so these numbers are noisier than a full analysis. "
        f"Rejected {len(rejected)}:"
    )
    lines.append("")
    by_cat: dict[str, int] = {}
    for s in rejected:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        label = cat.replace("the day budget", f"a {profile.days}-day budget")
        lines.append(f"- {n} {label}")
    if skipped:
        lines.append(f"- {len(skipped)} could not be screened "
                     f"({', '.join(skipped)})")
    lines.append("")

    if not survivors:
        lines += ["No candidate survived screening. Widen the search or the "
                  "day budget and try again.", ""]
        return "\n".join(lines).rstrip() + "\n"

    lines.append(f"Analysed {len(rows)} of {len(survivors)} survivors at full "
                 "crawl depth. Rows are in screening order, not ranked.")
    if unanalysed:
        lines.append(f"{unanalysed} survivor(s) not analysed "
                     "(over the --max-analyze cap); nothing is claimed about them.")
    if unanalysable:
        lines.append(f"{len(unanalysable)} survivor(s) could not be analysed "
                     f"({', '.join(unanalysable)}); nothing is claimed about them.")
    lines.append("")

    headers = ("repository", "verdict", "outsiders in", "first reply", "why")
    table = [(r.slug, r.verdict, r.landed, r.reply, r.why) for r in rows]
    widths = [max(len(str(row[i])) for row in (*table, headers)) for i in range(5)]

    def line(cells) -> str:
        return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    lines.append(line(headers))
    lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for r, row in zip(rows, table):
        lines.append(line(row))
        for note in r.notes:
            lines.append(f"|   ↳ {note}")
    lines += ["", "`outsiders in` counts pull requests merged from people with "
              "no prior merge here, over the number who tried.",
              "Run `holt analyze <repo>` for the evidence behind any row."]
    return "\n".join(lines).rstrip() + "\n"


def run_replay(name: str, days: int | None = None,
               max_analyze: int = 8) -> str:
    """Re-run a recorded discovery session with no credentials and no spend.

    The day budget may be changed: screening and the verdict re-run for free,
    which is the same zero-model-call reparameterisation `--days` gives
    `holt analyze`.
    """
    manifest = json.loads(manifest_path(name).read_text())
    as_of = datetime.fromisoformat(manifest["as_of"])
    profile = Profile(**manifest["profile"])
    if days:
        profile.days = days

    candidates = [Candidate(**c) for c in manifest["candidates"]]
    screened, skipped = [], []
    screen_provider = FixtureProvider(Window.PRE_T, root=screen_root(name), cutoff=as_of)
    for cand in candidates:
        try:
            records = screen_provider.fetch(cand.slug)
        except FileNotFoundError:
            skipped.append(cand.slug)
            continue
        screened.append(screen_records(cand, records, profile.days))

    survivors = [s for s in screened if not s.category]
    rows: list[SurvivorRow] = []
    unanalysable: list[str] = []
    for s in survivors[:max_analyze]:
        provider = FixtureProvider(Window.PRE_T, root=full_root(name), cutoff=as_of)
        try:
            client = model.ReplayModel(trajectory_for(s.candidate.slug))
        except FileNotFoundError:
            unanalysable.append(s.candidate.slug)
            continue
        row = analyse_survivor(s.candidate.slug, provider, client, profile.days, as_of)
        records = provider.fetch(s.candidate.slug)
        row.notes = contribution_notes(
            landing_mod.compute(build_threads(records)), profile.contributions)
        rows.append(row)

    return render(profile, manifest["queries"], screened, rows, replayed=True,
                  as_of=as_of, skipped=skipped,
                  unanalysed=max(0, len(survivors) - max_analyze),
                  unanalysable=unanalysable)


def run_live(profile: Profile, limit: int = 25, max_analyze: int = 8,
             record: str | None = None,
             progress: Callable[[str], None] = lambda s: None) -> str:
    """Live discovery. With `record`, every fetch and every model call is
    written down so the session replays byte-for-byte with no credentials."""
    from holt.evidence.github_graphql import LiveGitHubProvider

    search = source_live(profile, limit, record=record)
    as_of, transport, queries = search.as_of, search.transport, search.queries
    candidates = search.candidates
    progress(f"sourced {len(candidates)} candidates from GitHub repository search")

    screened, skipped = [], []
    for step in search.screen():
        if step.result is None:
            skipped.append(step.candidate.slug)
            progress(f"[{step.index}/{step.total}] {step.candidate.slug}: "
                     f"skipped ({step.error})")
            continue
        screened.append(step.result)
        progress(f"[{step.index}/{step.total}] {step.candidate.slug}: "
                 f"{step.result.category or 'survived screening'}")

    survivors = [s for s in screened if not s.category]
    rows: list[SurvivorRow] = []
    unanalysable: list[str] = []
    for s in survivors[:max_analyze]:
        slug = s.candidate.slug
        provider = LiveGitHubProvider(Window.PRE_T, cutoff=as_of,
                                      transport=transport, max_pages=FULL_PAGES)
        try:
            records = provider.fetch(slug)
        except Exception as err:
            unanalysable.append(slug)
            progress(f"analyse {slug}: skipped ({err})")
            continue
        if record:
            write_fixture(slug, Window.PRE_T, records,
                          root=full_root(record), cutoff=as_of)
        cached = PrefetchedProvider(Window.PRE_T, as_of, records)
        client = model.live_client(trajectory_for(slug))
        row = analyse_survivor(slug, cached, client, profile.days, as_of)
        row.notes = contribution_notes(
            landing_mod.compute(build_threads(records)), profile.contributions)
        rows.append(row)
        progress(f"analysed {slug}: {row.verdict} (${client.usage.cost_usd:.4f})")

    if record:
        manifest_path(record).parent.mkdir(parents=True, exist_ok=True)
        manifest_path(record).write_text(json.dumps({
            "name": record,
            "queries": queries,
            "as_of": as_of.isoformat(),
            "captured_at": as_of.isoformat(),
            "profile": {"languages": profile.languages, "topics": profile.topics,
                        "contributions": profile.contributions, "days": profile.days},
            "candidates": [c.as_dict() for c in candidates],
            "analysed": [r.slug for r in rows],
        }, indent=1, sort_keys=True) + "\n")

    return render(profile, queries, screened, rows, replayed=False, as_of=as_of,
                  skipped=skipped, unanalysed=max(0, len(survivors) - max_analyze),
                  unanalysable=unanalysable)
