"""Warm the caches before people arrive: popular repos' reports and starter
issues, the repository details Discover shows, and the /find searches the web
app's default pages make.

    python -m holt_server.warm                 # everything, stopping on GitHub budget
    python -m holt_server.warm --dry-run       # what would run, no GitHub calls
    python -m holt_server.warm --no-find --limit 50
    python -m holt_server.warm --stale-only    # after a deploy: redo reports from an older engine
    python -m holt_server.warm --tier weekly   # reports only: saved or recently viewed repos
    python -m holt_server.warm --tier monthly  # reports only: the rest of the seed list
    python -m holt_server.warm --no-reports --no-starter --no-find   # details only (daily timer)

Or in the API process on a schedule: HOLT_WARM_INTERVAL_HOURS=6.

How it stays out of the way:

* Reports go through the normal job queue at badge priority, so every user
  request runs first. The pass keeps HOLT_WARM_PARALLEL (3) report jobs in
  flight and queues the next as one finishes; the runner's badge lane
  (HOLT_BADGE_CONCURRENCY) should allow as many at a time.
* Fresh work is skipped: reports under HOLT_WARM_MAX_AGE_HOURS (20), finds
  and starter issues still inside most of their cache lifetime. A report or
  find made by an older engine version (holt.engine_version) is never fresh.
  `--stale-only` does just those: every seed whose latest report is from an
  older engine, however young, and nothing else. Run it after a deploy that
  bumps ENGINE_VERSION. Where the evidence behind that report was kept
  (evidence_store.py) and is younger than its repo's refresh tier (a week or
  a month; at least HOLT_EVIDENCE_REUSE_HOURS), the report is made again from
  it, in this process, with no GitHub call.
* Seeds the last look found closed to outside pull requests (GitHub's
  settings, or archived) or dormant (no push in DORMANT_DAYS) go last, so a
  pass that runs out of budget has done the useful ones. That comes from
  their last report and repo_meta; nothing is read from GitHub to decide it.
* Repository details (discover.py) are read for every reported repo at once,
  a hundred per GraphQL query (about a point each), once a day. A repo's
  first report reads its own details right away (meta_refresh.py); the
  details-only pass (`deploy/prod/warm-meta.sh`, a daily timer) keeps the
  rest from going stale. The summary says how many GitHub points it used.
* Refresh tiers (`--tier`, deploy/prod/warm-refresh.sh): repos someone saved,
  viewed in the last INTEREST_DAYS, or has an open pull request PR watch
  alerts on, are the weekly tier; the rest of the seed list is the monthly one. A tier pass runs reports only, the oldest
  first, and skips any younger than HOLT_WARM_MAX_AGE_HOURS, which the
  timer sets per tier (a week, a month).
* Before each report job, and every few other steps, it checks the GitHub
  GraphQL points left on every token and stops below HOLT_WARM_MIN_POINTS,
  counting REPORT_POINTS for each report still in flight, so a warm pass can
  never starve the requests people make. `--wait-for-budget` waits for the
  points to come back instead of stopping (a long sweep, left alone).
* A seed whose report fails is remembered (`warm_failures`) and not asked for
  again for RETRY_HOURS, doubling with each failure in a row up to a week; a
  repository that isn't on GitHub, for a month. When its wait is over it goes
  to the back of the queue. So a pass spends its time on seeds that can
  succeed, and a repository GitHub can't answer for (a 502 after ten seconds
  of its time, every try) isn't asked for again every round.
* BREAKER_FAILURES reports in a row failing on GitHub's side pause the pass
  for BREAKER_PAUSE_S: a run of those is what makes GitHub rate-limit the
  App, which people's checks read with too.
* When GitHub says "slow down" (a rate limit: `rate_limited`), that is no
  repository's failure. With `--wait-for-budget` the pass waits as long as
  GitHub asked (longer each time it says so again), then runs one report at
  a time for SLOW_S, and asks for the same seed again; it ends only after
  MAX_LIMITS_IN_A_ROW waits with no report made. Without the flag it ends
  there and says so.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select

from holt_server import evidence_store, repos, starter
from holt_server.db import (
    ACTIVE,
    BADGE_PRIORITY,
    ENGINE_VERSION,
    AlertSettings,
    Contribution,
    FindCache,
    Job,
    RepoMeta,
    RepoView,
    Report,
    SavedRepo,
    StarterCache,
    WarmFailure,
    dedupe_key,
    find_key,
    now,
    utc,
)
from holt_server.errors import ApiError

log = logging.getLogger("holt_server.warm")

# Package data, so it ships in the wheel and the image.
SEEDS = Path(__file__).with_name("seeds") / "repos.txt"
DAYS = 7
JOB_TIMEOUT_S = 15 * 60
POLL_S = 1.0
# Budget is checked before every report job, and before the first of the
# other steps and then every this many.
BUDGET_EVERY = 5
# The most GitHub points one report costs (measured: 10 typical, 18 at most),
# held back for each report still in flight when the budget is checked.
REPORT_POINTS = 20
# What a report costs on average (production, 304 repos), for dry-run estimates.
REPORT_POINTS_TYPICAL = 12
# --wait-for-budget: how long to wait before looking at the points again.
BUDGET_WAIT_S = 300
# Seeds with no push in this many days go last (the engine's "inactive" rule
# looks at the same 90 days), and so do those whose last report was decided
# by one of these rules.
DORMANT_DAYS = 90
QUIET_RULES = frozenset({"archived", "prs_closed", "inactive"})
# A job that never finishes fails its repository and the pass goes on; this
# many in a row means nothing is working the queue, and the pass stops.
MAX_TIMEOUTS_IN_A_ROW = 3
# A seed whose report failed isn't asked for again for this long, doubling
# with each failure in a row up to RETRY_MAX_HOURS. One that isn't on GitHub
# (renamed away or deleted) waits NOT_FOUND_RETRY_HOURS and is listed in the
# summary until the seed list is fixed.
RETRY_HOURS = 6
RETRY_MAX_HOURS = 7 * 24
NOT_FOUND_RETRY_HOURS = 30 * 24
# This many reports in a row failing on GitHub's side (502, 504, a timeout)
# pause the pass this long, however many seeds are left.
BREAKER_FAILURES = 5
BREAKER_PAUSE_S = 300
# After GitHub says "slow down": wait what it asked (LIMIT_WAIT_S when it
# named no time, never under LIMIT_WAIT_MIN_S), doubling each time it says so
# again with no report made in between, up to LIMIT_WAIT_MAX_S; then one
# report at a time for SLOW_S. After MAX_LIMITS_IN_A_ROW such waits in a row
# (about three hours) the pass ends.
LIMIT_WAIT_S = 300
LIMIT_WAIT_MIN_S = 60
LIMIT_WAIT_MAX_S = 3600
SLOW_S = 30 * 60
MAX_LIMITS_IN_A_ROW = 6
# A "progress:" line every this many seeds (`warm.sh --status` shows the last).
PROGRESS_EVERY = 25
# The pauses' clock and sleep (the tests put their own in).
clock = time.monotonic
sleep = asyncio.sleep
# Refresh a cached find or starter list once this share of its lifetime is gone.
REFRESH_AFTER = 0.8
FIND_LIMIT = 20
LOCK_ID = 7_406_111
# Exit status when another process is warming (as deploy.sh: try again later).
BUSY = 75
TIERS = ("weekly", "monthly")
# Viewed on Holt this recently: the weekly tier.
INTEREST_DAYS = 30
# A report is stored a few minutes after its evidence was read (the job's run
# time), so a snapshot this much older than the report is still its evidence.
SNAPSHOT_SLACK = timedelta(hours=1)

# The searches the web app makes on its own pages (web/src/app/hacktoberfest
# and web/src/app/find): languages as the web sends them, lower-cased.
HACKTOBERFEST_TABS: list[list[str]] = [
    [], ["python"], ["javascript", "typescript"], ["go"], ["rust"], ["java"],
    ["c", "c++"], ["ruby"], ["php"],
]
FIND_CHIPS = ["python", "javascript", "typescript", "go", "rust", "java", "c++", "ruby",
              "php", "nix"]


@dataclass(frozen=True)
class Profile:
    languages: tuple[str, ...]
    hacktoberfest: bool
    days: int = DAYS

    @property
    def key(self) -> str:
        return find_key(list(self.languages), [], self.hacktoberfest, self.days)


def profiles() -> list[Profile]:
    seen: dict[str, Profile] = {}
    candidates = [Profile(tuple(sorted(t)), True) for t in HACKTOBERFEST_TABS]
    candidates += [Profile((lang,), hf) for lang in FIND_CHIPS for hf in (True, False)]
    for p in candidates:
        seen.setdefault(p.key, p)
    return list(seen.values())


def load_seeds(path: Path | str | None = None) -> list[str]:
    """`owner/repo` per line; `#` comments and blank lines ignored; deduplicated."""
    out, seen = [], set()
    for line in Path(path or SEEDS).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            repo = repos.normalize(line)
        except ApiError:
            log.warning("seed %r is not a repository; skipped", line)
            continue
        if repos.key(repo) not in seen:
            seen.add(repos.key(repo))
            out.append(repo)
    return out


def retry_delay(code: str, failures: int) -> timedelta:
    """How long a seed waits after its `failures`-th failure in a row."""
    if code == "not_found":
        return timedelta(hours=NOT_FOUND_RETRY_HOURS)
    return timedelta(hours=min(RETRY_HOURS * 2 ** (max(failures, 1) - 1), RETRY_MAX_HOURS))


def limit_wait(retry_after: float | None, in_a_row: int) -> float:
    """Seconds to wait after GitHub's `in_a_row`-th "slow down" in a row."""
    asked = max(float(retry_after or LIMIT_WAIT_S), LIMIT_WAIT_MIN_S)
    return min(asked * 2 ** (max(in_a_row, 1) - 1), LIMIT_WAIT_MAX_S)


