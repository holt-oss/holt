"""The endpoints in API.md."""

from __future__ import annotations

import asyncio
import hmac
import json
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from holt_server import __version__, badge, crypto, llm, quota, repos, starter
from holt_server.db import (
    ACTIVE,
    BADGE_PRIORITY,
    USER_PRIORITY,
    FindCache,
    Job,
    Report,
    StarterCache,
    Subscription,
    User,
    dedupe_key,
    find_key,
    iso,
    now,
    utc,
)
from holt_server.errors import ApiError
from holt_server.jobs import done_payload
from holt_server.services import Services

SSE_KEEPALIVE_SECONDS = 15.0

public = APIRouter()
router = APIRouter(prefix="/v1")


# --- dependencies -------------------------------------------------------------


def services(request: Request) -> Services:
    return request.app.state.services


async def internal(
    request: Request,
    x_holt_internal_key: str | None = Header(default=None),
) -> None:
    expected = services(request).settings.internal_key
    if not expected or not x_holt_internal_key or not hmac.compare_digest(
        x_holt_internal_key.encode(), expected.encode()
    ):
        raise ApiError("unauthorized", "This API is only for the Holt website.")


class Caller:
    def __init__(self, user_id: str | None, ip: str | None) -> None:
        self.user_id = user_id
        self.ip = ip

    @property
    def rate_key(self) -> str:
        return f"user:{self.user_id}" if self.user_id else f"ip:{self.ip}"

    def limit(self, svc: Services) -> int:
        s = svc.settings
        return s.user_rate_per_hour if self.user_id else s.anon_rate_per_hour


async def caller(
    request: Request,
    _: None = Depends(internal),
    x_holt_user: str | None = Header(default=None),
    x_holt_client_ip: str | None = Header(default=None),
) -> Caller:
    user_id = (x_holt_user or "").strip()[:200] or None
    # No fallback to the socket address: that is the BFF's, and every anonymous
    # visitor would share one bucket.
    ip = (x_holt_client_ip or "").strip()[:64] or None
    return Caller(user_id, ip)


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


async def get_user(svc: Services, user_id: str) -> User:
    """The user row, created the first time `web/` sends this id."""
    async with svc.db.session() as s:
        user = await s.get(User, user_id)
        if user is None:
            user = User(id=user_id, plan="free", ai_used=0, ai_period="")
            s.add(user)
            try:
                await s.commit()
            except Exception:  # created concurrently by another request
                await s.rollback()
                user = await s.get(User, user_id)
        return user


def signed_in(who: Caller) -> str:
    if not who.user_id:
        raise ApiError("unauthorized", "Please sign in first.")
    return who.user_id


# --- account body -------------------------------------------------------------


async def active_subscription(svc: Services, user_id: str) -> Subscription | None:
    """The user's most recent subscription, whatever its status."""
    async with svc.db.session() as s:
        return (await s.execute(
            select(Subscription).where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc()).limit(1)
        )).scalar_one_or_none()


async def me_body(svc: Services, user: User) -> dict[str, Any]:
    plan = quota.effective_plan(user, svc.catalog, svc.grace)
    paid = quota.is_paid(plan)
    sub = await active_subscription(svc, user.id) if paid else None
    renewing = sub is not None and sub.status in ("active", "pending") \
        and not sub.cancel_at_period_end
    until = iso(user.plan_until) if paid else None
    return {
        "plan": plan.id,
        "plan_name": plan.name,
        # Next charge date while the subscription renews; else null.
        "renews_at": until if renewing else None,
        # When paid access stops, if it is going to (cancelled, halted); else null.
        "ends_at": until if (paid and not renewing and until) else None,
        "pack_credits": user.pack_credits or 0,
        "quota": {"ai_used": quota.used(user, plan),
                  "ai_limit": plan.ai_reports_per_month,
                  "resets_at": iso(quota.resets_at(user, plan))},
        "byok": {"provider": user.byok_provider, "model": user.byok_model or
                 llm.DEFAULT_MODELS.get(user.byok_provider or "", ""), "set": True}
        if user.byok_cipher else None,
    }


# --- bodies -------------------------------------------------------------------


class AnalysisIn(BaseModel):
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


