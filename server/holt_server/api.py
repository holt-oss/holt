"""The endpoints in API.md."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from holt.evidence.errors import RateLimited
from holt_server import report as report_mod
from holt_server import (
    __version__,
    badge,
    budget,
    cache,
    credits,
    discover,
    entitlements,
    find as find_mod,
    repo_stats,
    repos,
    schema,
    starter,
    usage,
)
from holt_server.db import (
    ACTIVE,
    BADGE_PRIORITY,
    FindCache,
    Job,
    RepoMeta,
    Report,
    RepoUserStats,
    StarterCache,
    User,
    current_engine,
    dedupe_key,
    find_key,
    iso,
    now,
    utc,
)
from holt_server.credits import get_user
from holt_server.deps import Caller, caller, internal, services, signed_in
from holt_server.discover import DiscoverRepo
from holt_server.errors import ApiError, github_rate_limited
from holt_server.jobs import done_payload
from holt_server.services import Services

SSE_KEEPALIVE_SECONDS = 15.0

public = APIRouter()
# Every /v1 error is the envelope in API.md.
router = APIRouter(prefix="/v1", responses={"default": {"model": schema.ErrorBody}})


# --- dependencies -------------------------------------------------------------


def rate_limit(svc: Services, who: Caller, bucket: str = "work") -> None:
    """Count one request. `work` is new analyses and find; `read` is cache
    misses on reads. Separate counters: reading never uses up work."""
    if not who.user_id and not who.ip:
        raise ApiError("invalid_request",
                       "Anonymous requests must say who is asking (X-Holt-Client-Ip).")
    if bucket == "read":
        s = svc.settings
        limit = s.user_read_rate_per_hour if who.user_id else s.anon_read_rate_per_hour
        svc.read_limiter.hit(who.rate_key, limit)
    else:
        svc.limiter.hit(who.rate_key, who.limit(svc))


# --- account ------------------------------------------------------------------


async def me_body(svc: Services, user: User) -> schema.Me:
    return schema.Me(plan=entitlements.effective_plan(entitlements.catalogue(svc), user),
                     plan_expires_at=iso(user.plan_expires_at),
                     credits=await credits.credits_body(svc, user))


# --- bodies -------------------------------------------------------------------


class AnalysisIn(BaseModel):
    # Model choice is server configuration (OPENROUTER_MODEL). Clients from
    # when the web had a model picker still send `model`; unknown keys are
    # dropped here, so it never reaches the engine, the job or its cache key.
    model_config = ConfigDict(extra="ignore")

    repo: str = Field(max_length=500)
    mode: Literal["rules", "ai"] = "rules"
    days: int = Field(7, ge=1, le=90)
    refresh: bool = False


class FindIn(BaseModel):
    languages: list[str] = Field(default_factory=list, max_length=10)
    topics: list[str] = Field(default_factory=list, max_length=10)
    days: int = Field(7, ge=1, le=90)
    hacktoberfest: bool = False
    limit: int = Field(20, ge=1, le=50)


# --- health and badge (no internal key) ---------------------------------------


@public.get("/health", response_model=schema.Health, responses={503: {"model": schema.Health}})
async def health(request: Request) -> Any:
    svc = services(request)
    body: dict[str, Any] = {"ok": True, "version": __version__}
    if not await svc.db.ping():
        body.update(ok=False, database=False)
        return JSONResponse(body, status_code=503)
    return body


@public.get("/badge/{owner}/{repo}.svg")
async def badge_svg(owner: str, repo: str, request: Request) -> Response:
    svc = services(request)
    name = repos.normalize(f"{owner}/{repo}")
    latest = await latest_report(svc, name, "rules", 7)
    # An outdated report's verdict is never shown: the badge says it is
    # updating until the refresh queued below lands.
    updating = latest is not None and latest.outdated
    verdict = latest.report.get("verdict") if latest and not updating else None
    stats = latest.report.get("stats") if latest and not updating else None
    shown = latest.repo if latest else name
    stale = latest is None or not is_fresh(svc, latest)
    if stale:
        # Stale-while-revalidate: show what we have, refresh behind it. Bounded
        # per client and in total, on counters of its own, and queued behind
        # every user request (see JobRunner), so badge URLs cannot crowd out
        # people using the site.
        try:
            await enqueue_badge_refresh(svc, name, badge_client(request))
        except Exception:  # noqa: BLE001 -- a badge must always render
            pass
    link = f"{svc.settings.web_url.rstrip('/')}/{shown}"
    return Response(
        badge.render(verdict, stats, link, updating=updating),
        media_type="image/svg+xml",
        headers={"Cache-Control": BADGE_UPDATING_CACHE if updating else BADGE_CACHE},
    )


BADGE_CACHE = "public, max-age=3600, stale-while-revalidate=86400"
# Short, so the new verdict replaces "updating" soon after the refresh lands.
BADGE_UPDATING_CACHE = "public, max-age=300"


def badge_client(request: Request) -> str:
    """Who is asking for a badge. Behind the Cloudflare tunnel the socket is
    always local, so Cloudflare's header is the client when present."""
    return (request.headers.get("cf-connecting-ip")
            or (request.client.host if request.client else "unknown"))[:64]