def minutes(seconds: float) -> str:
    n = max(1, round(seconds / 60))
    return f"{n} minute{'' if n == 1 else 's'}"


@dataclass
class Result:
    reports_run: int = 0
    reports_fresh: int = 0
    # Made again from kept evidence, with no GitHub call (--stale-only).
    reports_rederived: int = 0
    reports_failed: int = 0
    # Failed lately and not due again yet (retry_delay): not asked for.
    skipped_failed: int = 0
    # Failed before and due again: asked for after everything else.
    failed_last: int = 0
    # Seeds this pass leaves without a current report (failed, skipped or
    # not reached).
    left: int = 0
    # Seeds GitHub says aren't there, this pass or one before: fix the list.
    not_found: list[str] = field(default_factory=list)
    # Times the pass paused: GitHub said slow down, or reports kept failing.
    pauses: int = 0
    # Closed to outside pull requests or dormant, so warmed last.
    quiet_last: int = 0
    starter_run: int = 0
    starter_fresh: int = 0
    meta_run: int = 0
    meta_points: int = 0
    finds_run: int = 0
    finds_fresh: int = 0
    stopped: str | None = None
    dry_run: bool = False
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"reports {self.reports_run} run, {self.reports_fresh} fresh, "
                 f"{self.reports_failed} failed",
                 f"{self.skipped_failed} skipped as recently failed",
                 f"{self.left} still without a current report",
                 f"{len(self.not_found)} not on GitHub",
                 f"{self.reports_rederived} made again from kept evidence",
                 f"{self.quiet_last} closed or dormant seeds last",
                 f"starter issues {self.starter_run} run, {self.starter_fresh} fresh",
                 f"repo details {self.meta_run} read ({self.meta_points} GitHub points)",
                 f"finds {self.finds_run} run, {self.finds_fresh} fresh"]
        if self.dry_run:
            parts.append(f"the reports would use about "
                         f"{self.reports_run * REPORT_POINTS_TYPICAL} GitHub points")
        if self.stopped:
            parts.append(f"stopped: {self.stopped}")
        return "; ".join(parts)


