"""The in-process jobs runner.

Jobs live in the `jobs` table, so a queued job survives a restart and every
API process sees the same state. Each runs in a worker thread because the
engine is synchronous, in one of two lanes:

* the user lane, `HOLT_JOB_CONCURRENCY` workers, runs only people's jobs;
* the background lane, `HOLT_BADGE_CONCURRENCY` workers, runs badge refreshes
  and warm passes, but takes a person's queued job first whenever one is
  waiting. So background work never holds a worker a person needs, and yields
  to people when there is a queue.

Every job has a time limit (`HOLT_JOB_TIMEOUT_*`). Past it the job fails with
a plain "took too long" error, and its thread is told to stop at its next
GitHub call or progress step (a thread can't be killed from outside). Job
threads come from the runner's own executor, sized with room for such
leftovers, so they never starve the loop's default executor (repo lookups,
starter issues) or the jobs that follow.

Progress goes to the table (for polling) and to an in-memory hub (for SSE
subscribers in this process); SSE also re-reads the table, so it keeps working
if the job runs in another process. A queued job's subscribers also hear its
place in the queue each time it moves.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from holt.types import EvidenceRecord

from holt_server import budget, entitlements, starter
from holt_server.db import (
    ACTIVE,
    BADGE_PRIORITY,
    ENGINE_VERSION,
    FindCache,
    Job,
    Report,
    current_engine,
    dedupe_key,
    find_key,
    now,
)
from holt_server.engine import RecordingProvider
from holt_server.errors import ApiError
from holt_server.github import JobStopped, background, job_stop
from holt_server.meta_refresh import MetaRefresher

if TYPE_CHECKING:
    from holt_server.services import Services

log = logging.getLogger("holt_server.jobs")

POLL_SECONDS = 5.0
# A running job's runner touches `heartbeat_at` this often. One not touched for
# STALE_AFTER belonged to a process that died, and is queued again.
HEARTBEAT_SECONDS = 15.0
STALE_AFTER = timedelta(seconds=90)
# Queue positions are counted over at most this many queued jobs.
QUEUE_SCAN = 2000

# How long a finished report waits for its repo's details (README, links,
# stars...) before it's announced without them. One GitHub query, usually ~1 s.
META_WAIT_S = 8.0

USER_LANE = "user"
BACKGROUND_LANE = "background"


def timed_out() -> ApiError:
    return ApiError(
        "upstream",
        "This check took too long, so we stopped it. GitHub may be slow right now, "
        "or the repository is very busy. Please try again in a few minutes.",
    )


def waiting_stage(position: int) -> str:
    """Plain-English stage for a queued job; `position` 1 is next to start."""
    if position <= 1:
        return "In the queue: yours is next"
    ahead = position - 1
    return f"In the queue: {ahead} {'check' if ahead == 1 else 'checks'} ahead of yours"


class Hub:
    """Fan-out of job events to SSE subscribers in this process."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subs[job_id].add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subs.pop(job_id, None)

    def watched(self) -> list[str]:
        return list(self._subs)

    def publish(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in list(self._subs.get(job_id, ())):
            queue.put_nowait((event, data))


class JobRunner:
    def __init__(self, services: Services, concurrency: int = 2,
                 badge_concurrency: int = 1) -> None:
        self.services = services
        # User lane workers; they never take badge work.
        self.concurrency = max(1, concurrency)
        # Background lane workers (badge refreshes, warm passes). They take the
        # lowest priority number first, so a waiting person's job always goes
        # before badge work. 0 turns badge work off entirely.
        self.badge_concurrency = max(0, badge_concurrency)
        # Job threads: one per worker, and as many again for threads of timed-out
        # jobs that haven't reached their next stop check yet.
        self.executor_size = 2 * (self.concurrency + self.badge_concurrency)
        self._executor: ThreadPoolExecutor | None = None
        self.hub = Hub()
        self.worker_id = uuid.uuid4().hex
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._running: dict[str, int] = {}  # job id -> priority, jobs this runner holds
        self._models: dict[str, budget.Capped] = {}  # running AI reports' model clients
        # Reads a reported repo's details (Discover) after its report is stored.
        self.meta = MetaRefresher(services)
        self.meta_wait = META_WAIT_S
        self._stopping = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._stopping = False
        self._executor = ThreadPoolExecutor(self.executor_size,
                                            thread_name_prefix="holt-job-thread")
        await self.requeue_stale()
        self._tasks = [asyncio.create_task(self._worker(i, USER_LANE), name=f"holt-job-{i}")
                       for i in range(self.concurrency)]
        self._tasks += [asyncio.create_task(self._worker(i, BACKGROUND_LANE),
                                            name=f"holt-background-{i}")
                        for i in range(self.badge_concurrency)]
        log.info("job runner started: %d user worker(s), %d background worker(s)",
                 self.concurrency, self.badge_concurrency)
        self._tasks.append(asyncio.create_task(self._heartbeat(), name="holt-heartbeat"))

    async def requeue_stale(self) -> int:
        """Queue again the running jobs whose runner stopped heartbeating.

        Only stale ones: a job another live process is running keeps its
        heartbeat fresh and is left alone. The engine is read-only, so running
        a dead process's job again is safe.
        """
        cutoff = now() - STALE_AFTER
        async with self.services.db.session() as s:
            result = await s.execute(
                update(Job).where(Job.status == "running",
                                  (Job.heartbeat_at < cutoff) | Job.heartbeat_at.is_(None))
                .values(status="queued", stage="Waiting to start", progress=0.0,
                        worker_id=None, heartbeat_at=None))
            await s.commit()
        if result.rowcount:
            log.warning("requeued %d stale job(s)", result.rowcount)
            self.wake()
        return result.rowcount

    async def _heartbeat(self) -> None:
        while not self._stopping:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                if self._running:
                    async with self.services.db.session() as s:
                        await s.execute(update(Job).where(
                            Job.id.in_(list(self._running)), Job.worker_id == self.worker_id,
                            Job.status == "running").values(heartbeat_at=now()))
                        await s.commit()
                await self.requeue_stale()
            except Exception:  # noqa: BLE001 -- try again next beat
                log.exception("heartbeat failed")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await self.meta.stop()
        if self._executor is not None:
            # Don't wait: a leftover thread notices its stop flag on its own.
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def wake(self) -> None:
        self._wake.set()

    # --- the loop -----------------------------------------------------------

    async def _worker(self, index: int, lane: str = USER_LANE) -> None:
        while not self._stopping:
            try:
                job = await self._claim(lane)
            except Exception:  # noqa: BLE001 -- the database blinked; keep going
                log.exception("claiming a job failed")
                job = None
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)
                except TimeoutError:
                    pass
                continue
            try:
                await self.announce_queue()
            except Exception:  # noqa: BLE001 -- positions are a nicety
                log.exception("announcing queue positions failed")
            try:
                await self._run(job, lane)
            finally:
                self._running.pop(job.id, None)

    async def _claim(self, lane: str = USER_LANE) -> Job | None:
        query = select(Job.id, Job.priority).where(Job.status == "queued")
        badges = sum(1 for p in self._running.values() if p >= BADGE_PRIORITY)
        if lane == USER_LANE or badges >= self.badge_concurrency:
            query = query.where(Job.priority < BADGE_PRIORITY)
        async with self.services.db.session() as s:
            rows = (await s.execute(
                query.order_by(Job.priority, Job.created_at).limit(5))).all()
            for job_id, priority in rows:
                claimed = await s.execute(
                    update(Job).where(Job.id == job_id, Job.status == "queued")
                    .values(status="running", started_at=now(), stage="Starting",
                            progress=0.01, worker_id=self.worker_id, heartbeat_at=now())
                )
                await s.commit()
                if claimed.rowcount == 1:
                    self._running[job_id] = priority
                    return await s.get(Job, job_id)
        return None

    # --- queue position -------------------------------------------------------

    async def queue_positions(self, job_ids: list[str] | None = None) -> dict[str, int]:
        """Place in the queue (1 = next to start) of each queued job, or of `job_ids`."""
        async with self.services.db.session() as s:
            rows = (await s.execute(
                select(Job.id).where(Job.status == "queued")
                .order_by(Job.priority, Job.created_at, Job.id).limit(QUEUE_SCAN))).scalars()
            order = {job_id: i + 1 for i, job_id in enumerate(rows)}
        if job_ids is None:
            return order
        return {j: order[j] for j in job_ids if j in order}

    async def stage_event(self, job: Job) -> dict[str, Any]:
        """The `stage` SSE payload for `job` as the table has it, with its
        place in the queue while it waits."""
        if job.status == "queued":
            position = (await self.queue_positions([job.id])).get(job.id)
            if position is not None:
                return {"stage": waiting_stage(position), "progress": 0.0,
                        "queue_position": position}
        return {"stage": job.stage, "progress": round(job.progress or 0.0, 3)}

    async def announce_queue(self) -> None:
        """Tell this process's SSE subscribers where their queued jobs now are."""
        watched = self.hub.watched()
        if not watched:
            return
        for job_id, position in (await self.queue_positions(watched)).items():
            # Positions are a snapshot: a job this runner claimed since then
            # has already told its subscribers it started.
            if job_id in self._running:
                continue
            self.hub.publish(job_id, "stage", {"stage": waiting_stage(position),
                                               "progress": 0.0, "queue_position": position})

    # --- running --------------------------------------------------------------

    def timeout_for(self, job: Job) -> float:
        # Here, not at the top: it imports the API module, which imports this one.
        from holt_server import merge_plan

        s = self.services.settings
        if job.kind == "find":
            return s.job_timeout_find
        if job.kind == "merge_plan":
            return merge_plan.time_limit(s)
        # Playbook jobs are AI work too (mode "ai"): the service may read
        # GitHub and then wait on a model for up to 300 s.
        return s.job_timeout_ai if job.mode == "ai" else s.job_timeout_rules

    async def _run(self, job: Job, lane: str = USER_LANE) -> None:
        # Here, not at the top: these import the API module, which imports this one.
        from holt_server import merge_plan, playbook, preflight

        loop = asyncio.get_running_loop()
        self.hub.publish(job.id, "stage", {"stage": "Starting", "progress": 0.01})
        started = time.monotonic()
        waited = (now() - _aware(job.created_at)).total_seconds() if job.created_at else 0.0
        what = f"{job.kind}/{job.mode}" if job.kind == "analysis" else job.kind
        log.info("job %s started: %s %s, %s lane, waited %.0fs", job.id, what,
                 job.repo or "", lane, waited)
        self.services.metrics.job_started(job, lane, waited)
        outcome = "error"
        stop = threading.Event()
        evidence: Evidence | None = None
        # One writer applies the job's progress steps in the order they were
        # emitted. A coroutine per step let a slow write land after a later
        # one, so the table and SSE subscribers saw progress go backwards.
        steps: asyncio.Queue[tuple[str, float] | None] = asyncio.Queue()
        writer = asyncio.create_task(self._write_progress(job.id, steps))

        def emit(stage: str, progress: float) -> None:
            if stop.is_set():
                raise JobStopped
            loop.call_soon_threadsafe(steps.put_nowait, (stage, progress))

        limit = self.timeout_for(job)
        try:
            try:
                # AI work claims its hold on the budget, or fails (refunded) without one.
                await budget.start(self.services, job)
                if job.kind == "find":
                    result = await self.in_thread(stop, limit, self._find_sync, job, emit, loop)
                elif job.kind == "playbook":
                    # An HTTP call to the paid-features service: no thread needed.
                    result = await self._in_loop(stop, limit, playbook.write(
                        self.services, job, emit))
                elif job.kind == "preflight":
                    # An HTTP call to the paid-features service: no thread needed.
                    result = await self._in_loop(stop, limit, preflight.run(
                        self.services, job, emit))
                elif job.kind == "merge_plan":
                    # The AI stages, when it runs them, get a thread of their own
                    # (`in_thread`); the rest is an HTTP call to the service.
                    result = await self._in_loop(stop, limit, merge_plan.run(
                        self.services, job, emit))
                else:
                    # The key is only ever held in memory: the jobs table records
                    # where it came from, not what it is.
                    spec = await self.services.model_spec_for(job) if job.mode == "ai" else None
                    result, evidence = await self.in_thread(stop, limit, self._analysis_sync,
                                                             job, spec, emit)
            finally:
                # Steps emitted so far are written before the job ends, so
                # `done` or `error` is the last event a subscriber hears. The
                # end goes through `call_soon` as they do, so it can't overtake
                # one emitted just before a job returned without yielding.
                loop.call_soon(steps.put_nowait, None)
                await writer
        except JobTimedOut:
            outcome = "timeout"
            log.warning("job %s timed out after %.0fs (%s %s)", job.id, limit, what,
                        job.repo or "")
            # It may still be running, and spending: it keeps its whole hold.
            self.services.ai_costs[job.id] = None
            await self._fail(job, timed_out())
        except ApiError as err:
            log.warning("job %s failed after %.1fs: %s", job.id,
                        time.monotonic() - started, err.code)
            await self._fail(job, err)
        except Exception:  # noqa: BLE001
            log.exception("job %s crashed", job.id)
            await self._fail(job, ApiError(
                "internal", "Something went wrong on our side. Please try again in a minute."))
        else:
            outcome = "done"
            log.info("job %s done in %.1fs", job.id, time.monotonic() - started)
            await self._finish(job, result, evidence)
        finally:
            self.services.metrics.job_finished(job, lane, outcome,
                                               time.monotonic() - started)

    async def in_thread(self, stop: threading.Event, limit: float, fn, *args) -> Any:
        """`fn(*args)` on the runner's executor, for at most `limit` seconds.

        On timeout `stop` is set, which the thread notices at its next GitHub
        call (`github.job_stop`) or progress step; whatever it returns after
        that is dropped.
        """
        if self._executor is None:  # not started (tests driving _run directly)
            self._executor = ThreadPoolExecutor(self.executor_size,
                                                thread_name_prefix="holt-job-thread")
        # run_in_executor doesn't copy contextvars the way to_thread does.
        ctx = contextvars.copy_context()
        ctx.run(job_stop.set, stop)
        work = asyncio.get_running_loop().run_in_executor(
            self._executor, functools.partial(ctx.run, fn, *args))
        done, _ = await asyncio.wait({work}, timeout=limit)
        if not done:
            stop.set()
            # Nobody awaits it any more; keep its late error out of the log.
            work.add_done_callback(lambda f: f.cancelled() or f.exception())
            raise JobTimedOut
        return work.result()

    async def _in_loop(self, stop: threading.Event, limit: float, work) -> Any:
        """Await `work` for at most `limit` seconds; past it, cancel it."""
        try:
            return await asyncio.wait_for(work, limit)
        except TimeoutError:
            stop.set()
            raise JobTimedOut from None

    def _analysis_sync(self, job: Job, spec, emit) -> tuple[dict[str, Any], Evidence]:
        """The report, and the evidence it read (for the evidence store)."""
        svc = self.services
        # Nobody waits on a badge refresh or a warm report (github.background).
        background.set(job.priority >= BADGE_PRIORITY)
        model = None
        if job.mode == "ai":
            model = budget.Capped(svc.model_factory(spec), spec.model,
                                  budget.run_max_usd(svc.settings, budget.ANALYSIS))
            # What it has spent so far, for `_fail` if the run stops early.
            self._models[job.id] = model
        return read_repo(svc, job.repo, job.mode, job.days, model, emit)

    def _find_sync(self, job: Job, emit, loop) -> dict[str, Any]:
        from holt_server import find

        svc = self.services

        def cached(repo: str) -> dict[str, Any] | None:
            # Called from find's worker threads; the database lives on the loop.
            return asyncio.run_coroutine_threadsafe(
                fresh_rules_report(svc, repo, job.days), loop).result(timeout=30)

        return find.run(svc, job.params or {}, job.days, emit, loop, cached)

    # --- state changes ------------------------------------------------------

    def _mine(self, job_id: str):
        """Writes to a job only while this runner still holds it. If it was
        requeued as stale and picked up elsewhere, this runner's result is dropped."""
        return update(Job).where(Job.id == job_id, Job.status == "running",
                                 Job.worker_id == self.worker_id)

    async def _dressed(self, repo: str, result: dict[str, Any]) -> dict[str, Any]:
        """`result` as the report page is served it (api.dressed), its repo's
        details read first if there are none yet. Never raises: without them,
        the report is still announced."""
        from holt_server import api, schema

        try:
            await asyncio.wait_for(self.meta.read_now(repo), self.meta_wait)
        except TimeoutError:
            # GitHub is slow: announce the report now and read them after it.
            self.meta.note(repo)
        except Exception as exc:  # noqa: BLE001 -- the report goes out regardless
            log.warning("reading %s's details before its report failed: %s",
                        repo, getattr(exc, "code", None) or type(exc).__name__)
        try:
            report = await api.dressed(self.services, schema.Report.model_validate(result), repo)
        except Exception:  # noqa: BLE001
            log.exception("adding details to %s's report failed", repo)
            return result
        extra = report.model_dump(mode="json", include={"about", "holt_users"})
        return {**result, **extra}

    async def _write_progress(self, job_id: str,
                              steps: asyncio.Queue[tuple[str, float] | None]) -> None:
        """Record a job's progress steps one at a time until `None`."""
        while (step := await steps.get()) is not None:
            try:
                await self._progress(job_id, *step)
            except Exception:  # noqa: BLE001 -- a missed step shouldn't fail the job
                log.exception("recording progress for job %s failed", job_id)

    async def _progress(self, job_id: str, stage: str, progress: float) -> None:
        async with self.services.db.session() as s:
            await s.execute(self._mine(job_id).values(
                stage=stage[:80], progress=progress, heartbeat_at=now()))
            await s.commit()
        self.hub.publish(job_id, "stage", {"stage": stage, "progress": progress})

    async def _finish(self, job: Job, result: dict[str, Any],
                      evidence: Evidence | None = None) -> None:
        # Here, not at the top: these import the API module, which imports this one.
        from holt_server import discover, find, merge_plan, playbook, preflight

        model_id = self._ai_model(job)
        cost = self._ai_cost(job, result)
        shown = result
        if job.kind == "find":
            # The search is cached on its own; the job answers with the index
            # first (find.py), as a cached search is served.
            async with self.services.db.session() as s:
                result = {**result, "results": await discover.with_meta(
                    s, list(result.get("results") or []))}
            index = await find.index_results(self.services, {**(job.params or {}),
                                                             "days": job.days})
            limit = int((job.params or {}).get("limit") or 20)
            shown = {**result, "results": find.merge(index, result["results"])[:limit]}
        elif job.kind == "analysis" and job.repo:
            # The page shows the report as announced: give it what a stored
            # report is served with, so nothing appears only after a reload.
            shown = await self._dressed(job.repo, result)
        async with self.services.db.session() as s:
            done = await s.execute(self._mine(job.id).values(
                status="done", stage="Done", progress=1.0, result=shown,
                finished_at=now()))
            if done.rowcount != 1:
                await s.rollback()
                return
            if job.kind == "analysis":
                s.add(Report(repo=job.repo, repo_key=job.repo_key, mode=job.mode,
                             days=job.days, report=result, engine_version=ENGINE_VERSION))
            elif job.kind == "find":
                await store_find(s, job.params or {}, job.days, result)
            elif job.kind == "playbook":
                await playbook.store(s, job, result)
            elif job.kind == "preflight":
                await preflight.store(s, job, result)
            elif job.kind == "merge_plan":
                await merge_plan.store(s, job, result)
            if budget.kind_of(job):
                await budget.settle(s, job.id, cost, model_id)
            await s.commit()
        self.hub.publish(job.id, "done", done_payload(job.kind, shown))
        if job.kind == "analysis" and job.repo:
            if evidence is not None and evidence.records:
                await self.keep_evidence(job.repo, evidence)
        if job.kind == "find":
            await self._queue_found(result)

    async def keep_evidence(self, repo: str, evidence: Evidence) -> None:
        """Write the report's evidence to the store, after the report itself.
        Never fails the job: the store logs its own errors."""
        try:
            await asyncio.to_thread(self.services.evidence.save, repo, evidence.records,
                                    evidence.cutoff, evidence.judges_recency)
        except Exception:  # noqa: BLE001 -- the report is already stored and sent
            log.exception("keeping the evidence of %s failed", repo)

    async def _queue_found(self, result: dict[str, Any]) -> None:
        """Queue a background rules report for the first few repositories a
        search found that have none fresh. The search screened them at a
        lighter depth and stored no report, so without this a repository
        listed "Worth your time" opened on "not checked yet".

        Bounded: `FOUND_PER_SEARCH` per search, nothing while
        `FOUND_QUEUE_MAX` background jobs already wait or the tokens are
        below the warm pass's floor, one job per repository, and all of it on
        the background lane, which a person's own check never waits behind."""
        svc = self.services
        left = svc.pool.points_left()
        if left is not None and left < svc.settings.warm_min_points:
            log.info("not queueing reports for found repos: %d GitHub points left", left)
            return
        found = [r["repo"] for r in result.get("results") or []
                  if isinstance(r, dict) and r.get("repo")][:FOUND_PER_SEARCH]
        for repo in found:
            try:
                if await any_fresh_rules_report(svc, repo):
                    continue
                key = repo.lower()
                async with svc.db.session() as s:
                    waiting = (await s.execute(select(func.count()).select_from(Job).where(
                        Job.status == "queued", Job.priority >= BADGE_PRIORITY))).scalar_one()
                    if waiting >= FOUND_QUEUE_MAX:
                        break
                    if (await s.execute(select(Job.id).where(
                            Job.dedupe_key == dedupe_key(key, "rules", FOUND_DAYS),
                            Job.status.in_(ACTIVE)).limit(1))).first():
                        continue
                    s.add(Job(kind="analysis", repo=repo, repo_key=key, mode="rules",
                              days=FOUND_DAYS, params={}, user_id=None,
                              priority=BADGE_PRIORITY,
                              dedupe_key=dedupe_key(key, "rules", FOUND_DAYS)))
                    await s.commit()
            except IntegrityError:
                pass  # queued by someone else in between
            except Exception:  # noqa: BLE001 -- the search itself already succeeded
                log.exception("queueing a report for %s failed", repo)
        self.wake()

    def _ai_model(self, job: Job) -> str | None:
        """The model id the job's AI work ran on, for `budget.settle`: what the
        service said, or the model an AI report was built with. Call it before
        `_ai_cost`, which lets go of the report's model."""
        if job.id in self.services.ai_models:
            return self.services.ai_models.pop(job.id)
        return getattr(self._models.get(job.id), "model", None)

    def _ai_cost(self, job: Job, result: dict[str, Any] | None = None) -> float | None:
        """What the job's model work cost, for `budget.settle`: the report's
        own `cost`, what its model spent before it failed, or what the service
        said. None when unknown (it timed out, or the service didn't answer)."""
        model = self._models.pop(job.id, None)
        if job.id in self.services.ai_costs:
            return self.services.ai_costs.pop(job.id)
        if job.kind != "analysis":
            return None
        usd = ((result or {}).get("cost") or {}).get("usd")
        if isinstance(usd, int | float):
            return float(usd)
        if model is None:
            return None
        return float(getattr(getattr(model.inner, "usage", None), "cost_usd", 0.0) or 0.0)

    async def _fail(self, job: Job, err: ApiError) -> None:
        # Here, not at the top: playbook.py imports the API module, which imports this one.
        from holt_server import playbook

        model_id = self._ai_model(job)
        cost = self._ai_cost(job)
        async with self.services.db.session() as s:
            failed = await s.execute(self._mine(job.id).values(
                status="error", stage="Failed", error=err.body(), finished_at=now()))
            if failed.rowcount != 1:
                await s.rollback()
                return
            # A report that never arrived costs nothing: its credit comes
            # back in the same transaction.
            await entitlements.refund_job(s, job)
            if job.kind == "playbook":
                await playbook.refund_unlocks(s, job.id)
            if budget.kind_of(job):
                await budget.settle(s, job.id, cost, model_id)
            await s.commit()
        self.hub.publish(job.id, "error", {"error": err.body()})