async def enqueue_badge_refresh(svc: Services, repo: str, client: str) -> None:
    key = repos.key(repo)
    if await active_job(svc, key, "rules", 7):
        return
    s = svc.settings
    svc.badge_limiter.hit(f"ip:{client}", s.badge_rate_per_ip)
    svc.badge_limiter.hit("total", s.badge_rate_total)
    canonical = await svc.canonical(repo)
    await insert_or_join(svc, Job(
        kind="analysis", repo=canonical, repo_key=key, mode="rules", days=7, params={},
        user_id=None, priority=BADGE_PRIORITY, dedupe_key=dedupe_key(key, "rules", 7)))


# --- reports and cache ----------------------------------------------------------


async def latest_report(svc: Services, repo: str, mode: str, days: int) -> Report | None:
    """The newest report for this repo, mode and budget.

    A rules report's verdict doesn't depend on the budget (see
    `report.retime`), so when there is no fresh one for `days`, a fresh one
    made for another budget answers, with its reply-time note redone. It is
    not stored: the next read derives it again, and a real run for `days`
    wins as soon as one exists. Only reports from the current engine count
    as fresh (`Report.outdated`); an outdated one is still returned when
    nothing fresher exists, and callers decide what to do with it.
    """
    key = repos.key(repo)
    async with svc.db.session() as s:
        exact = (await s.execute(
            select(Report).where(Report.repo_key == key, Report.mode == mode,
                                 Report.days == days)
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(1)
        )).scalar_one_or_none()
        if mode != "rules" or (exact is not None and is_fresh(svc, exact)):
            return exact
        cutoff = now() - timedelta(hours=svc.settings.cache_hours)
        others = (await s.execute(
            select(Report).where(Report.repo_key == key, Report.mode == "rules",
                                 Report.days != days, Report.created_at >= cutoff,
                                 current_engine())
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(5)
        )).scalars().all()
    for other in others:
        if (derived := report_mod.retime(other.report, days)) is not None:
            return Report(id=other.id, repo=other.repo, repo_key=other.repo_key, mode="rules",
                          days=days, report=derived, created_at=other.created_at,
                          engine_version=other.engine_version)
    return exact


def is_fresh(svc: Services, report: Report) -> bool:
    """Young enough to serve as the answer, and made by the current engine."""
    return (not report.outdated
            and now() - utc(report.created_at) < timedelta(hours=svc.settings.cache_hours))


async def active_job(svc: Services, key: str, mode: str, days: int) -> Job | None:
    async with svc.db.session() as s:
        return (await s.execute(
            select(Job).where(Job.dedupe_key == dedupe_key(key, mode, days),
                              Job.status.in_(ACTIVE)).limit(1)
        )).scalar_one_or_none()


async def join_active(svc: Services, key: str, mode: str, days: int) -> Job | None:
    """The in-flight job for this question, promoted to user priority: someone
    is waiting on it now, even if a badge queued it."""
    job = await active_job(svc, key, mode, days)
    if job is not None and job.priority:
        async with svc.db.session() as s:
            await s.execute(update(Job).where(Job.id == job.id).values(priority=0))
            await s.commit()
    return job