class OutOfBudget(Exception):
    pass


class Warmer:
    def __init__(self, svc, say: Callable[[str], None] = log.info, dry_run: bool = False,
                 parallel: int | None = None, wait_for_budget: bool = False):
        self.svc = svc
        self.say = say
        self.dry_run = dry_run
        # Report jobs in flight at once; a dry run goes one by one, in order.
        self.parallel = 1 if dry_run else max(1, parallel or svc.settings.warm_parallel)
        self.wait_for_budget = wait_for_budget
        self.result = Result(dry_run=dry_run)
        self._steps = 0
        self._timeouts = 0
        self._in_flight = 0
        # Seeds with a remembered failure, by repo key (failed_last).
        self._failures: dict[str, WarmFailure] = {}
        self._not_found: dict[str, str] = {}
        # No report starts before `_paused_until`; until `_slow_until`, one
        # at a time (both on `clock`).
        self._paused_until = 0.0
        self._slow_until = 0.0
        # In a row, with no report made in between.
        self._upstream = 0
        self._limits = 0
        self._looked_at = 0
        self._queue = 0
        # One budget check at a time, so two workers can't both take the last points.
        self._budget = asyncio.Lock()
        # repo keys of the weekly refresh tier (--stale-only's snapshot ages).
        self._weekly: set[str] = set()

    # --- budget -------------------------------------------------------------

    async def check_budget(self) -> None:
        """Before a step other than a report: every BUDGET_EVERY steps."""
        if self.dry_run:
            return
        self._steps += 1
        if (self._steps - 1) % BUDGET_EVERY:
            return
        async with self._budget:
            await self._enough_points()

    @contextlib.asynccontextmanager
    async def report_slot(self):
        """Around one report job: the budget checked first, with REPORT_POINTS
        held back for every report already in flight."""
        async with self._budget:
            await self._hold()
            await self._enough_points()
            self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1

    async def _hold(self) -> None:
        """Before a report starts: sit out a pause, and after a "slow down"
        wait for the report in flight, so they go one at a time."""
        while True:
            at = clock()
            if at < self._paused_until:
                await sleep(self._paused_until - at)
            elif at < self._slow_until and self._in_flight:
                await asyncio.sleep(POLL_S)
            else:
                return

    def pause(self, seconds: float) -> None:
        self._paused_until = max(self._paused_until, clock() + seconds)
        self.result.pauses += 1

    def slow_down(self, retry_after: float | None) -> None:
        """GitHub rate-limited a report. Wait as long as it asked, longer each
        time it says so again, then go one at a time for a while; OutOfBudget
        without --wait-for-budget, or when it has gone on too long."""
        if clock() < self._paused_until:
            return  # another report in flight was told the same
        self._limits += 1
        wait = limit_wait(retry_after, self._limits)
        if not self.wait_for_budget:
            raise OutOfBudget(
                "GitHub asked us to slow down (a rate limit, not a failing repository); "
                f"it takes requests again in about {minutes(wait)}. Run again then, or "
                "with --wait-for-budget to wait here")
        if self._limits > MAX_LIMITS_IN_A_ROW:
            raise OutOfBudget(
                f"GitHub asked us to slow down {self._limits} times in a row, with no "
                "report made in between; run again later")
        self.pause(wait)
        self._slow_until = self._paused_until + SLOW_S
        self.say(f"GitHub asked us to slow down (a rate limit): waiting {minutes(wait)}, "
                 f"then one report at a time for {minutes(SLOW_S)}")

    async def _enough_points(self) -> None:
        """OutOfBudget when the points left, less what the reports in flight
        may still spend, are under HOLT_WARM_MIN_POINTS; with --wait-for-budget,
        wait for them to come back instead."""
        floor = self.svc.settings.warm_min_points
        while True:
            # This process's own readers are held by a rate limit: the points
            # can't be asked for, and they are not what ran out.
            hold = self.svc.pool.held()
            if hold is not None:
                kind = ("asked us to slow down (too much at once, not the hourly points)"
                        if hold.secondary else "says the hourly points are used up")
                why = f"GitHub {kind}; it takes requests again in about {minutes(hold.seconds)}"
                if not self.wait_for_budget:
                    raise OutOfBudget(why)
                self.say(f"{why}; waiting")
                await sleep(hold.seconds + 1)
                continue
            remaining = await self.svc.lookup.remaining()
            spare = remaining - self._in_flight * REPORT_POINTS
            if spare >= floor:
                return
            why = f"GitHub points left {remaining} < {floor}"
            if self._in_flight:
                n = self._in_flight
                why = (f"GitHub points left {remaining}, {spare} after the {n} "
                       f"report{'' if n == 1 else 's'} in flight, < {floor}")
            if not self.wait_for_budget:
                raise OutOfBudget(why)
            self.say(f"{why}; looking again in {BUDGET_WAIT_S // 60} minutes")
            await asyncio.sleep(BUDGET_WAIT_S)

    # --- freshness ----------------------------------------------------------

    async def latest_report(self, repo: str) -> Report | None:
        """The seed's newest 7-day rules report: its time and engine version only."""
        async with self.svc.db.session() as s:
            row = (await s.execute(
                select(Report.created_at, Report.engine_version).where(
                    Report.repo_key == repos.key(repo), Report.mode == "rules",
                    Report.days == DAYS)
                .order_by(Report.created_at.desc(), Report.id.desc()).limit(1)
            )).first()
        return Report(created_at=row[0], engine_version=row[1]) if row else None

    async def report_is_fresh(self, repo: str) -> bool:
        cutoff = now() - timedelta(hours=self.svc.settings.warm_max_age_hours)
        latest = await self.latest_report(repo)
        return latest is not None and not latest.outdated and utc(latest.created_at) >= cutoff

    async def report_is_outdated(self, repo: str) -> bool:
        """There is a report, and an older engine made it."""
        latest = await self.latest_report(repo)
        return latest is not None and latest.outdated

    async def starter_is_fresh(self, repo: str) -> bool:
        ttl = timedelta(hours=self.svc.settings.starter_cache_hours * REFRESH_AFTER)
        async with self.svc.db.session() as s:
            row = await s.get(StarterCache, repos.key(repo))
        return (row is not None and utc(row.created_at) >= now() - ttl
                and starter.current(row.issues, row.rules_version))

    async def find_is_fresh(self, profile: Profile) -> bool:
        ttl = timedelta(hours=self.svc.settings.find_cache_hours * REFRESH_AFTER)
        async with self.svc.db.session() as s:
            row = await s.get(FindCache, profile.key)
        return row is not None and not row.outdated and utc(row.created_at) >= now() - ttl

    # --- jobs ---------------------------------------------------------------

    async def run_job(self, job: Job) -> Job | None:
        """The finished job, or None if it timed out (counted as a failure)."""
        if self._timeouts >= MAX_TIMEOUTS_IN_A_ROW:
            raise OutOfBudget(
                f"{self._timeouts} jobs in a row were never finished; is anything "
                "working the queue (HOLT_BADGE_CONCURRENCY > 0)?")
        try:
            done = await self._run_job(job)
        except TimeoutError as exc:
            self._timeouts += 1
            self.say(str(exc))
            return None
        self._timeouts = 0
        return done

    async def _run_job(self, job: Job) -> Job:
        """Queue (or join an identical queued job) and wait for it to finish."""
        from holt_server.api import active_job, insert_or_join

        if job.kind == "find":
            job_id = await self._insert_find(job)
        elif (running := await active_job(self.svc, job.repo_key, job.mode, job.days)):
            job_id = running.id  # wait on it; joining would raise its priority
        else:
            job_id = (await insert_or_join(self.svc, job))[0].id
        waited = 0.0
        while waited < JOB_TIMEOUT_S:
            async with self.svc.db.session() as s:
                row = await s.get(Job, job_id)
            if row is not None and row.status not in ACTIVE:
                return row
            await asyncio.sleep(POLL_S)
            waited += POLL_S
        raise TimeoutError(f"job {job_id} still running after {JOB_TIMEOUT_S}s")

    async def _insert_find(self, job: Job) -> str:
        from sqlalchemy.exc import IntegrityError

        async with self.svc.db.session() as s:
            s.add(job)
            try:
                await s.commit()
                self.svc.runner.wake()
                return job.id
            except IntegrityError:
                await s.rollback()
        async with self.svc.db.session() as s:
            return (await s.execute(select(Job.id).where(
                Job.dedupe_key == job.dedupe_key, Job.status.in_(ACTIVE)))).scalar_one()

    # --- the three passes ---------------------------------------------------

    async def warm_report(self, repo: str, stale_only: bool = False) -> None:
        skip = (not await self.report_is_outdated(repo) if stale_only
                else await self.report_is_fresh(repo))
        if skip:
            self.result.reports_fresh += 1
            return
        if stale_only and await self.from_snapshot(repo):
            return
        if self.dry_run:
            self.say(f"would analyse {repo}")
            self.result.reports_run += 1
            return
        key = repos.key(repo)
        while True:
            async with self.report_slot():
                done = await self.run_job(Job(
                    kind="analysis", repo=repo, repo_key=key, mode="rules", days=DAYS, params={},
                    priority=BADGE_PRIORITY, dedupe_key=dedupe_key(key, "rules", DAYS)))
            error = (done.error or {}) if done is not None and done.status != "done" else {}
            if error.get("code") != "rate_limited":
                break
            # GitHub's doing, not this repository's: ask for it again after.
            self.say(f"{repo}: not read (GitHub said to slow down)")
            self.slow_down(error.get("retry_after"))
        if done is not None and done.status == "done":
            self.result.reports_run += 1
            self._upstream = self._limits = 0
            self.say(f"{repo}: {(done.result or {}).get('headline', 'done')}")
            await self.forget_failure(repo)
            return
        code = "timeout" if done is None else error.get("code", "error")
        self.result.reports_failed += 1
        self.result.failures.append(f"{repo}: {'timed out' if done is None else code}")
        self.say(f"{repo}: failed ({code})")
        await self.note_failure(repo, code)
        if code in ("upstream", "timeout"):
            self._upstream += 1
            if self._upstream >= BREAKER_FAILURES:
                self._upstream = 0
                self.pause(BREAKER_PAUSE_S)
                self.say(f"{BREAKER_FAILURES} reports in a row failed on GitHub's side; "
                         f"pausing {minutes(BREAKER_PAUSE_S)}")

    # --- seeds that failed ----------------------------------------------------

    async def failed_last(self, seeds: list[str]) -> list[str]:
        """`seeds` without those that failed lately and aren't due again
        (counted in `skipped_failed`), and with the ones that are due at the
        back, the longest overdue first. A failure older than the seed's
        newest report is forgotten: something made the report since."""
        keys = {repos.key(r) for r in seeds}
        async with self.svc.db.session() as s:
            rows = [f for f in (await s.execute(select(WarmFailure))).scalars()
                    if f.repo_key in keys]
            made = dict((await s.execute(
                select(Report.repo_key, func.max(Report.created_at))
                .where(Report.mode == "rules", Report.days == DAYS,
                       Report.repo_key.in_([f.repo_key for f in rows]))
                .group_by(Report.repo_key))).all()) if rows else {}
            stale = [f.repo_key for f in rows
                     if f.repo_key in made and utc(made[f.repo_key]) > utc(f.last_failed_at)]
            if stale and not self.dry_run:
                await s.execute(delete(WarmFailure).where(WarmFailure.repo_key.in_(stale)))
                await s.commit()
        self._failures = {f.repo_key: f for f in rows if f.repo_key not in stale}
        self._not_found = {k: f.repo for k, f in self._failures.items() if f.code == "not_found"}
        at = now()
        front = [r for r in seeds if repos.key(r) not in self._failures]
        due = sorted((utc(self._failures[repos.key(r)].retry_at), i, r)
                     for i, r in enumerate(seeds) if repos.key(r) in self._failures)
        back = [r for when, _, r in due if when <= at]
        self.result.failed_last = len(back)
        self.result.skipped_failed = len(due) - len(back)
        return front + back

    async def note_failure(self, repo: str, code: str) -> None:
        """Remember that `repo`'s report failed, and when it may be tried again."""
        key, at = repos.key(repo), now()
        if code == "not_found":
            self._not_found[key] = repo
        async with self.svc.db.session() as s:
            row = await s.get(WarmFailure, key)
            if row is None:
                row = WarmFailure(repo_key=key, repo=repo, failures=0, first_failed_at=at)
                s.add(row)
            row.code, row.failures, row.last_failed_at = code[:20], row.failures + 1, at
            row.retry_at = at + retry_delay(code, row.failures)
            await s.commit()

    async def forget_failure(self, repo: str) -> None:
        key = repos.key(repo)
        self._not_found.pop(key, None)
        if self._failures.pop(key, None) is None:
            return
        async with self.svc.db.session() as s:
            await s.execute(delete(WarmFailure).where(WarmFailure.repo_key == key))
            await s.commit()

    def reuse_hours(self, repo: str) -> float:
        """How old a snapshot of `repo` may be and still stand in for a GitHub
        read: its refresh tier's age, which is how stale its report may get
        anyway, or HOLT_EVIDENCE_REUSE_HOURS if longer. 0 when that is 0."""
        s = self.svc.settings
        if s.evidence_reuse_hours <= 0:
            return 0
        tier = (s.refresh_weekly_hours if repos.key(repo) in self._weekly
                else s.refresh_monthly_hours)
        return max(s.evidence_reuse_hours, tier)

    async def from_snapshot(self, repo: str) -> bool:
        """Make `repo`'s outdated report again from its newest kept evidence,
        without GitHub. False (read GitHub instead) when there is none, it is
        older than `reuse_hours`, or older than the report it would replace
        (that one was read while evidence wasn't kept)."""
        hours = self.reuse_hours(repo)
        store = self.svc.evidence
        if not store.enabled or hours <= 0:
            return False
        latest = await self.latest_report(repo)
        snap = await asyncio.to_thread(store.newest, repo)
        if snap is None or latest is None:
            return False
        made = utc(latest.created_at)
        if snap.cutoff < now() - timedelta(hours=hours) or snap.cutoff < made - SNAPSHOT_SLACK:
            return False
        if self.dry_run:
            self.say(f"would make {repo} again from its evidence of {snap.cutoff:%Y-%m-%d}")
            self.result.reports_rederived += 1
            return True
        try:
            report = await asyncio.to_thread(evidence_store.rederive, snap, DAYS)
        except Exception:  # noqa: BLE001 -- GitHub is the way it always worked
            log.exception("making %s again from its evidence failed", repo)
            return False
        async with self.svc.db.session() as s:
            # As old as the report it replaces, never older, so it is the
            # newest and the refresh tiers still see the evidence's real age.
            s.add(Report(repo=snap.repo, repo_key=repos.key(repo), mode="rules", days=DAYS,
                         report=report, engine_version=ENGINE_VERSION,
                         created_at=max(made, snap.cutoff)))
            await s.commit()
        self.result.reports_rederived += 1
        self.say(f"{repo}: {report.get('headline', 'done')} (from evidence of "
                 f"{snap.cutoff:%Y-%m-%d})")
        return True

    async def warm_starter(self, repo: str) -> None:
        from holt_server.api import fetch_starter_issues

        if await self.starter_is_fresh(repo):
            self.result.starter_fresh += 1
            return
        if starter.module() is None or self.dry_run:
            return
        await self.check_budget()
        try:
            await fetch_starter_issues(self.svc, repo)
            self.result.starter_run += 1
        except ApiError as err:
            self.result.failures.append(f"{repo} starter issues: {err.code}")
            if err.code == "rate_limited":
                raise OutOfBudget("GitHub rate limit reached") from err

    async def warm_meta(self, seeds: list[str]) -> None:
        """Details (language, stars, topics...) of every reported repo whose
        copy is missing or a day old, a hundred per query."""
        from holt_server import discover

        stale = await discover.stale_meta(self.svc, seeds)
        batches = discover.batches(stale)
        if self.dry_run:
            if stale:
                self.say(f"would read details of {len(stale)} repos in {len(batches)} "
                         f"quer{'y' if len(batches) == 1 else 'ies'}")
            return
        for batch in batches:
            await self.check_budget()
            before = getattr(self.svc.lookup, "points_used", 0)
            try:
                details = await self.svc.lookup.details(batch)
            except ApiError as err:
                self.result.failures.append(f"repo details: {err.code}")
                if err.code == "rate_limited":
                    raise OutOfBudget("GitHub rate limit reached") from err
                return
            finally:
                self.result.meta_points += (
                    getattr(self.svc.lookup, "points_used", 0) - before)
            self.result.meta_run += await discover.store_meta(self.svc, details)

    async def warm_find(self, profile: Profile) -> None:
        if await self.find_is_fresh(profile):
            self.result.finds_fresh += 1
            return
        label = ", ".join(profile.languages) or "all languages"
        label += " (Hacktoberfest)" if profile.hacktoberfest else ""
        if self.dry_run:
            self.say(f"would search {label}")
            self.result.finds_run += 1
            return
        if starter.module() is None:
            return
        await self.check_budget()
        params = {"languages": list(profile.languages), "topics": [],
                  "hacktoberfest": profile.hacktoberfest, "days": profile.days,
                  "limit": FIND_LIMIT}
        done = await self.run_job(Job(
            kind="find", mode="rules", days=profile.days, params=params,
            priority=BADGE_PRIORITY, dedupe_key=f"find:{profile.key}"))
        if done is None:
            self.result.failures.append(f"find {label}: timed out")
        elif done.status == "done":
            self.result.finds_run += 1
            self.say(f"find {label}: {len((done.result or {}).get('results') or [])} repos")
        else:
            code = (done.error or {}).get("code", "error")
            self.result.failures.append(f"find {label}: {code}")
            if code == "rate_limited":
                raise OutOfBudget("GitHub rate limit reached")

    async def run(self, seeds: list[str], *, reports: bool = True, starter: bool = True,
                  meta: bool = True, finds: bool = True,
                  max_profiles: int | None = None, stale_only: bool = False,
                  tier: str | None = None) -> Result:
        """`stale_only`: only re-run seeds whose report an older engine made;
        `tier`: only the reports of that refresh tier, oldest first. Either
        way the other passes are skipped."""
        if stale_only or tier:
            starter = meta = finds = False
        if tier:
            seeds = await oldest_first(self.svc, await tier_repos(self.svc, tier, seeds))
            self.say(f"{tier} tier: {len(seeds)} repos")
        if stale_only:
            self._weekly = {repos.key(r) for r in await tier_repos(self.svc, "weekly", seeds)}
        total = len(seeds)
        if reports:
            seeds, self.result.quiet_last = await quiet_last(self.svc, seeds)
            seeds = await self.failed_last(seeds)
            if self.result.skipped_failed or self.result.failed_last:
                self.say(f"{self.result.skipped_failed} seeds skipped as recently failed; "
                         f"{self.result.failed_last} that failed before go last")
            if self.parallel > 1:
                self.say(f"{self.parallel} reports at a time")
        try:
            # Reports first: finds screen repositories through the report
            # cache, so a warm report cache makes every search cheaper.
            if reports or starter:
                await self.each_seed(seeds, lambda repo: self.warm_seed(
                    repo, reports=reports, starter=starter, stale_only=stale_only))
            if meta:
                await self.warm_meta(seeds)
            if finds:
                for profile in profiles()[:max_profiles]:
                    await self.warm_find(profile)
        except OutOfBudget as stop:
            self.result.stopped = str(stop)
            self.say(f"stopping: {stop}")
        if reports:
            r = self.result
            made = r.reports_fresh + r.reports_rederived + (0 if self.dry_run else r.reports_run)
            r.left = total - made
            r.not_found = sorted(self._not_found.values(), key=str.lower)
        return self.result

    async def warm_seed(self, repo: str, *, reports: bool, starter: bool,
                        stale_only: bool) -> None:
        if reports:
            await self.warm_report(repo, stale_only)
        if starter:
            await self.warm_starter(repo)

    async def each_seed(self, seeds: list[str], work) -> None:
        """`await work(repo)` for each seed, taken in order, `parallel` at a
        time. The first OutOfBudget stops new seeds; the ones under way
        finish, then it is raised."""
        todo = iter(seeds)
        stops: list[OutOfBudget] = []
        self._queue = len(seeds)

        async def worker() -> None:
            for repo in todo:
                try:
                    await work(repo)
                except OutOfBudget as stop:
                    stops.append(stop)
                if stops:
                    return
                self.looked_at()

        async with asyncio.TaskGroup() as group:
            for _ in range(min(self.parallel, len(seeds))):
                group.create_task(worker())
        if stops:
            raise stops[0]


    def looked_at(self) -> None:
        """One more seed done with; a "progress:" line every PROGRESS_EVERY."""
        self._looked_at += 1
        if self.dry_run or (self._looked_at % PROGRESS_EVERY and self._looked_at != self._queue):
            return
        r = self.result
        self.say(f"progress: {self._looked_at} of {self._queue} seeds looked at: "
                 f"{r.reports_run} reports run, {r.reports_fresh} fresh, "
                 f"{r.reports_failed} failed; {r.skipped_failed} skipped as recently failed; "
                 f"{self._queue - self._looked_at} to go")