class JobTimedOut(Exception):
    pass


@dataclass(frozen=True)
class Evidence:
    """What one analysis read from GitHub, for the evidence store."""

    records: list[EvidenceRecord]
    cutoff: datetime
    judges_recency: bool = True


def read_repo(svc: Services, repo: str, mode: str, days: int, model, emit
              ) -> tuple[dict[str, Any], Evidence]:
    """One report on `repo` (synchronous: a job thread runs it), and the
    evidence it read."""
    as_of = datetime.now(UTC)
    provider = svc.provider_factory(repo, as_of)
    cutoff = getattr(provider, "cutoff", as_of)
    recorder = RecordingProvider(provider)
    result = svc.analysis_fn(repo=repo, mode=mode, days=days, provider=recorder, model=model,
                             emit=emit, as_of=cutoff)
    return result, Evidence(recorder.records, cutoff, getattr(provider, "judges_recency", True))


def _aware(when: datetime) -> datetime:
    # SQLite hands back naive datetimes; they were written in UTC.
    return when if when.tzinfo else when.replace(tzinfo=UTC)


async def fresh_rules_report(svc, repo: str, days: int) -> dict[str, Any] | None:
    """The newest rules report for `repo`, if younger than the report cache
    and made by the current engine."""
    cutoff = now() - timedelta(hours=svc.settings.cache_hours)
    async with svc.db.session() as s:
        return (await s.execute(
            select(Report.report).where(Report.repo_key == repo.lower(),
                                        Report.mode == "rules", Report.days == days,
                                        Report.created_at >= cutoff, current_engine())
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(1)
        )).scalar_one_or_none()


