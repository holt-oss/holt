"""The stages that need a model.

Each returns typed findings carrying evidence ids. Nothing here decides a
verdict: that is verdict.py, and it runs no model. What these stages do is turn
evidence into fields a rule can act on.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

from holt.agent.findings import Findings
from holt.agent.signals import Thread
from holt.model import ModelClient, guarded, untrusted
from holt.types import EvidenceRecord

REPO_KINDS = [
    "real_software",
    "registry",
    "awesome_list",
    "portfolio",
    "course_material",
    "docs",
    "mirror",
    "unclear",
]

CLASSIFY_SYSTEM = """You identify what kind of GitHub repository you are looking at.

The distinction that matters is what a merged pull request *is* here:

  real_software    changes to code that runs: features, fixes, refactors
  registry         entries in a catalogue -- package manifests, domain records,
                   plugin listings, adapter stubs. Merges are easy and frequent
                   and change no software.
  awesome_list     a curated list of links
  portfolio        someone's personal work, coursework, or a collection of demos
  course_material  exercises or teaching material
  docs             a documentation site
  mirror           a read-only copy of a project developed elsewhere
  unclear          the evidence does not settle it

Registries are the common trap: they look extremely healthy on every activity
metric precisely because contributing to them is trivial. Judge by what the
merged diffs touch, not by how many there are.

Cite evidence ids for what you claim. Only cite ids you were given. If the
evidence does not settle the question, answer unclear rather than guessing."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "repo_kind": {"type": "string", "enum": REPO_KINDS},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "rationale": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "governance_flags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["cla_required", "corporate_controlled", "read_only", "none"],
            },
        },
    },
    "required": ["repo_kind", "confidence", "rationale", "evidence_ids", "governance_flags"],
    "additionalProperties": False,
}


def _doc(records: Iterable[EvidenceRecord], suffix: str) -> tuple[str, str] | None:
    for r in records:
        if r.evidence_id.endswith(suffix):
            return r.payload.get("text", ""), r.evidence_id
    return None


def _merged_path_sample(threads: dict[str, Thread], n: int = 25) -> list[tuple[str, list[str]]]:
    """What merged contributions actually touched -- the registry tell."""
    merged = [t for t in threads.values() if t.merged and t.files]
    rng = random.Random(0)
    sample = merged if len(merged) <= n else rng.sample(merged, n)
    return [(t.key, t.files[:4]) for t in sorted(sample, key=lambda t: t.key)]


def classify(
    repo: str,
    records: list[EvidenceRecord],
    threads: dict[str, Thread],
    model: ModelClient,
    findings: Findings,
) -> None:
    meta = next((r for r in records if r.evidence_id.endswith(":meta")), None)
    readme = _doc(records, ":readme")
    contributing = _doc(records, ":contributing")
    paths = _merged_path_sample(threads)

    parts = [f"Repository: {repo}", ""]
    if meta:
        p = meta.payload
        parts += [
            f"Metadata (evidence id: {meta.evidence_id})",
            f"  description: {untrusted(repr(p.get('description')), 'repository description')}",
            f"  primary language: {p.get('primary_language')!r}",
            f"  homepage: {untrusted(repr(p.get('homepage_url')), 'repository homepage')}",
            f"  archived: {p.get('is_archived')}  fork: {p.get('is_fork')}  mirror: {p.get('is_mirror')}",
            "",
        ]
    if readme:
        parts += [f"README (evidence id: {readme[1]})", untrusted(readme[0][:6000], "README"), ""]
    if contributing:
        parts += [f"CONTRIBUTING (evidence id: {contributing[1]})",
                  untrusted(contributing[0][:3000], "CONTRIBUTING"), ""]
    if paths:
        parts += ["Files touched by merged pull requests (evidence ids shown):"]
        parts += [untrusted(
            "\n".join(f"  {key}  {files}" for key, files in paths), "file paths"
        )]
    else:
        parts += ["No merged pull requests with file information were available."]

    result = model.complete(
        label="classify",
        system=guarded(CLASSIFY_SYSTEM),
        prompt="\n".join(parts),
        schema=CLASSIFY_SCHEMA,
    )
    # Stage A cites pull requests too, and shortens them the same way Stage C
    # does. Normalising here as well means a real citation is not thrown away
    # for being written in the wrong shape.
    cited = tuple(normalise_citation(repo, e) for e in result.get("evidence_ids", ()))
    findings.add(
        "repo_kind",
        result["repo_kind"],
        evidence_ids=cited,
        note=result.get("rationale", ""),
    )
    flags = [f for f in result.get("governance_flags", []) if f != "none"]
    if flags:
        findings.add("governance_flags", flags, evidence_ids=cited)
    if meta is not None and meta.payload.get("is_archived"):
        findings.add("is_archived", True, evidence_ids=(meta.evidence_id,))