class ByokIn(BaseModel):
    provider: Literal["openrouter", "openai", "anthropic", "gemini"]
    api_key: str = Field(min_length=8, max_length=500)
    model: str | None = Field(None, max_length=200)


# --- health and badge (no internal key) ---------------------------------------


@public.get("/health")
async def health(request: Request) -> dict[str, Any]:
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
    verdict = latest.report.get("verdict") if latest else None
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
        badge.render(verdict, link),
        media_type="image/svg+xml",
        headers={"Cache-Control": BADGE_CACHE},
    )


BADGE_CACHE = "public, max-age=3600, stale-while-revalidate=86400"


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
    async with svc.db.session() as s:
        return (await s.execute(
            select(Report).where(Report.repo_key == repos.key(repo), Report.mode == mode,
                                 Report.days == days)
            .order_by(Report.created_at.desc(), Report.id.desc()).limit(1)
        )).scalar_one_or_none()


def is_fresh(svc: Services, report: Report) -> bool:
    return now() - utc(report.created_at) < timedelta(hours=svc.settings.cache_hours)


async def active_job(svc: Services, key: str, mode: str, days: int) -> Job | None:
    async with svc.db.session() as s:
        return (await s.execute(
            select(Job).where(Job.dedupe_key == dedupe_key(key, mode, days),
                              Job.status.in_(ACTIVE)).limit(1)
        )).scalar_one_or_none()


async def join_active(svc: Services, key: str, mode: str, days: int,
                      priority: int = USER_PRIORITY) -> Job | None:
    """The in-flight job for this question, promoted to the joiner's priority:
    someone is waiting on it now, even if a badge queued it."""
    job = await active_job(svc, key, mode, days)
    if job is not None and job.priority > priority:
        async with svc.db.session() as s:
            await s.execute(update(Job).where(Job.id == job.id, Job.priority > priority)
                            .values(priority=priority))
            await s.commit()
    return job


async def insert_or_join(svc: Services, job: Job, before_insert=None) -> tuple[Job, bool]:
    """Insert `job` unless an identical one is queued or running; then return that.

    Atomic: the partial unique index on `dedupe_key` decides, so two requests
    racing past the `active_job` check still end up with one job. Whatever
    `before_insert` does in the session (the quota charge) commits with the
    insert or rolls back with it. Returns (job, created).
    """
    async with svc.db.session() as s:
        if before_insert is not None:
            await before_insert(s)
        s.add(job)
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
        else:
            svc.runner.wake()
            return job, True
    existing = await join_active(svc, job.repo_key, job.mode, job.days, job.priority)
    if existing is None:  # finished in between; retry once without the race
        return await insert_or_join(svc, job_copy(job), before_insert)
    return existing, False


def job_copy(job: Job) -> Job:
    return Job(kind=job.kind, repo=job.repo, repo_key=job.repo_key, mode=job.mode,
               days=job.days, params=dict(job.params or {}), user_id=job.user_id,
               key_source=job.key_source, charged=job.charged, priority=job.priority,
               quota_pool=job.quota_pool,
               dedupe_key=job.dedupe_key)