async def insert_or_join(svc: Services, job: Job, before_insert=None) -> tuple[Job, bool]:
    """Insert `job` unless an identical one is queued or running; then return that.

    Atomic: the partial unique index on `dedupe_key` decides, so two requests
    racing past the `active_job` check still end up with one job. Whatever
    `before_insert(session, job)` does (spending a credit) commits with the
    insert or rolls back with it. Returns (job, created).
    """
    async with svc.db.session() as s:
        if before_insert is not None:
            job.id = job.id or uuid.uuid4().hex
            await before_insert(s, job)
        s.add(job)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
        else:
            svc.runner.wake()
            return job, True
    existing = await join_active(svc, job.repo_key, job.mode, job.days)
    if existing is None:  # finished in between; retry once without the race
        return await insert_or_join(svc, job_copy(job), before_insert)
    return existing, False


def job_copy(job: Job) -> Job:
    return Job(kind=job.kind, repo=job.repo, repo_key=job.repo_key, mode=job.mode,
               days=job.days, params=dict(job.params or {}), user_id=job.user_id,
               key_source=job.key_source, charged=job.charged, priority=job.priority,
               dedupe_key=job.dedupe_key)


@router.get("/reports", dependencies=[Depends(internal)])
async def list_reports(request: Request,
                       limit: int = Query(500, ge=1, le=5000)) -> schema.ReportList:
    """The latest 7-day rules report per repository, newest first (sitemaps)."""
    svc = services(request)
    latest = (select(func.max(Report.id).label("id"))
              .where(Report.mode == "rules", Report.days == 7)
              .group_by(Report.repo_key).subquery())
    async with svc.db.session() as s:
        # Two fields out of each report in SQL, not 500 whole report bodies.
        rows = (await s.execute(
            select(Report.repo, Report.mode, Report.created_at,
                   Report.report["generated_at"].as_string(),
                   Report.report["verdict"].as_string())
            .join(latest, Report.id == latest.c.id)
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(limit)
        )).all()
    return schema.ReportList.model_validate({"reports": [
        {"repo": repo, "mode": mode, "generated_at": generated or iso(created),
         "verdict": verdict}
        for repo, mode, created, generated, verdict in rows
    ]})


# A free report as it is sent is served for this long at most, and only until
# this process writes one of the rows it was made from (`report_stamp`). At
# most this many, and this many bytes of them.
REPORT_KEPT_S = 60.0
REPORTS_KEPT = 512
REPORTS_KEPT_BYTES = 32 * 1024 * 1024


def kept_reports(svc: Services) -> cache.Kept[cache.Body]:
    """This process's free reports, as sent (cache.py)."""
    return cache.store(svc, "reports", lambda: cache.Kept(
        REPORT_KEPT_S, REPORTS_KEPT, REPORTS_KEPT_BYTES))


def report_stamp(svc: Services, key: str) -> tuple:
    """Changes whenever this process writes what `GET /v1/reports` sends for
    this repo: a report (for any budget: one answers for another), its
    details, or Holt users' numbers (rebuilt, or taken away when someone opts
    out). No database read (cache.py)."""
    return cache.writes(svc).repo(
        key, Report.__tablename__, RepoMeta.__tablename__, RepoUserStats.__tablename__)


async def report_body(svc: Services, name: str, mode: str, days: int) -> schema.Report:
    latest = await latest_report(svc, name, mode, days)
    if latest is None:
        raise ApiError("not_found", f"There's no report for {name} yet.")
    report = await dressed(svc, schema.Report.model_validate(latest.report), name)
    report.outdated = latest.outdated
    return report


@router.get("/reports/{owner}/{repo}", dependencies=[Depends(internal)],
            response_model=schema.Report)
async def get_report(owner: str, repo: str, request: Request,
                     mode: Literal["rules", "ai"] = "rules",
                     days: int = Query(7, ge=1, le=90)) -> Response:
    """The free report is the same for every reader, so it is kept as sent
    (cache.py): a read costs no session, and no parsing, validating and
    serialising of the report again. AI reports are read from the database
    every time."""
    svc = services(request)
    name = repos.normalize(f"{owner}/{repo}")
    if mode != "rules":
        return cache.respond(request, cache.body_of(await report_body(svc, name, mode, days)))
    key = repos.key(name)

    async def build() -> cache.Body:
        return cache.body_of(await report_body(svc, name, mode, days))

    body = await kept_reports(svc).load((key, days), report_stamp(svc, key), build, len)
    return cache.respond(request, body)