OUTCOMES_SYSTEM = """You read pull request threads and judge what each one reveals
about an outsider's chances of landing meaningful work in this repository.

This is not sentiment. A polite refusal and an impatient acceptance point in
opposite directions from how they sound. Judge the path the contributor was left
on, not the tone of the words.

Two cases that are easy to get backwards:

  "Thanks for taking the time. We're moving this into the new architecture, so
   closing." -- warm words, but the contributor is told this class of work is not
  wanted. That is discouraging.

  "This isn't right yet. Change X and Y and I'll merge it." -- a rejection at
  this moment, and strong evidence of a working contribution process. That is
  welcoming.

Outcomes:
Cite the exact evidence id shown for each thread, in full, including the
":opened" suffix. Do not abbreviate it to a number.

  merged_after_review        merged, with substantive human feedback on the way
  merged_without_engagement  merged, nobody said anything of substance
  changes_requested          not merged yet, but a maintainer gave a route in
  closed_with_guidance       closed, and the contributor was told where to go instead
  closed_dismissive          closed with no route forward
  ignored                    nobody replied at all

Signal is what the thread tells a prospective contributor: welcoming, neutral,
or discouraging.

Quote the words you judged from, verbatim and short, copied exactly from the
thread. If a thread shows NO_REPLIES there is nothing to quote: return an empty
quote rather than describing the silence. Never quote the scaffolding around the
thread -- only what a person actually wrote. Cite only pull request ids you were
given."""

OUTCOMES_SCHEMA = {
    "type": "object",
    "properties": {
        "threads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pr_id": {"type": "string"},
                    "outcome": {
                        "type": "string",
                        "enum": [
                            "merged_after_review",
                            "merged_without_engagement",
                            "changes_requested",
                            "closed_with_guidance",
                            "closed_dismissive",
                            "ignored",
                        ],
                    },
                    "signal": {
                        "type": "string",
                        "enum": ["welcoming", "neutral", "discouraging"],
                    },
                    "quote": {"type": "string"},
                },
                "required": ["pr_id", "outcome", "signal", "quote"],
                "additionalProperties": False,
            },
        },
        "posture": {"type": "string", "enum": ["welcoming", "mixed", "discouraging", "absent"]},
        "posture_rationale": {"type": "string"},
    },
    "required": ["threads", "posture", "posture_rationale"],
    "additionalProperties": False,
}


def cite_id(thread_key: str) -> str:
    """A thread key is not itself an evidence id -- only its events are.

    Stage C reasons about whole threads, but the provider holds `#12:opened`,
    `#12:merged` and so on. Citing the bare key would make every Stage C finding
    unresolvable and Stage D would correctly delete the entire stage's output.
    """
    return f"{thread_key}:opened"


def normalise_citation(repo: str, cited: str) -> str:
    """Repair the shapes a model reaches for when asked to quote an id.

    Models shorten. Given `pr:owner/name#381843:opened` they will often answer
    `381843`. Repairing the format is not the same as excusing the claim: the
    repaired id is still resolved against real evidence, and still dropped if
    nothing is there.
    """
    cited = (cited or "").strip()
    if cited.isdigit():
        return f"pr:{repo}#{cited}:opened"
    if cited.startswith("pr:") and cited.count(":") == 1:
        return f"{cited}:opened"
    if cited.startswith("#") and cited[1:].isdigit():
        return f"pr:{repo}#{cited[1:]}:opened"
    return cited


def _render_thread(t: Thread) -> str:
    state = "merged" if t.merged else "closed unmerged" if t.closed_unmerged else "open"
    lines = [
        f"--- evidence id: {cite_id(t.key)}  ({state})",
        f"    opened by {t.author}; {t.changed_files} files, +{t.additions}/-{t.deletions}",
        untrusted(f"    files: {t.files[:4]}", "file paths"),
    ]
    if not t.responses:
        # Deliberately not a quotable sentence. The previous wording read like
        # thread content and the model quoted it back as evidence, which the
        # evidence-integrity check caught: 80 of 528 quotes were this scaffold.
        lines.append("    NO_REPLIES")
    replies = []
    for when, who, body in sorted(t.responses)[:6]:
        speaker = "AUTHOR" if who == t.author else who
        replies.append(f"    [{speaker}] {' '.join((body or '').split())[:600]}")
    if replies:
        lines.append(untrusted("\n".join(replies), "pull request comments"))
    return "\n".join(lines)