@router.get("/reports", dependencies=[Depends(internal)])
async def list_reports(request: Request,
                       limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
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
    return {"reports": [
        {"repo": repo, "mode": mode, "generated_at": generated or iso(created),
         "verdict": verdict}
        for repo, mode, created, generated, verdict in rows
    ]}


@router.get("/reports/{owner}/{repo}", dependencies=[Depends(internal)])
async def get_report(owner: str, repo: str, request: Request,
                     mode: Literal["rules", "ai"] = "rules",
                     days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    svc = services(request)
    name = repos.normalize(f"{owner}/{repo}")
    latest = await latest_report(svc, name, mode, days)
    if latest is None:
        raise ApiError("not_found", f"There's no report for {name} yet.")
    return latest.report


# --- analyses -------------------------------------------------------------------


@router.post("/analyses")
async def create_analysis(body: AnalysisIn, request: Request,
                          who: Caller = Depends(caller)) -> JSONResponse:
    svc = services(request)
    repo = repos.normalize(body.repo)
    key = repos.key(repo)

    if body.mode == "ai" and not who.user_id:
        raise ApiError("needs_key", "Sign in to get an AI-written report. "
                       "The quick report is free without an account.")

    if not body.refresh:
        cached = await latest_report(svc, repo, body.mode, body.days)
        if cached is not None and is_fresh(svc, cached):
            return JSONResponse({"status": "done", "report": cached.report})

    rate_limit(svc, who)

    user = await get_user(svc, who.user_id) if who.user_id else None
    plan = quota.effective_plan(user, svc.catalog, svc.grace)
    priority = quota.job_priority(plan)

    if existing := await join_active(svc, key, body.mode, body.days, priority):
        return queued(existing.id)

    canonical = await svc.canonical(repo)
    job = Job(kind="analysis", repo=canonical, repo_key=key, mode=body.mode,
              days=body.days, params={"refresh": body.refresh}, user_id=who.user_id,
              dedupe_key=dedupe_key(key, body.mode, body.days), priority=priority)
    charge = None
    if body.mode == "ai":
        if user.byok_cipher:
            # A saved key is used when there is one: the person chose to set
            # it, it is free and unlimited, and it leaves their reports for later.
            job.key_source = "byok"
        else:
            if not svc.server_model_available():
                raise ApiError("needs_key", "AI reports need an API key. Add your own "
                               "key in settings to run one.")
            job.key_source, job.charged = "server", True
            charge = charge_ai(user, plan, job)
    job, _created = await insert_or_join(svc, job, charge)
    return queued(job.id)


def charge_ai(user: User, plan, job: Job):
    """One AI report against the server's key, counted atomically in the same
    transaction as the job insert: a lost dedupe race refunds itself."""

    async def charge(s) -> None:
        pool, window, pack_payment = await quota.charge(s, user, plan)
        job.quota_pool = pool
        job.params = {**(job.params or {}), "ai_period": window,
                      "pack_payment_id": pack_payment}

    return charge


def queued(job_id: str) -> JSONResponse:
    return JSONResponse({"status": "queued", "job_id": job_id}, status_code=202)


async def load_job(svc: Services, job_id: str, kind: str) -> Job:
    async with svc.db.session() as s:
        job = await s.get(Job, job_id[:64])
    if job is None or job.kind != kind:
        raise ApiError("not_found", "We couldn't find that check. It may have expired.")
    return job


def job_body(job: Job) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": job.status,
        "stage": job.stage,
        "progress": round(job.progress or 0.0, 3),
        "error": job.error if job.status == "error" else None,
    }
    if job.kind == "find":
        body["results"] = (job.result or {}).get("results") if job.status == "done" else None
    else:
        body["report"] = job.result if job.status == "done" else None
    return body


@router.get("/analyses/{job_id}", dependencies=[Depends(internal)])
async def get_analysis(job_id: str, request: Request) -> dict[str, Any]:
    return job_body(await load_job(services(request), job_id, "analysis"))


@router.get("/analyses/{job_id}/events", dependencies=[Depends(internal)])
async def analysis_events(job_id: str, request: Request) -> StreamingResponse:
    svc = services(request)
    await load_job(svc, job_id, "analysis")
    return sse(svc, job_id, "analysis", request)


# --- server-sent events ---------------------------------------------------------


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


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
                    current = (job.stage, round(job.progress or 0.0, 3))
                    if current != last:
                        last = current
                        yield sse_event("stage", {"stage": current[0], "progress": current[1]})
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
    return row if row is not None and utc(row.created_at) >= cutoff else None


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
        issues = await asyncio.to_thread(
            starter.run_starter_issues, canonical, svc.pool.next(), STARTER_CACHE_LIMIT)
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
        await s.commit()
    return canonical, issues


@router.get("/repos/{owner}/{repo}/starter-issues")
async def starter_issues(owner: str, repo: str, request: Request,
                         limit: int = Query(20, ge=1, le=50),
                         who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    name = repos.normalize(f"{owner}/{repo}")
    # A cache hit costs nothing: no rate limit, no GitHub.
    if (hit := await cached_starter_issues(svc, name)) is not None:
        return {"repo": hit.repo, "issues": hit.issues[:limit]}
    starter.function("starter_issues")  # 501 before spending a rate-limit hit
    rate_limit(svc, who, "read")
    canonical, issues = await fetch_starter_issues(svc, name)
    return {"repo": canonical, "issues": issues[:limit]}


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
    """Fresh cached results that can answer a request for `limit`, or None."""
    cutoff = now() - timedelta(hours=svc.settings.find_cache_hours)
    async with svc.db.session() as s:
        row = await s.get(FindCache, key)
    if row is None or utc(row.created_at) < cutoff:
        return None
    computed_for = int((row.params or {}).get("limit") or 0)
    # Enough results, or the search ran out before its own limit (so asking
    # for more would find nothing new).
    if computed_for >= limit or len(row.results) < computed_for:
        return row.results[:limit]
    return None


async def active_find(svc: Services, key: str) -> Job | None:
    async with svc.db.session() as s:
        return (await s.execute(select(Job).where(
            Job.dedupe_key == f"find:{key}", Job.status.in_(ACTIVE)).limit(1)
        )).scalar_one_or_none()


@router.post("/find")
async def find(body: FindIn, request: Request, who: Caller = Depends(caller)) -> JSONResponse:
    svc = services(request)
    starter.function("find")
    params = find_params(body)
    key = find_key(params["languages"], params["topics"], params["hacktoberfest"], body.days)
    # Cached, or already being searched for someone else: free, no rate limit.
    if (results := await cached_find(svc, key, body.limit)) is not None:
        return JSONResponse({"status": "done", "results": results})
    if (running := await active_find(svc, key)) is not None:
        return queued(running.id)
    rate_limit(svc, who)
    async with svc.db.session() as s:
        job = Job(kind="find", mode="rules", days=body.days, params=params,
                  user_id=who.user_id, dedupe_key=f"find:{key}")
        s.add(job)
        try:
            await s.commit()
        except IntegrityError:  # an identical search started a moment ago
            await s.rollback()
            if (running := await active_find(svc, key)) is not None:
                return queued(running.id)
            raise
    svc.runner.wake()
    return queued(job.id)


@router.get("/find/{job_id}", dependencies=[Depends(internal)])
async def get_find(job_id: str, request: Request) -> dict[str, Any]:
    return job_body(await load_job(services(request), job_id, "find"))


@router.get("/find/{job_id}/events", dependencies=[Depends(internal)])
async def find_events(job_id: str, request: Request) -> StreamingResponse:
    svc = services(request)
    await load_job(svc, job_id, "find")
    return sse(svc, job_id, "find", request)


# --- account ----------------------------------------------------------------------


@router.get("/me")
async def me(request: Request, who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    return await me_body(svc, await get_user(svc, signed_in(who)))


@router.put("/me/byok")
async def put_byok(body: ByokIn, request: Request,
                   who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    await get_user(svc, user_id)
    try:
        cipher = crypto.encrypt(svc.settings.secret_key, body.api_key.strip(), user_id)
    except crypto.SecretKeyMissing as exc:
        raise ApiError("internal", "Saving keys isn't set up on this server yet.") from exc
    async with svc.db.session() as s:
        user = await s.get(User, user_id)
        user.byok_provider = body.provider
        user.byok_model = (body.model or "").strip() or None
        user.byok_cipher = cipher
        await s.commit()
    return await me_body(svc, user)


@router.delete("/me/byok")
async def delete_byok(request: Request, who: Caller = Depends(caller)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    await get_user(svc, user_id)
    async with svc.db.session() as s:
        user = await s.get(User, user_id)
        user.byok_provider = user.byok_model = user.byok_cipher = None
        await s.commit()
    return await me_body(svc, user)


@router.get("/me/history")
async def history(request: Request, who: Caller = Depends(caller),
                  limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    svc = services(request)
    user_id = signed_in(who)
    async with svc.db.session() as s:
        jobs = (await s.execute(
            select(Job).where(Job.user_id == user_id, Job.kind == "analysis")
            .order_by(Job.created_at.desc()).limit(limit)
        )).scalars().all()
    return {"items": [
        {
            "job_id": j.id,
            "repo": j.repo,
            "mode": j.mode,
            "days": j.days,
            "status": j.status,
            "verdict": (j.result or {}).get("verdict"),
            "headline": (j.result or {}).get("headline"),
            "created_at": iso(j.created_at),
        }
        for j in jobs
    ]}
