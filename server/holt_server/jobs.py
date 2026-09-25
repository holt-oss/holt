"""The in-process jobs runner.

Jobs live in the `jobs` table, so a queued job survives a restart and every
API process sees the same state. Up to `HOLT_JOB_CONCURRENCY` run at once, each
in a worker thread because the engine is synchronous. Progress goes to the
table (for polling) and to an in-memory hub (for SSE subscribers in this
process); SSE also re-reads the table, so it keeps working if the job runs in
another process.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update

from holt_server import starter
from holt_server.db import BADGE_PRIORITY, FindCache, Job, Report, User, find_key, now
from holt_server.errors import ApiError

if TYPE_CHECKING:
    from holt_server.services import Services

log = logging.getLogger("holt_server.jobs")

POLL_SECONDS = 5.0
# A running job's runner touches `heartbeat_at` this often. One not touched for
# STALE_AFTER belonged to a process that died, and is queued again.
HEARTBEAT_SECONDS = 15.0
STALE_AFTER = timedelta(seconds=90)


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

    def publish(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in list(self._subs.get(job_id, ())):
            queue.put_nowait((event, data))


class JobRunner:
    def __init__(self, services: Services, concurrency: int = 2,
                 badge_concurrency: int = 1) -> None:
        self.services = services
        self.concurrency = max(1, concurrency)
        # Never all workers: a user request always has a worker badges can't take.
        self.badge_concurrency = max(0, min(badge_concurrency, self.concurrency - 1))
        self.hub = Hub()
        self.worker_id = uuid.uuid4().hex
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._running: dict[str, int] = {}  # job id -> priority, jobs this runner holds
        self._stopping = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        self._stopping = False
        await self.requeue_stale()
        self._tasks = [asyncio.create_task(self._worker(i), name=f"holt-job-{i}")
                       for i in range(self.concurrency)]
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

    def wake(self) -> None:
        self._wake.set()

    # --- the loop -----------------------------------------------------------

    async def _worker(self, index: int) -> None:
        while not self._stopping:
            try:
                job = await self._claim()
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
                await self._run(job)
            finally:
                self._running.pop(job.id, None)

    async def _claim(self) -> Job | None:
        badges = sum(1 for p in self._running.values() if p >= BADGE_PRIORITY)
        query = select(Job.id, Job.priority).where(Job.status == "queued")
        if badges >= self.badge_concurrency:
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

    async def _run(self, job: Job) -> None:
        loop = asyncio.get_running_loop()
        self.hub.publish(job.id, "stage", {"stage": "Starting", "progress": 0.01})

        def emit(stage: str, progress: float) -> None:
            asyncio.run_coroutine_threadsafe(self._progress(job.id, stage, progress), loop)

        try:
            if job.kind == "find":
                result = await asyncio.to_thread(self._find_sync, job, emit, loop)
            else:
                # The key is decrypted here, per run, and only ever held in
                # memory: the jobs table records where it came from, not what it is.
                spec = await self.services.model_spec_for(job) if job.mode == "ai" else None
                result = await asyncio.to_thread(self._analysis_sync, job, spec, emit)
        except ApiError as err:
            await self._fail(job, err)
        except Exception:  # noqa: BLE001
            log.exception("job %s crashed", job.id)
            await self._fail(job, ApiError(
                "internal", "Something went wrong on our side. Please try again in a minute."))
        else:
            await self._finish(job, result)

    def _analysis_sync(self, job: Job, spec, emit) -> dict[str, Any]:
        svc = self.services
        as_of = datetime.now(UTC)
        provider = svc.provider_factory(job.repo, as_of)
        model = None
        if job.mode == "ai":
            model = svc.model_factory(spec)
        return svc.analysis_fn(repo=job.repo, mode=job.mode, days=job.days,
                              provider=provider, model=model, emit=emit,
                              as_of=getattr(provider, "cutoff", as_of))

    def _find_sync(self, job: Job, emit, loop) -> dict[str, Any]:
        p = job.params
        svc = self.services

        def cached(repo: str) -> dict[str, Any] | None:
            # Called from find's worker threads; the database lives on the loop.
            return asyncio.run_coroutine_threadsafe(
                fresh_rules_report(svc, repo, job.days), loop).result(timeout=30)

        return starter.run_find(
            languages=p.get("languages") or [], topics=p.get("topics") or [],
            hacktoberfest=bool(p.get("hacktoberfest")), days=job.days,
            limit=int(p.get("limit") or 20), token=svc.pool.next(), emit=emit,
            cached=cached, http=getattr(svc, "http", None),
        )

    # --- state changes ------------------------------------------------------

    def _mine(self, job_id: str):
        """Writes to a job only while this runner still holds it. If it was
        requeued as stale and picked up elsewhere, this runner's result is dropped."""
        return update(Job).where(Job.id == job_id, Job.status == "running",
                                 Job.worker_id == self.worker_id)

    async def _progress(self, job_id: str, stage: str, progress: float) -> None:
        async with self.services.db.session() as s:
            await s.execute(self._mine(job_id).values(
                stage=stage[:80], progress=progress, heartbeat_at=now()))
            await s.commit()
        self.hub.publish(job_id, "stage", {"stage": stage, "progress": progress})

    async def _finish(self, job: Job, result: dict[str, Any]) -> None:
        async with self.services.db.session() as s:
            done = await s.execute(self._mine(job.id).values(
                status="done", stage="Done", progress=1.0, result=result,
                finished_at=now()))
            if done.rowcount != 1:
                await s.rollback()
                return
            if job.kind == "analysis":
                s.add(Report(repo=job.repo, repo_key=job.repo_key, mode=job.mode,
                             days=job.days, report=result))
            elif job.kind == "find":
                await store_find(s, job.params or {}, job.days, result)
            await s.commit()
        self.hub.publish(job.id, "done", done_payload(job.kind, result))

    async def _fail(self, job: Job, err: ApiError) -> None:
        async with self.services.db.session() as s:
            failed = await s.execute(self._mine(job.id).values(
                status="error", stage="Failed", error=err.body(), finished_at=now()))
            if failed.rowcount != 1:
                await s.rollback()
                return
            if job.charged and job.user_id:
                # A report that never arrived is not charged for. Atomic, and
                # only against the month it was charged to.
                await s.execute(update(User).where(
                    User.id == job.user_id, User.ai_used > 0,
                    User.ai_period == (job.params or {}).get("ai_period", ""),
                ).values(ai_used=User.ai_used - 1))
            await s.commit()
        self.hub.publish(job.id, "error", {"error": err.body()})


async def fresh_rules_report(svc, repo: str, days: int) -> dict[str, Any] | None:
    """The newest rules report for `repo`, if younger than the report cache."""
    cutoff = now() - timedelta(hours=svc.settings.cache_hours)
    async with svc.db.session() as s:
        return (await s.execute(
            select(Report.report).where(Report.repo_key == repo.lower(),
                                        Report.mode == "rules", Report.days == days,
                                        Report.created_at >= cutoff)
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(1)
        )).scalar_one_or_none()


async def store_find(s, params: dict[str, Any], days: int, result: dict[str, Any]) -> None:
    """Keep a finished search for `/v1/find` to serve again (replaces older)."""
    key = find_key(params.get("languages") or [], params.get("topics") or [],
                   bool(params.get("hacktoberfest")), days)
    await s.execute(delete(FindCache).where(FindCache.key == key))
    s.add(FindCache(key=key, params={**params, "days": days},
                    results=list((result or {}).get("results") or [])))


def done_payload(kind: str, result: dict[str, Any] | None) -> dict[str, Any]:
    if kind == "find":
        return dict(result or {"results": []})
    return {"report": result}