async def tier_repos(svc, tier: str, seeds: list[str]) -> list[str]:
    """The repos of refresh tier `tier`: "weekly", every repo someone saved,
    viewed in the last INTEREST_DAYS, or has an open pull request on with
    alerts turned on (PR watch needs the report's timing), seed or not;
    "monthly", the seeds that aren't weekly."""
    if tier not in TIERS:
        raise ValueError(f"no refresh tier {tier!r}; one of {', '.join(TIERS)}")
    since = now() - timedelta(days=INTEREST_DAYS)
    async with svc.db.session() as s:
        rows = [*(await s.execute(select(SavedRepo.repo_key, SavedRepo.repo))).all(),
                *(await s.execute(select(RepoView.repo_key, RepoView.repo)
                                  .where(RepoView.last_viewed_at >= since))).all(),
                *(await s.execute(
                    select(Contribution.repo_key, Contribution.repo)
                    .join(AlertSettings, AlertSettings.user_id == Contribution.user_id)
                    .where(AlertSettings.enabled.is_(True), Contribution.state == "open")
                    .distinct())).all()]
    weekly: dict[str, str] = {}
    for key, repo in rows:
        weekly.setdefault(key, repo)
    if tier == "weekly":
        return list(weekly.values())
    return [r for r in seeds if repos.key(r) not in weekly]


