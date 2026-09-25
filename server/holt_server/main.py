"""App factory and `holt-server` entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from holt_server import __version__, errors
from holt_server.api import public, router
from holt_server.services import Services
from holt_server.settings import Settings, get_settings


def create_app(settings: Settings | None = None, services: Services | None = None,
               run_jobs: bool = True) -> FastAPI:
    svc = services or Services(settings or get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await svc.db.create_all()
        if run_jobs:
            await svc.runner.start()
        try:
            yield
        finally:
            if run_jobs:
                await svc.runner.stop()
            await svc.db.dispose()
            svc.http.close()

    dev = svc.settings.env == "dev"
    app = FastAPI(title="Holt API", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if dev else None, redoc_url=None,
                  openapi_url="/openapi.json" if dev else None)
    app.state.services = svc
    errors.install(app)
    app.include_router(public)
    app.include_router(router)
    return app


def run() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run(
        "holt_server.main:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=False,
    )