async def dressed(svc: Services, report: schema.Report, name: str) -> schema.Report:
    """`report` with what the page shows beside it but the stored report doesn't
    hold: the repo's details (`about`) and Holt users' numbers. Every way a
    report reaches the page goes through here, so a report just checked shows
    the same as the same report read back later."""
    report.holt_users = await repo_stats.for_repo(svc, name)
    report.about = await discover.about(svc, name)
    return report


# --- analyses -------------------------------------------------------------------


@router.post("/analyses", response_model=schema.AnalysisDone,
             responses={202: {"model": schema.Queued}})
async def create_analysis(body: AnalysisIn, request: Request,
                          who: Caller = Depends(caller)) -> JSONResponse:
    svc = services(request)
    repo = repos.normalize(body.repo)
    key = repos.key(repo)

    if body.mode == "ai" and not who.user_id:
        raise ApiError("needs_key", "Sign in to get an AI-written report. "
                       "The quick report is free without an account.")

    await usage.record(svc, "analysis", user_id=who.user_id, ip=who.ip, repo_key=key,
                       mode=body.mode)

    if not body.refresh:
        cached = await latest_report(svc, repo, body.mode, body.days)
        if cached is not None and is_fresh(svc, cached):
            report = await dressed(svc, schema.Report.model_validate(cached.report), repo)
            return JSONResponse(schema.AnalysisDone(report=report).model_dump(mode="json"))

    if body.mode == "ai" and not svc.server_model_available():
        # Before the rate limit and the credit: nothing is spent or queued.
        raise ApiError("ai_unavailable", "AI reports aren't switched on yet. "
                       "The free quick report has the full verdict and evidence.")

    rate_limit(svc, who)

    if existing := await join_active(svc, key, body.mode, body.days):
        return queued(existing.id)

    canonical = await svc.canonical(repo)
    job = Job(kind="analysis", repo=canonical, repo_key=key, mode=body.mode,
              days=body.days, params={"refresh": body.refresh}, user_id=who.user_id,
              dedupe_key=dedupe_key(key, body.mode, body.days))
    charge = None
    if body.mode == "ai":
        await get_user(svc, who.user_id)  # the welcome credits, on a first visit
        job.key_source, job.charged = "server", True
        user_id = who.user_id

        async def charge(s, job: Job) -> None:
            # The budget first: a run that doesn't fit is refused before any credit moves.
            await budget.reserve(s, svc.settings, job.id, budget.ANALYSIS)
            paid = await entitlements.charge(s, svc, user_id, "ai_report", job_id=job.id)
            params = {k: v for k, v in (job.params or {}).items()
                      if k not in ("charge", "paid_with")}  # a retry charges again
            params["charge"] = paid
            if paid.get("draws") == [{"source": "free", "lot": None, "amount": 1}]:
                # What the release before entitlements refunds, should it run this job.
                params["paid_with"] = "credit"
            job.params = params

    job, _created = await insert_or_join(svc, job, charge)
    return queued(job.id)


def queued(job_id: str) -> JSONResponse:
    return JSONResponse({"status": "queued", "job_id": job_id}, status_code=202)


async def load_job(svc: Services, job_id: str, kind: str) -> Job:
    async with svc.db.session() as s:
        job = await s.get(Job, job_id[:64])
    if job is None or job.kind != kind:
        raise ApiError("not_found", "We couldn't find that check. It may have expired.")
    return job


def job_body(job: Job) -> dict[str, Any]:
    """The poll body; the endpoints validate it as `schema.JobStatus` or
    `schema.FindJobStatus`, which also fills in reports' derived fields."""
    body: dict[str, Any] = {
        "status": job.status,
        "stage": job.stage,
        "progress": round(job.progress or 0.0, 3),
        "error": job.error if job.status == "error" else None,
    }
    if job.kind == "find":
        body["results"] = (job.result or {}).get("results") if job.status == "done" else None
    elif job.kind == "playbook":
        body["playbook"] = job.result if job.status == "done" else None
    elif job.kind == "preflight":
        body["preflight"] = job.result if job.status == "done" else None
    elif job.kind == "merge_plan":
        body["plan"] = job.result if job.status == "done" else None
    else:
        body["report"] = job.result if job.status == "done" else None
    return body