# The budget a found repository's background report is made for: the default,
# so the report page, badges and the extension read it directly.
FOUND_DAYS = 7
# Background reports one search may queue (its top results; the page shows
# those first), and the background queue length past which searches queue none.
FOUND_PER_SEARCH = 5
FOUND_QUEUE_MAX = 50


async def any_fresh_rules_report(svc, repo: str) -> bool:
    """Whether `repo` has a rules report from the current engine younger than
    the report cache, for any budget (a rules verdict doesn't depend on it)."""
    cutoff = now() - timedelta(hours=svc.settings.cache_hours)
    async with svc.db.session() as s:
        return (await s.execute(
            select(Report.id).where(Report.repo_key == repo.lower(), Report.mode == "rules",
                                    Report.created_at >= cutoff, current_engine())
            .limit(1))).first() is not None


async def store_find(s, params: dict[str, Any], days: int, result: dict[str, Any]) -> None:
    """Keep a finished search for `/v1/find` to serve again (replaces older)."""
    key = find_key(params.get("languages") or [], params.get("topics") or [],
                   bool(params.get("hacktoberfest")), days)
    await s.execute(delete(FindCache).where(FindCache.key == key))
    s.add(FindCache(key=key, params={**params, "days": days, "engine_version": ENGINE_VERSION,
                                     "starter_rules": starter.rules_version()},
                    results=list((result or {}).get("results") or [])))


def done_payload(kind: str, result: dict[str, Any] | None) -> dict[str, Any]:
    if kind == "find":
        return dict(result or {"results": []})
    if kind == "playbook":
        return {"playbook": without_model(result)}
    if kind == "preflight":
        return {"preflight": without_model(result, "summary")}
    if kind == "merge_plan":
        return {"plan": result}
    return {"report": without_model(result, "cost")}


def without_model(result: dict[str, Any] | None, part: str | None = None
                  ) -> dict[str, Any] | None:
    """`result` without the model id, which is never sent to anyone (results
    stored before it was dropped from the response bodies still hold it).
    `part` names the object inside that carries it."""
    if not isinstance(result, dict):
        return result
    if part is None:
        return {k: v for k, v in result.items() if k != "model"}
    inner = result.get(part)
    if not isinstance(inner, dict) or "model" not in inner:
        return result
    return {**result, part: {k: v for k, v in inner.items() if k != "model"}}