async def oldest_first(svc, names: list[str]) -> list[str]:
    """`names` by their newest 7-day rules report, oldest first; never
    reported ones first of all, in the order given."""
    async with svc.db.session() as s:
        made = dict((await s.execute(
            select(Report.repo_key, func.max(Report.created_at))
            .where(Report.mode == "rules", Report.days == DAYS,
                   Report.repo_key.in_([repos.key(r) for r in names]))
            .group_by(Report.repo_key))).all())

    def order(item: tuple[int, str]):
        i, repo = item
        when = made.get(repos.key(repo))
        return (0, i, None) if when is None else (1, utc(when), i)

    return [repo for _, repo in sorted(enumerate(names), key=order)]


async def quiet_last(svc, names: list[str]) -> tuple[list[str], int]:
    """`names` in their order, but those that can't take outside work now at
    the back, and how many that is: the last report was decided by a
    QUIET_RULES rule (archived, pull requests closed to outsiders in GitHub's
    settings, inactive), or repo_meta says archived or no push in
    DORMANT_DAYS. Only what Holt already has; nothing is read from GitHub."""
    keys = [repos.key(r) for r in names]
    latest = (select(func.max(Report.id).label("id"))
              .where(Report.mode == "rules", Report.days == DAYS, Report.repo_key.in_(keys))
              .group_by(Report.repo_key).subquery())
    async with svc.db.session() as s:
        codes = (await s.execute(select(Report.repo_key, Report.report["rule_codes"])
                                 .join(latest, Report.id == latest.c.id))).all()
        meta = (await s.execute(select(RepoMeta.repo_key, RepoMeta.archived, RepoMeta.pushed_at)
                                .where(RepoMeta.repo_key.in_(keys)))).all()
    since = now() - timedelta(days=DORMANT_DAYS)
    quiet = {key for key, rules in codes if QUIET_RULES & set(rules or [])}
    quiet |= {key for key, archived, pushed in meta
              if archived or (pushed is not None and utc(pushed) < since)}
    front = [r for r in names if repos.key(r) not in quiet]
    return front + [r for r in names if repos.key(r) in quiet], len(names) - len(front)