@router.get("/analyses/{job_id}", dependencies=[Depends(internal)])
async def get_analysis(job_id: str, request: Request) -> schema.JobStatus:
    return schema.JobStatus.model_validate(
        job_body(await load_job(services(request), job_id, "analysis")))


@router.get("/analyses/{job_id}/events", dependencies=[Depends(internal)])
async def analysis_events(job_id: str, request: Request) -> StreamingResponse:
    svc = services(request)
    await load_job(svc, job_id, "analysis")
    return sse(svc, job_id, "analysis", request)


# --- server-sent events ---------------------------------------------------------


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def drop_queued_stages(queue: asyncio.Queue) -> tuple[str, dict[str, Any]] | None:
    """Empty a subscriber's queue of stage events. Returns the job's end
    (`done` or `error`) if it is already waiting there."""
    while not queue.empty():
        event, data = queue.get_nowait()
        if event != "stage":
            return event, data
    return None


def sse(svc: Services, job_id: str, kind: str, request: Request) -> StreamingResponse:
    async def stream():
        queue = svc.runner.hub.subscribe(job_id)
        try:
            last: tuple[str, float] | None = None
            job = await load_job(svc, job_id, kind)
            while True:
                if job is not None:
                    if job.status == "done":
                        yield sse_event("done", done_payload(kind, job.result))
                        return
                    if job.status == "error":
                        yield sse_event("error", {"error": job.error})
                        return
                    data = await svc.runner.stage_event(job)
                    # Steps queued before this read finished are in it (bar one
                    # landing mid-read, which the next step replaces); sending
                    # them after it would step backwards.
                    end = drop_queued_stages(queue)
                    current = (data["stage"], data["progress"])
                    if current != last:
                        last = current
                        yield sse_event("stage", data)
                    if end is not None:
                        yield sse_event(*end)
                        return
                job = None
                try:
                    event, data = await asyncio.wait_for(queue.get(), SSE_KEEPALIVE_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"
                    # Re-read: the job may be running in another process.
                    job = await load_job(svc, job_id, kind)
                    continue
                if event == "stage":
                    current = (data["stage"], data["progress"])
                    if current != last:
                        last = current
                        yield sse_event("stage", data)
                else:
                    yield sse_event(event, data)
                    return
        finally:
            svc.runner.hub.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- starter issues and find ------------------------------------------------------


# Issues are ranked once, at this many, and sliced per request.
STARTER_CACHE_LIMIT = 50


async def cached_starter_issues(svc: Services, repo: str) -> StarterCache | None:
    cutoff = now() - timedelta(hours=svc.settings.starter_cache_hours)
    async with svc.db.session() as s:
        row = await s.get(StarterCache, repos.key(repo))
    fresh = (row is not None and utc(row.created_at) >= cutoff
             and starter.current(row.issues, row.rules_version))
    return row if fresh else None


async def fetch_starter_issues(svc: Services, repo: str) -> tuple[str, list[dict]]:
    """Ask GitHub, store the answer. Concurrent misses for one repo share one
    call (single-flight, per process)."""
    key = repos.key(repo)
    if (pending := svc.inflight.get(key)) is not None:
        return await asyncio.shield(pending)
    task = asyncio.ensure_future(_fetch_and_store(svc, repo))
    svc.inflight[key] = task
    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            svc.inflight.pop(key, None)
        else:
            task.add_done_callback(lambda _: svc.inflight.pop(key, None))


async def _fetch_and_store(svc: Services, repo: str) -> tuple[str, list[dict]]:
    canonical = await svc.canonical(repo)
    try:
        # The token is taken in the thread: the GitHub App may fetch a new one.
        issues = await asyncio.to_thread(
            lambda: starter.run_starter_issues(canonical, svc.pool.next(), STARTER_CACHE_LIMIT))
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        from holt_server.engine import translate

        raise translate(exc, canonical) from exc
    async with svc.db.session() as s:
        row = await s.get(StarterCache, repos.key(canonical))
        if row is None:
            s.add(StarterCache(repo_key=repos.key(canonical), repo=canonical, issues=issues))
        else:
            row.repo, row.issues, row.created_at = canonical, issues, now()
            row.rules_version = starter.rules_version()
        await s.commit()
    return canonical, issues


@router.get("/repos/{owner}/{repo}/starter-issues")
async def starter_issues(owner: str, repo: str, request: Request,
                         limit: int = Query(20, ge=1, le=50),
                         who: Caller = Depends(caller)) -> schema.StarterIssues:
    svc = services(request)
    name = repos.normalize(f"{owner}/{repo}")
    # A cache hit costs nothing: no rate limit, no GitHub.
    if (hit := await cached_starter_issues(svc, name)) is not None:
        return schema.StarterIssues(repo=hit.repo, issues=starter.offered(hit.issues)[:limit])
    starter.function("starter_issues")  # 501 before spending a rate-limit hit
    rate_limit(svc, who, "read")
    canonical, issues = await fetch_starter_issues(svc, name)
    return schema.StarterIssues(repo=canonical, issues=starter.offered(issues)[:limit])


# Repository-name searches already answered: the same name is asked for again
# and again (a card's one-tap matchups, a shared link), and GitHub's search
# allows far fewer requests than its other APIs.
REPO_SEARCH_TTL_S = 600
REPO_SEARCH_MAX = 500
REPO_SEARCH_NAME = re.compile(r"[a-z0-9._-]+(?: [a-z0-9._-]+)*")
_repo_searches: dict[str, tuple[float, list[dict]]] = {}


@router.get("/repos/search")
async def search_repos(request: Request, q: str = Query(..., min_length=1, max_length=60),
                       who: Caller = Depends(caller)) -> schema.RepoSearch:
    """Which repository does a bare name mean? ("excalidraw" is
    excalidraw/excalidraw.) Public repositories whose name matches, most
    starred first, at most five. It only reads GitHub's search; nothing is
    stored."""
    svc = services(request)
    name = " ".join(q.lower().split())
    if not REPO_SEARCH_NAME.fullmatch(name):
        raise ApiError("invalid_request", "That doesn't look like a repository name.")
    hit = _repo_searches.get(name)
    if hit is not None and hit[0] > time.monotonic():
        return schema.RepoSearch(query=name, results=hit[1])
    rate_limit(svc, who, "read")
    try:
        found = await svc.lookup.search(name)
    except RateLimited as exc:
        raise github_rate_limited() from exc
    _repo_searches[name] = (time.monotonic() + REPO_SEARCH_TTL_S, found)
    while len(_repo_searches) > REPO_SEARCH_MAX:  # oldest first: dicts keep insertion order
        _repo_searches.pop(next(iter(_repo_searches)))
    return schema.RepoSearch(query=name, results=found)


# A search is computed for at least this many results, so the default page
# and anything smaller come from one cached answer.
FIND_MIN_LIMIT = 20


def find_params(body: FindIn) -> dict[str, Any]:
    params = body.model_dump()
    params["languages"] = sorted({x.strip().lower()[:40] for x in body.languages if x.strip()})
    params["topics"] = sorted({x.strip().lower()[:60] for x in body.topics if x.strip()})
    params["limit"] = max(body.limit, FIND_MIN_LIMIT)
    return params


async def cached_find(svc: Services, key: str, limit: int) -> list[dict] | None:
    """A fresh cached search that can answer a request for `limit`, or None."""
    cutoff = now() - timedelta(hours=svc.settings.find_cache_hours)
    async with svc.db.session() as s:
        row = await s.get(FindCache, key)
        if row is None or utc(row.created_at) < cutoff or row.outdated:
            return None
        computed_for = int((row.params or {}).get("limit") or 0)
        # Enough results, or the search ran out before its own limit (so asking
        # for more would find nothing new).
        if computed_for >= limit or len(row.results) < computed_for:
            # Details the warm pass fetched since the search ran show up too.
            return await discover.with_meta(s, row.results)
    return None


async def active_find(svc: Services, key: str) -> Job | None:
    async with svc.db.session() as s:
        return (await s.execute(select(Job).where(
            Job.dedupe_key == f"find:{key}", Job.status.in_(ACTIVE)).limit(1)
        )).scalar_one_or_none()


def find_done(results: list[dict], limit: int, complete: bool = True) -> JSONResponse:
    return JSONResponse(schema.FindDone.model_validate(
        {"results": results[:limit], "complete": complete}).model_dump(mode="json"))


def find_queued(job_id: str, index: list[dict], limit: int) -> JSONResponse:
    """202 for a search under way, with the index part to show meanwhile."""
    return JSONResponse(schema.FindQueued.model_validate(
        {"job_id": job_id, "results": index[:limit]}).model_dump(mode="json"), status_code=202)


@router.post("/find", response_model=schema.FindDone,
             responses={202: {"model": schema.FindQueued}})
async def find(body: FindIn, request: Request, who: Caller = Depends(caller)) -> JSONResponse:
    svc = services(request)
    starter.function("find")
    params = find_params(body)
    key = find_key(params["languages"], params["topics"], params["hacktoberfest"], body.days)
    await usage.record(svc, "find", user_id=who.user_id, ip=who.ip)
    # Holt's own index answers first, from the database (find.py).
    index = await find_mod.index_results(svc, params)
    # Cached, or already being searched for someone else: free, no rate limit.
    if (search := await cached_find(svc, key, body.limit)) is not None:
        return find_done(find_mod.merge(index, search), body.limit)
    if (running := await active_find(svc, key)) is not None:
        return find_queued(running.id, index, body.limit)
    try:
        rate_limit(svc, who)
    except ApiError as err:
        # Over the work limit: what the index has is still an answer.
        if err.code == "rate_limited" and index:
            return find_done(index, body.limit, complete=False)
        raise
    async with svc.db.session() as s:
        job = Job(kind="find", mode="rules", days=body.days, params=params,
                  user_id=who.user_id, dedupe_key=f"find:{key}")
        s.add(job)
        try:
            await s.commit()
        except IntegrityError:  # an identical search started a moment ago
            await s.rollback()
            if (running := await active_find(svc, key)) is not None:
                return find_queued(running.id, index, body.limit)
            raise
    svc.runner.wake()
    return find_queued(job.id, index, body.limit)


@router.get("/find/{job_id}", dependencies=[Depends(internal)])
async def get_find(job_id: str, request: Request) -> schema.FindJobStatus:
    return schema.FindJobStatus.model_validate(
        job_body(await load_job(services(request), job_id, "find")))


@router.get("/find/{job_id}/events", dependencies=[Depends(internal)])
async def find_events(job_id: str, request: Request) -> StreamingResponse:
    svc = services(request)
    await load_job(svc, job_id, "find")
    return sse(svc, job_id, "find", request)


# --- account ----------------------------------------------------------------------


@router.get("/me")
async def me(request: Request, who: Caller = Depends(caller)) -> schema.Me:
    svc = services(request)
    return await me_body(svc, await get_user(svc, signed_in(who)))


@router.get("/me/entitlements")
async def me_entitlements(request: Request, who: Caller = Depends(caller)) -> schema.Entitlements:
    """Each paid feature: can this user use it now, and what would it cost."""
    svc = services(request)
    user = await get_user(svc, signed_in(who))
    cat = entitlements.catalogue(svc)
    access = [await entitlements.check(svc, user.id, f) for f in cat.features]
    return schema.Entitlements(plan=entitlements.effective_plan(cat, user),
                               plan_expires_at=iso(user.plan_expires_at),
                               features=[schema.Access(**a.__dict__) for a in access])


class History(schema.Model):
    items: list[schema.HistoryItem]
    cards: list[DiscoverRepo] = Field(
        default_factory=list,
        description="Holt's current card for each repo in `items` that has one "
                    "(the latest 7-day rules report, as on saved repos).")


@router.get("/me/history")
async def history(request: Request, who: Caller = Depends(caller),
                  limit: int = Query(50, ge=1, le=200)) -> History:
    svc = services(request)
    user_id = signed_in(who)
    async with svc.db.session() as s:
        jobs = (await s.execute(
            select(Job).where(Job.user_id == user_id, Job.kind == "analysis")
            .order_by(Job.created_at.desc()).limit(limit)
        )).scalars().all()
    cards = await discover.cards(svc, list({repos.key(j.repo) for j in jobs}))
    return History.model_validate({"cards": list(cards.values()), "items": [
        {
            "job_id": j.id,
            "repo": j.repo,
            "mode": j.mode,
            "days": j.days,
            "status": j.status,
            "verdict": (j.result or {}).get("verdict"),
            "created_at": iso(j.created_at),
        }
        for j in jobs
    ]})