def read_outcomes(
    repo: str,
    threads: dict[str, Thread],
    model: ModelClient,
    findings: Findings,
    sample: int = 12,
) -> None:
    """Read the threads with the most conversation -- silence is already counted."""
    talkative = sorted(
        (t for t in threads.values() if not t.author_is_bot),
        key=lambda t: (len(t.responses), t.additions + t.deletions),
        reverse=True,
    )[:sample]
    if not talkative:
        findings.add("outsider_posture", "absent", note="no threads available to read")
        return

    prompt = "\n".join(
        [f"Repository: {repo}", "", "Pull request threads:", ""]
        + [_render_thread(t) for t in talkative]
    )
    result = model.complete(
        label="outcomes",
        system=guarded(OUTCOMES_SYSTEM),
        prompt=prompt,
        schema=OUTCOMES_SCHEMA,
    )

    per_thread = result.get("threads", [])
    findings.add(
        "outsider_posture",
        result["posture"],
        evidence_ids=tuple(normalise_citation(repo, t["pr_id"]) for t in per_thread),
        note=result.get("posture_rationale", ""),
    )
    for entry in per_thread:
        findings.add(
            "thread_outcome",
            {"outcome": entry["outcome"], "signal": entry["signal"], "quote": entry["quote"]},
            evidence_ids=(normalise_citation(repo, entry["pr_id"]),),
        )


OPPORTUNITY_SYSTEM = """You judge whether a repository offers an outsider a real
route in, using its own onboarding material.

What counts as a real route: a documented setup that someone could follow, a
described process for proposing work, named places where help is wanted, some
indication of who to ask. What does not: a CONTRIBUTING file that only restates
a code of conduct, a README that is purely marketing, or instructions that
assume commit access.

Answer from the material given. If there is no onboarding material at all, say
so rather than inferring from the project's fame. Cite only evidence ids you
were given."""

OPPORTUNITY_SCHEMA = {
    "type": "object",
    "properties": {
        "onboarding": {
            "type": "string",
            "enum": ["substantive", "boilerplate", "absent", "assumes_insider"],
        },
        "rationale": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["onboarding", "rationale", "evidence_ids"],
    "additionalProperties": False,
}


def assess_opportunity(
    repo: str, records: list[EvidenceRecord], model: ModelClient, findings: Findings
) -> None:
    readme = _doc(records, ":readme")
    contributing = _doc(records, ":contributing")
    parts = [f"Repository: {repo}", ""]
    if contributing:
        parts += [f"CONTRIBUTING (evidence id: {contributing[1]})",
                  untrusted(contributing[0][:6000], "CONTRIBUTING"), ""]
    else:
        parts += ["No CONTRIBUTING file was present at the cutoff.", ""]
    if readme:
        parts += [f"README (evidence id: {readme[1]})", untrusted(readme[0][:4000], "README")]

    result = model.complete(
        label="opportunity",
        system=guarded(OPPORTUNITY_SYSTEM),
        prompt="\n".join(parts),
        schema=OPPORTUNITY_SCHEMA,
    )
    findings.add(
        "onboarding",
        result["onboarding"],
        evidence_ids=tuple(
            normalise_citation(repo, e) for e in result.get("evidence_ids", ())
        ),
        note=result.get("rationale", ""),
    )


NARRATE_SYSTEM = """You write the assessment a careful contributor would leave
after an afternoon reading a repository's pull requests, for someone deciding
where to spend a limited number of days. You are not told how many days they
have; say what the repository is like, not how long it would take them.

You are given a verdict that has already been decided. You do not revisit it,
soften it, or argue with it -- you explain what it rests on.

Three parts, each doing a different job:

**bottom_line** -- two sentences at most, addressed to the reader as "you", and
concrete about what they would be walking into. Not a restatement of the verdict
word. "Your pull request will get a reply within a day, but half of newcomers
here never got one" beats "this repository appears welcoming".

**what_the_evidence_shows** -- plain prose, no headings and no bullet lists, the
way you would write to a colleague. **Two or three short paragraphs, separated by
a blank line, and under 200 words in total.** One unbroken block is something a
reader has to mine rather than read. Lead with the fact that mattered most rather
than with a summary of everything, and leave out anything that does not change
the decision. Quote a maintainer where a quote does the work
better than a paraphrase. Numbers are only useful next to what they mean: "0.8
hours to first reply" is worth writing as fast, "63 threads ignored" is worth
writing as most.

**what_could_not_be_determined** -- one sentence, or empty if there is nothing
honest to put there. Do not invent a limitation to look rigorous, and do not
list something the evidence in front of you actually settles.

Never say a contribution will be accepted. Never describe work as easy. Where the
evidence is thin, say it is thin -- "I could not determine this" is a better
sentence than a confident one that outruns what was read.

Never use the word "cutoff" -- it is internal jargon and means nothing to the
reader. The measurements you are given describe the window of history that was
read; say "in the period read", "in this sample", or name no window at all."""

# Three fields rather than one blob. The old single `summary` produced a
# 250-word paragraph that a reader had to mine for the decision, which is the
# shape of an answer nobody proof-read.
NARRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "bottom_line": {"type": "string"},
        "what_the_evidence_shows": {"type": "string"},
        "what_could_not_be_determined": {"type": "string"},
    },
    "required": ["bottom_line", "what_the_evidence_shows", "what_could_not_be_determined"],
    "additionalProperties": False,
}


