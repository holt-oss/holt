"""Warm the caches before people arrive: popular repos' reports and starter
issues, and the /find searches the web app's default pages make.

    python -m holt_server.warm                 # everything, stopping on GitHub budget
    python -m holt_server.warm --dry-run       # what would run, no GitHub calls
    python -m holt_server.warm --no-find --limit 50

Or in the API process on a schedule: HOLT_WARM_INTERVAL_HOURS=6.

How it stays out of the way:

* Reports go through the normal job queue at badge priority, so every user
  request runs first, and the runner's badge lane allows one at a time. The
  pass itself waits for each job before queueing the next.
* Fresh work is skipped: reports under HOLT_WARM_MAX_AGE_HOURS (20), finds
  and starter issues still inside most of their cache lifetime.
* Before each step it checks the GitHub GraphQL points left on every token
  and stops below HOLT_WARM_MIN_POINTS, so a warm pass can never starve the
  requests people make.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, text

from holt_server import repos
from holt_server.db import (
    ACTIVE,
    BADGE_PRIORITY,
    FindCache,
    Job,
    Report,
    StarterCache,
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
# Budget is checked before the first step and then every this many steps.
BUDGET_EVERY = 5
# A job that never finishes fails its repository and the pass goes on; this
# many in a row means nothing is working the queue, and the pass stops.
MAX_TIMEOUTS_IN_A_ROW = 3
# Refresh a cached find or starter list once this share of its lifetime is gone.
REFRESH_AFTER = 0.8
FIND_LIMIT = 20
LOCK_ID = 7_406_111

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


@dataclass
class Result:
    reports_run: int = 0
    reports_fresh: int = 0
    reports_failed: int = 0
    starter_run: int = 0
    starter_fresh: int = 0
    finds_run: int = 0
    finds_fresh: int = 0
    stopped: str | None = None
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"reports {self.reports_run} run, {self.reports_fresh} fresh, "
                 f"{self.reports_failed} failed",
                 f"starter issues {self.starter_run} run, {self.starter_fresh} fresh",
                 f"finds {self.finds_run} run, {self.finds_fresh} fresh"]
        if self.stopped:
            parts.append(f"stopped: {self.stopped}")
        return "; ".join(parts)


class OutOfBudget(Exception):
    pass


class Warmer:
    def __init__(self, svc, say: Callable[[str], None] = log.info, dry_run: bool = False):
        self.svc = svc
        self.say = say
        self.dry_run = dry_run
        self.result = Result()
        self._steps = 0
        self._timeouts = 0

    # --- budget -------------------------------------------------------------

    async def check_budget(self) -> None:
        if self.dry_run:
            return
        self._steps += 1
        if (self._steps - 1) % BUDGET_EVERY:
            return
        floor = self.svc.settings.warm_min_points
        remaining = await self.svc.lookup.remaining()
        if remaining < floor:
            raise OutOfBudget(f"GitHub points left {remaining} < {floor}")

    # --- freshness ----------------------------------------------------------

    async def report_is_fresh(self, repo: str) -> bool:
        cutoff = now() - timedelta(hours=self.svc.settings.warm_max_age_hours)
        async with self.svc.db.session() as s:
            created = (await s.execute(
                select(Report.created_at).where(
                    Report.repo_key == repos.key(repo), Report.mode == "rules",
                    Report.days == DAYS)
                .order_by(Report.created_at.desc()).limit(1))).scalar_one_or_none()
        return created is not None and utc(created) >= cutoff

    async def starter_is_fresh(self, repo: str) -> bool:
        ttl = timedelta(hours=self.svc.settings.starter_cache_hours * REFRESH_AFTER)
        async with self.svc.db.session() as s:
            row = await s.get(StarterCache, repos.key(repo))
        return row is not None and utc(row.created_at) >= now() - ttl

    async def find_is_fresh(self, profile: Profile) -> bool:
        ttl = timedelta(hours=self.svc.settings.find_cache_hours * REFRESH_AFTER)
        async with self.svc.db.session() as s:
            row = await s.get(FindCache, profile.key)
        return row is not None and utc(row.created_at) >= now() - ttl

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

    async def warm_report(self, repo: str) -> None:
        if await self.report_is_fresh(repo):
            self.result.reports_fresh += 1
            return
        if self.dry_run:
            self.say(f"would analyse {repo}")
            self.result.reports_run += 1
            return
        await self.check_budget()
        key = repos.key(repo)
        done = await self.run_job(Job(
            kind="analysis", repo=repo, repo_key=key, mode="rules", days=DAYS, params={},
            priority=BADGE_PRIORITY, dedupe_key=dedupe_key(key, "rules", DAYS)))
        if done is None:
            self.result.reports_failed += 1
            self.result.failures.append(f"{repo}: timed out")
        elif done.status == "done":
            self.result.reports_run += 1
            self.say(f"{repo}: {(done.result or {}).get('headline', 'done')}")
        else:
            self.result.reports_failed += 1
            code = (done.error or {}).get("code", "error")
            self.result.failures.append(f"{repo}: {code}")
            self.say(f"{repo}: failed ({code})")
            if code == "rate_limited":
                raise OutOfBudget("GitHub rate limit reached")

    async def warm_starter(self, repo: str) -> None:
        from holt_server import starter
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

    async def warm_find(self, profile: Profile) -> None:
        from holt_server import starter

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
                  finds: bool = True, max_profiles: int | None = None) -> Result:
        try:
            # Reports first: finds screen repositories through the report
            # cache, so a warm report cache makes every search cheaper.
            for repo in seeds:
                if reports:
                    await self.warm_report(repo)
                if starter:
                    await self.warm_starter(repo)
            if finds:
                for profile in profiles()[:max_profiles]:
                    await self.warm_find(profile)
        except OutOfBudget as stop:
            self.result.stopped = str(stop)
            self.say(f"stopping: {stop}")
        return self.result


async def warm_once(svc, *, seeds: list[str] | None = None, dry_run: bool = False,
                    say: Callable[[str], None] = log.info, **passes) -> Result | None:
    """One pass. On Postgres, only one process warms at a time (advisory lock);
    returns None if another holds it."""
    seeds = seeds if seeds is not None else load_seeds(svc.settings.warm_seeds_file or None)
    if svc.db.engine.dialect.name != "postgresql":
        return await Warmer(svc, say, dry_run).run(seeds, **passes)
    async with svc.db.engine.connect() as conn:
        got = (await conn.execute(text("SELECT pg_try_advisory_lock(:id)"),
                                  {"id": LOCK_ID})).scalar()
        if not got:
            say("another process is warming; skipped")
            return None
        try:
            return await Warmer(svc, say, dry_run).run(seeds, **passes)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


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
    parser.add_argument("--no-find", action="store_true")
    parser.add_argument("--profiles", type=int, help="only the first N find profiles")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would run; no GitHub calls, no jobs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from holt_server.services import Services
    from holt_server.settings import get_settings

    async def run() -> int:
        svc = Services(get_settings())
        await svc.db.create_all()
        if not args.dry_run:
            await svc.runner.start()  # this process works the queue too
        try:
            seeds = load_seeds(args.seeds or svc.settings.warm_seeds_file or None)
            if args.limit:
                seeds = seeds[: args.limit]
            result = await warm_once(svc, seeds=seeds, dry_run=args.dry_run, say=print,
                                     reports=not args.no_reports,
                                     starter=not args.no_starter, finds=not args.no_find,
                                     max_profiles=args.profiles)
            if result is None:
                return 1
            print(result.summary())
            for failure in result.failures:
                print(f"  failed: {failure}")
            return 0
        finally:
            if not args.dry_run:
                await svc.runner.stop()
            svc.http.close()
            await svc.db.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
