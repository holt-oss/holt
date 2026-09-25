"""Pre-cutoff signals computed from evidence, with no model involved.

The split matters. Counting merges and measuring how long a maintainer took to
reply are arithmetic; asking a language model to do them adds cost, variance and
a chance of being wrong about a number that was sitting right there. What the
model is for is judgement -- what kind of project is this, what does the tone of
that thread mean -- which is the part arithmetic cannot reach.

Note what is deliberately absent: this module has no diff-shape rules. L1 has
those, and if the agent shared them it would agree with the label by
construction on the dimension that matters most. The agent judges what a
contribution *was* by reading, not by re-running the grader's arithmetic.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from holt.types import EvidenceRecord


def pr_key(evidence_id: str) -> str:
    return ":".join(evidence_id.split(":")[:2])


# GitHub only marks an account as a Bot when it is a real GitHub App. Plenty of
# automation runs on ordinary user accounts -- wingetbot on microsoft/winget-pkgs
# posts every validation log as a normal user -- and counting those as human
# engagement turns an auto-merge pipeline into a conversational project. Applied
# at read time so fixtures stay as captured.
_BOT_HINTS = ("dependabot", "renovate", "greenkeeper", "imgbot", "allcontributors",
              "codecov", "sonarcloud", "netlify", "vercel", "mergify", "stale")


# A pull request opened an hour ago has not been ignored; nobody has had the
# chance to read it. Without this, a busy repository read at any moment looked
# hostile, because its newest pull requests -- often most of the sample -- had
# no reply *yet*. Two days covers a weekend's silence without excusing a week.
MIN_AGE_HOURS = 48.0


def looks_like_bot(login: str, flagged: bool = False) -> bool:
    if flagged:
        return True
    low = (login or "").lower()
    if low.endswith("[bot]") or low.endswith("bot") or "-bot" in low:
        return True
    return any(hint in low for hint in _BOT_HINTS)


@dataclass(slots=True)
class Thread:
    """One pull request and everything that happened on it before the cutoff."""

    key: str
    number: int
    author: str
    author_is_bot: bool
    opened_at: object
    files: list[str] = field(default_factory=list)
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    merged: bool = False
    closed_unmerged: bool = False
    responses: list[tuple[object, str, str]] = field(default_factory=list)

    @property
    def first_response_hours(self) -> float | None:
        """Hours until someone other than the author first said anything."""
        others = [t for t, who, _ in self.responses if who != self.author]
        if not others:
            return None
        return (min(others) - self.opened_at).total_seconds() / 3600

    @property
    def engaged(self) -> bool:
        return any(who != self.author for _, who, _ in self.responses)

    def awaiting_reply(self, as_of: datetime | None, min_age_hours: float) -> bool:
        """Still open, unanswered, and too new for that silence to mean anything."""
        if as_of is None or min_age_hours <= 0:
            return False
        if self.engaged or self.merged or self.closed_unmerged:
            return False
        return as_of - self.opened_at < timedelta(hours=min_age_hours)


def build_threads(records: Iterable[EvidenceRecord]) -> dict[str, Thread]:
    threads: dict[str, Thread] = {}
    records = list(records)

    for r in records:
        if not r.evidence_id.endswith(":opened"):
            continue
        p = r.payload
        key = pr_key(r.evidence_id)
        threads[key] = Thread(
            key=key,
            number=int(key.split("#")[-1]),
            author=p.get("author", ""),
            author_is_bot=looks_like_bot(p.get("author", ""), bool(p.get("author_is_bot"))),
            opened_at=r.timestamp,
            files=list(p.get("files") or []),
            changed_files=p.get("changed_files") or 0,
            additions=p.get("additions") or 0,
            deletions=p.get("deletions") or 0,
        )

    for r in records:
        key = pr_key(r.evidence_id)
        thread = threads.get(key)
        if thread is None:
            continue
        if r.evidence_id.endswith(":merged"):
            thread.merged = True
        elif r.evidence_id.endswith(":closed"):
            thread.closed_unmerged = True
        elif ":review:" in r.evidence_id or ":comment:" in r.evidence_id:
            if not looks_like_bot(
                r.payload.get("author", ""), bool(r.payload.get("author_is_bot"))
            ):
                thread.responses.append(
                    (r.timestamp, r.payload.get("author", ""), r.payload.get("body") or "")
                )
    return threads


def newcomer_threads(threads: dict[str, Thread]) -> list[Thread]:
    """Threads opened by someone who had not yet landed anything here.

    The obvious definition -- an outsider is anyone without a merged pull
    request -- is circular inside a single window: merging is what stops you
    being an outsider, so "outsider merges" is always zero. That bug produced a
    column of zeros across the whole pool before it was caught.

    Asked properly, the question is per-thread and time-ordered: at the moment
    this pull request was opened, had its author ever landed anything here
    before? That is also the question a newcomer actually has, which is the
    point of the project.
    """
    merged_opens: dict[str, list] = {}
    for t in threads.values():
        if t.merged and not t.author_is_bot:
            merged_opens.setdefault(t.author, []).append(t.opened_at)

    return [
        t
        for t in threads.values()
        if not t.author_is_bot
        and not any(earlier < t.opened_at for earlier in merged_opens.get(t.author, []))
    ]


@dataclass(slots=True)
class Signals:
    total_threads: int
    outsider_threads: int
    outsider_merged: int
    outsider_ignored: int
    median_first_response_hours: float | None
    bot_share: float
    distinct_outsider_authors: int
    distinct_merged_authors: int
    # Share of merged threads where somebody other than the author, and not a
    # bot, said anything at all. Mechanical, over every merge -- not the
    # twelve-thread model-judged sample that the first rejection rule used and
    # which is the likeliest reason that attempt failed.
    reviewed_share: float | None
    merge_rate: float | None
    # The shape of a merged contribution: how many files it touched, and how
    # many top-level directories those spanned, at the median. A catalogue entry
    # is one file in one place almost by definition; a change to running
    # software is not. These exist so a claim *about* that shape -- `registry`,
    # `awesome_list` -- can be checked against it rather than trusted.
    merged_files_median: float | None = None
    merged_dirs_median: float | None = None
    merged_with_files: int = 0
    # Outsider attempts too new to judge: unanswered, but opened less than
    # MIN_AGE_HOURS before the reading. Counted in `outsider_threads` (they are
    # attempts) and never in `outsider_ignored`.
    outsider_awaiting_reply: int = 0
    # How many outsider attempts got any reply. `median_first_response_hours`
    # is the median over exactly these; the rest never got one, which a median
    # over replies alone cannot show. Report the two together.
    outsider_answered: int = 0

    @property
    def outsider_judgeable(self) -> int:
        """Attempts old enough that silence on them means something."""
        return self.outsider_threads - self.outsider_awaiting_reply

    def as_dict(self) -> dict:
        return {
            "total_threads": self.total_threads,
            "outsider_threads": self.outsider_threads,
            "outsider_merged": self.outsider_merged,
            "outsider_ignored": self.outsider_ignored,
            "median_first_response_hours": self.median_first_response_hours,
            "bot_share": round(self.bot_share, 3),
            "distinct_outsider_authors": self.distinct_outsider_authors,
            "distinct_merged_authors": self.distinct_merged_authors,
            "reviewed_share": self.reviewed_share,
            "merge_rate": self.merge_rate,
            "merged_files_median": self.merged_files_median,
            "merged_dirs_median": self.merged_dirs_median,
            "merged_with_files": self.merged_with_files,
            "outsider_awaiting_reply": self.outsider_awaiting_reply,
            "outsider_answered": self.outsider_answered,
        }


def compute(
    threads: dict[str, Thread],
    as_of: datetime | None = None,
    min_age_hours: float = MIN_AGE_HOURS,
) -> Signals:
    """Count what the threads show.

    `as_of` is the moment the evidence is read at. Given one, attempts younger
    than `min_age_hours` with no reply are "awaiting a reply", not ignored.
    Without one (or with `min_age_hours=0`) every silent attempt counts, which
    is how the committed benchmark was computed.
    """
    outsiders = newcomer_threads(threads)
    waiting = [t for t in outsiders if t.awaiting_reply(as_of, min_age_hours)]
    waiting_keys = {t.key for t in waiting}
    merged_threads = [t for t in threads.values() if t.merged]
    # Every merge with a file list, not only the outsiders': what a merged
    # contribution *is* here is a property of the repository, and narrowing it
    # to newcomers would measure it on a handful of threads in a repository that
    # merges hundreds.
    shaped = [t for t in merged_threads if t.files]
    file_counts = [len(t.files) for t in shaped]
    dir_counts = [len({f.split("/")[0] for f in t.files}) for t in shaped]
    latencies = [h for t in outsiders if (h := t.first_response_hours) is not None]
    bots = sum(1 for t in threads.values() if t.author_is_bot)

    return Signals(
        total_threads=len(threads),
        outsider_threads=len(outsiders),
        outsider_merged=sum(1 for t in outsiders if t.merged),
        outsider_ignored=sum(
            1 for t in outsiders
            if not t.engaged and not t.merged and t.key not in waiting_keys
        ),
        median_first_response_hours=round(statistics.median(latencies), 1) if latencies else None,
        bot_share=(bots / len(threads)) if threads else 0.0,
        distinct_outsider_authors=len({t.author for t in outsiders}),
        # People who actually landed something, as distinct from people who
        # tried. Conflating the two produced a user-visible falsehood: a repo
        # with 15 merges and 72 first-time attempters was reported as "15
        # merges from 72 people".
        distinct_merged_authors=len({t.author for t in outsiders if t.merged}),
        reviewed_share=(
            sum(1 for t in merged_threads if t.engaged) / len(merged_threads)
            if merged_threads else None
        ),
        merge_rate=(len(outsiders) and sum(1 for t in outsiders if t.merged) / len(outsiders))
        or (None if not outsiders else 0.0),
        merged_files_median=statistics.median(file_counts) if file_counts else None,
        merged_dirs_median=statistics.median(dir_counts) if dir_counts else None,
        merged_with_files=len(shaped),
        outsider_awaiting_reply=len(waiting),
        outsider_answered=len(latencies),
    )
