"""App factory and `holt-server` entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from holt_server import (
    __version__,
    account_mail,
    account_merge,
    admin,
    alerts_api,
    budget,
    connections,
    contributions,
    credits,
    discover,
    entitlements,
    errors,
    feedback,
    find,
    mailer,
    merge_plan,
    metrics,
    payments,
    playbook,
    preflight,
    pro,
    profiles,
    recommendations,
    saved,
    watch,
)
from holt_server.api import public, router
from holt_server.services import Services
from holt_server.settings import Settings, get_settings


def create_app(settings: Settings | None = None, services: Services | None = None,
               run_jobs: bool = True) -> FastAPI:
    svc = services or Services(settings or get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        entitlements.catalogue(svc)  # a broken pricing file stops startup here
        await svc.db.migrate()
        if run_jobs:
            await svc.runner.start()
        warming = None
        level, line = budget.startup_line(svc.settings)
        logging.getLogger("holt_server.budget").log(level, line)
        payments.log.log(*payments.startup_line(svc))
        # A readiness line in the log; it never holds up startup.
        pro_check = asyncio.create_task(_log_pro(svc), name="holt-pro-check")
        if run_jobs and svc.settings.warm_interval_hours > 0:
            from holt_server import warm

            warming = asyncio.create_task(warm.schedule(svc), name="holt-warm")
        refreshing = None
        if run_jobs and svc.settings.contributions_refresh_hours > 0:
            refreshing = asyncio.create_task(contributions.schedule(svc),
                                             name="holt-contributions")
        # PR watch: the checker and the mailer, only when switched on.
        watching = mailing = None
        if run_jobs and svc.settings.pr_watch:
            watching = asyncio.create_task(watch.schedule(svc), name="holt-pr-watch")
            mailing = asyncio.create_task(mailer.schedule(svc), name="holt-alert-mail")
        # Account emails (the welcome, receipts, the "ending" ones), when on.
        account_mailing = None
        if run_jobs and svc.settings.account_emails:
            account_mailing = asyncio.create_task(account_mail.schedule(svc),
                                                  name="holt-account-mail")
        try:
            yield
        finally:
            pro_check.cancel()
            await asyncio.gather(pro_check, return_exceptions=True)
            for task in (warming, refreshing, watching, mailing, account_mailing,
                         *account_mail._background):
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            if run_jobs:
                await svc.runner.stop()
            await svc.db.dispose()
            svc.http.close()
            if svc.pro is not None:
                await svc.pro.aclose()
            if svc.razorpay is not None:
                svc.razorpay.close()
            if svc.dodo is not None:
                svc.dodo.close()

    dev = svc.settings.env == "dev"
    app = FastAPI(title="Holt API", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if dev else None, redoc_url=None,
                  openapi_url="/openapi.json" if dev else None)
    app.state.services = svc
    errors.install(app)
    app.add_middleware(metrics.HttpMetrics, metrics=svc.metrics)
    app.include_router(metrics.router)
    app.include_router(public)
    app.include_router(router)
    app.include_router(credits.router)
    app.include_router(admin.router)
    app.include_router(feedback.router)
    app.include_router(connections.router)
    app.include_router(account_merge.router)
    app.include_router(contributions.router)
    app.include_router(alerts_api.router)
    app.include_router(account_mail.router)
    app.include_router(discover.router)
    app.include_router(find.router)
    app.include_router(profiles.router)
    app.include_router(payments.router)
    app.include_router(playbook.router)
    app.include_router(recommendations.router)
    app.include_router(saved.router)
    app.include_router(preflight.router)
    app.include_router(merge_plan.router)
    return app


async def _log_pro(svc: Services) -> None:
    if svc.pro is None:
        return
    ok, line = await pro.check(svc.pro)
    logging.getLogger("holt_server.pro").log(logging.INFO if ok else logging.WARNING, line)


def run() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    logging.getLogger("alembic").setLevel(logging.WARNING)
    uvicorn.run(
        "holt_server.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=False,
    )
