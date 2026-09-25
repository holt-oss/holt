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
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from holt_server import starter
from holt_server.db import Job, Report, User, now
from holt_server.errors import ApiError

if TYPE_CHECKING:
    from holt_server.services import Services

log = logging.getLogger("holt_server.jobs")

POLL_SECONDS = 5.0


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
    def __init__(self, services: Services, concurrency: int = 2) -> None:
        self.services = services
        self.concurrency = max(1, concurrency)
        self.hub = Hub()
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        # A job left `running` by a process that died will never finish. Put it
        # back in the queue; the engine is read-only, so running it again is safe.
        async with self.services.db.session() as s:
            await s.execute(update(Job).where(Job.status == "running")
                            .values(status="queued", stage="Waiting to start", progress=0.0))
            await s.commit()
        self._stopping = False
        self._tasks = [asyncio.create_task(self._worker(i), name=f"holt-job-{i}")
                       for i in range(self.concurrency)]

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
            await self._run(job)

    async def _claim(self) -> Job | None:
        async with self.services.db.session() as s:
            ids = (await s.execute(
                select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(5)
            )).scalars().all()
            for job_id in ids:
                claimed = await s.execute(
                    update(Job).where(Job.id == job_id, Job.status == "queued")
                    .values(status="running", started_at=now(), stage="Starting",
                            progress=0.01)
                )
                await s.commit()
                if claimed.rowcount == 1:
                    return await s.get(Job, job_id)
        return None

    async def _run(self, job: Job) -> None:
        loop = asyncio.get_running_loop()
        self.hub.publish(job.id, "stage", {"stage": "Starting", "progress": 0.01})

        def emit(stage: str, progress: float) -> None:
            asyncio.run_coroutine_threadsafe(self._progress(job.id, stage, progress), loop)

        try:
            if job.kind == "find":
                result = await asyncio.to_thread(self._find_sync, job, emit)
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

    def _find_sync(self, job: Job, emit) -> dict[str, Any]:
        p = job.params
        return starter.run_find(
            languages=p.get("languages") or [], topics=p.get("topics") or [],
            hacktoberfest=bool(p.get("hacktoberfest")), days=job.days,
            limit=int(p.get("limit") or 20), token=self.services.pool.next(), emit=emit,
        )

    # --- state changes ------------------------------------------------------

    async def _progress(self, job_id: str, stage: str, progress: float) -> None:
        async with self.services.db.session() as s:
            await s.execute(update(Job).where(Job.id == job_id, Job.status == "running")
                            .values(stage=stage[:80], progress=progress))
            await s.commit()
        self.hub.publish(job_id, "stage", {"stage": stage, "progress": progress})

    async def _finish(self, job: Job, result: dict[str, Any]) -> None:
        async with self.services.db.session() as s:
            await s.execute(update(Job).where(Job.id == job.id).values(
                status="done", stage="Done", progress=1.0, result=result,
                finished_at=now()))
            if job.kind == "analysis":
                s.add(Report(repo=job.repo, repo_key=job.repo_key, mode=job.mode,
                             days=job.days, report=result))
            await s.commit()
        self.hub.publish(job.id, "done", done_payload(job.kind, result))

    async def _fail(self, job: Job, err: ApiError) -> None:
        async with self.services.db.session() as s:
            await s.execute(update(Job).where(Job.id == job.id).values(
                status="error", stage="Failed", error=err.body(), finished_at=now()))
            if job.charged and job.user_id:
                # A report that never arrived is not charged for.
                user = await s.get(User, job.user_id)
                if user is not None and user.ai_used > 0:
                    user.ai_used -= 1
            await s.commit()
        self.hub.publish(job.id, "error", {"error": err.body()})


def done_payload(kind: str, result: dict[str, Any] | None) -> dict[str, Any]:
    if kind == "find":
        return dict(result or {"results": []})
    return {"report": result}