def narrate(
    repo: str, verdict: str, trace: list[str], findings: Findings, signals_dict: dict,
    model: ModelClient,
) -> dict:
    # The contributor's day budget is deliberately absent from this prompt. It
    # reaches the reader through the renderer's headline and through the rule
    # trace below, both of which are computed without a model. Putting it here
    # made the prompt vary with `--days`, which turned every non-default budget
    # into a replay miss and quietly broke the one claim that re-answering the
    # question costs nothing.
    lines = [f"Repository: {repo}", f"Verdict (already decided, do not change): {verdict}", ""]
    lines += ["Why the rules landed there:"] + [f"  - {t}" for t in trace]
    lines += ["", "Measured in the sampled window:"]
    lines += [f"  {k}: {v}" for k, v in signals_dict.items()]
    # Findings passed Stage D, so their citations resolve -- but the values and
    # notes are a model's reading of repository text, and quotes are that text.
    # Both are fenced: resolving is not the same as being true.
    lines += ["", "Verified findings:"]
    for item in findings:
        note = f" -- {untrusted(item.note, 'AI rationale, not verified')}" if item.note else ""
        value = str(item.value)
        if isinstance(item.value, dict) and item.value.get("quote"):
            value = untrusted(value, "AI reading with a quote from a thread")
        lines.append(f"  {item.field} = {value}{note}")
    return model.complete(
        label="narrate",
        system=guarded(NARRATE_SYSTEM),
        prompt="\n".join(lines),
        schema=NARRATE_SCHEMA,
    )


PATHFINDER_SYSTEM = """You are helping an outside developer -- someone with no
prior connection to a project -- choose which open issue to attempt first.

You are given issues that were open at a fixed point in time, and evidence about
how the project treated outside contributions before that point.

Rank the issues by one thing only: **how likely is it that an outsider, starting
from nothing, lands a merged pull request resolving this issue?**

That is not the same as "which issue is most important", and it is not the same
as "which issue is easiest". Weigh:

  * whether the issue states a concrete, bounded outcome rather than a wish
  * whether someone could act on it without private context or a design decision
    only a maintainer can make
  * whether the report contains enough to reproduce or locate the problem
  * whether the project's history suggests work of this shape gets merged

An issue labelled for beginners is not automatically a good entry point; many
are aspirational one-liners nobody has scoped. Judge the text, not the label.

Return at most five, best first. For each, say in one sentence what the person
would actually do, and cite the issue's evidence id."""

PATHFINDER_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_id": {"type": "string"},
                    "first_step": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["evidence_id", "first_step", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ranked"],
    "additionalProperties": False,
}

MAX_ISSUES_SHOWN = 40


def _render_issue(record: EvidenceRecord) -> str:
    p = record.payload
    body = " ".join((p.get("body") or "").split())[:700]
    return "\n".join([
        f"--- evidence id: {record.evidence_id}",
        f"    opened {record.timestamp.date()} by {p.get('author')}; "
        f"{p.get('comments', 0)} comments; labels: {p.get('labels') or 'none'}",
        untrusted(f"    title: {p.get('title')}\n    {body or '(no description)'}",
                  "issue title and body"),
    ])


def find_paths(
    repo: str,
    issues: list[EvidenceRecord],
    signals_summary: dict,
    model: ModelClient,
) -> list[dict]:
    """Rank candidate issues. Returns [] when there is nothing worth ranking.

    Shipped, and shipped losing. It does not beat the comparators it was
    pre-registered against, and `holt.agent.entry` prints that result in the same
    output as the ranking rather than filing it in a document. Call through
    `entry.rank` rather than directly: it is what both the CLI and
    `eval/pathfinder_harness.py` use, which is the only reason the published
    precision describes something a user can actually run.
    """
    if not issues:
        return []
    # Most-discussed first: an issue nobody has said anything about is usually
    # unscoped, and the sample has to fit in one call.
    shown = sorted(
        issues, key=lambda r: r.payload.get("comments", 0), reverse=True
    )[:MAX_ISSUES_SHOWN]

    prompt = "\n".join(
        [f"Repository: {repo}", "", "How this project treated outsiders before the cutoff:"]
        + [f"  {k}: {v}" for k, v in signals_summary.items()]
        + ["", f"Issues open at the cutoff ({len(shown)} of {len(issues)} shown):", ""]
        + [_render_issue(r) for r in shown]
    )
    return model.complete(
        label="pathfinder", system=guarded(PATHFINDER_SYSTEM), prompt=prompt,
        schema=PATHFINDER_SCHEMA,
    )["ranked"]