async def warm_once(svc, *, seeds: list[str] | None = None, dry_run: bool = False,
                    say: Callable[[str], None] = log.info, parallel: int | None = None,
                    wait_for_budget: bool = False, **passes) -> Result | None:
    """One pass. On Postgres, only one process warms at a time (advisory lock);
    returns None if another holds it."""
    seeds = seeds if seeds is not None else load_seeds(svc.settings.warm_seeds_file or None)

    def warmer() -> Warmer:
        return Warmer(svc, say, dry_run, parallel=parallel, wait_for_budget=wait_for_budget)

    async with svc.db.advisory_lock(LOCK_ID) as got:
        if not got:
            say("another process is warming; skipped")
            return None
        return await warmer().run(seeds, **passes)


async def schedule(svc, first_delay_s: float = 60.0) -> None:
    """Warm every HOLT_WARM_INTERVAL_HOURS, in the API process, until cancelled."""
    hours = svc.settings.warm_interval_hours
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            result = await warm_once(svc)
            if result is not None:
                log.info("warm pass: %s", result.summary())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- try again next time
            log.exception("warm pass failed")
        await asyncio.sleep(hours * 3600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m holt_server.warm",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", help="seed list (default: the one shipped in the package)")
    parser.add_argument("--limit", type=int, help="only the first N seed repositories")
    parser.add_argument("--no-reports", action="store_true")
    parser.add_argument("--no-starter", action="store_true")
    parser.add_argument("--no-meta", action="store_true",
                        help="don't read repository details (Discover)")
    parser.add_argument("--no-find", action="store_true")
    parser.add_argument("--profiles", type=int, help="only the first N find profiles")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would run; no GitHub calls, no jobs")
    parser.add_argument("--tier", choices=TIERS,
                        help="only the reports of this refresh tier, oldest first: weekly "
                             "(saved or recently viewed repos) or monthly (the other seeds)")
    parser.add_argument("--parallel", type=int,
                        help="report jobs in flight at once (default HOLT_WARM_PARALLEL, 3)")
    parser.add_argument("--wait-for-budget", action="store_true",
                        help="when GitHub points run low, wait for them to come back "
                             "instead of stopping")
    parser.add_argument("--stale-only", action="store_true",
                        help="only re-run seeds whose report an older engine version "
                             "made, however young (after a deploy); nothing else")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from holt_server.services import Services
    from holt_server.settings import get_settings

    async def run() -> int:
        svc = Services(get_settings())
        await svc.db.migrate()
        # Reports and finds are jobs, which this process works too. Starter
        # issues and details are read directly, so a details-only pass
        # never picks up anyone's job.
        works_queue = not args.dry_run and not (args.no_reports and args.no_find)
        if works_queue:
            await svc.runner.start()
        try:
            seeds = load_seeds(args.seeds or svc.settings.warm_seeds_file or None)
            if args.limit:
                seeds = seeds[: args.limit]
            result = await warm_once(svc, seeds=seeds, dry_run=args.dry_run, say=print,
                                     reports=not args.no_reports,
                                     starter=not args.no_starter, meta=not args.no_meta,
                                     finds=not args.no_find,
                                     max_profiles=args.profiles, parallel=args.parallel,
                                     wait_for_budget=args.wait_for_budget,
                                     stale_only=args.stale_only, tier=args.tier)
            if result is None:
                return BUSY
            print(result.summary())
            for failure in result.failures:
                print(f"  failed: {failure}")
            if result.not_found:
                print("  not on GitHub (renamed away or deleted; fix the seed list): "
                      + ", ".join(result.not_found))
            return 0
        finally:
            if works_queue:
                await svc.runner.stop()
            svc.http.close()
            await svc.db.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
