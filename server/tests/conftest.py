"""Server test harness: SQLite instead of Postgres, the engine and GitHub faked.

Nothing here touches the network. `canonical` (the GitHub lookup) is replaced
with a dictionary, and `analysis_fn` with a function that returns a canned
report unless a test swaps in the real engine over the replay fixtures.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from holt_server.errors import not_found_repo
from holt_server.main import create_app
from holt_server.services import Services
from holt_server.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
KEY = "test-internal-key"
H = {"X-Holt-Internal-Key": KEY}

KNOWN = {r.lower(): r for r in (
    "pallets/flask", "NixOS/nixpkgs", "octo/one", "octo/two", "octo/three", "octo/four",
)}


def canned_report(repo: str, mode: str = "rules", days: int = 7,
                  verdict: str = "viable") -> dict[str, Any]:
    headline = {"viable": "Worth your time", "not_viable": "Not worth your time",
                "insufficient_evidence": "Not enough evidence"}[verdict]
    return {
        "repo": repo, "mode": mode, "days": days, "verdict": verdict,
        "headline": headline, "summary": "ok" if mode == "ai" else None,
        "stats": {}, "decided_by": [], "unknowns": [], "landing": [],
        "never_landed": [], "evidence": [], "evidence_until": None,
        "generated_at": "2026-09-25T00:00:00Z",
        "cost": {"model": "m", "input_tokens": 1, "output_tokens": 1} if mode == "ai" else None,
    }


class FakeEngine:
    """Stands in for `engine.analyze`. `gate` holds jobs mid-run when cleared."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.gate = threading.Event()
        self.gate.set()
        self.error: Exception | None = None
        self.verdict = "viable"

    def __call__(self, *, repo, mode, days, provider, model, emit, as_of):
        self.calls.append({"repo": repo, "mode": mode, "days": days, "model": model})
        emit("Fetching pull requests", 0.1)
        self.gate.wait(10)
        emit("Reading threads", 0.5)
        if self.error is not None:
            raise self.error
        return canned_report(repo, mode, days, self.verdict)


# Small numbers so tests can run a pool dry. Razorpay plan ids are set for
# student (INR) and pro (INR) only; pro in USD has none, to test that path.
TEST_PLANS = """
[plans.free]
name = "Free"
ai_reports_per_month = 2

[plans.student]
name = "Student"
ai_reports_per_month = 3
priority = true
prices = [{ currency = "INR", amount = 9900, interval = "month", razorpay_plan_id = "plan_student_inr" }]

[plans.pro]
name = "Pro"
ai_reports_per_month = 5
priority = true
prices = [
  { currency = "INR", amount = 29900, interval = "month", razorpay_plan_id = "plan_pro_inr" },
  { currency = "USD", amount = 500, interval = "month" },
]

[packs.pack10]
name = "10 AI reports"
reports = 10
prices = [{ currency = "INR", amount = 4900 }]
"""


def write_plans(tmp_path: Path, text: str = TEST_PLANS) -> Path:
    path = tmp_path / "plans.toml"
    path.write_text(text, encoding="utf-8")
    return path


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values = {
        # Set HOLT_TEST_DATABASE_URL to run against a real Postgres (e.g. the
        # one in server/compose.yml). Its tables are dropped for every harness.
        "DATABASE_URL": os.environ.get("HOLT_TEST_DATABASE_URL")
        or f"sqlite+aiosqlite:///{tmp_path / 'holt.db'}",
        "HOLT_INTERNAL_KEY": KEY,
        "HOLT_SECRET_KEY": "a test passphrase",
        "GITHUB_TOKENS": "tok1,tok2",
        "OPENROUTER_API_KEY": "",
        "HOLT_ANON_RATE_PER_HOUR": 100,
        "HOLT_USER_RATE_PER_HOUR": 100,
        "HOLT_PLANS_FILE": str(write_plans(tmp_path)),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Harness:
    def __init__(self, client: TestClient, services: Services, engine: FakeEngine) -> None:
        self.client = client
        self.svc = services
        self.engine = engine
        self.model_specs: list[Any] = []

    def post(self, path: str, json: Any = None, user: str | None = None,
             ip: str | None = "10.0.0.1", **kw):
        return self.client.post(path, json=json, headers=self.headers(user, ip), **kw)

    def get(self, path: str, user: str | None = None, ip: str | None = "10.0.0.1", **kw):
        return self.client.get(path, headers=self.headers(user, ip), **kw)

    def put(self, path: str, json: Any = None, user: str | None = None):
        return self.client.put(path, json=json, headers=self.headers(user))

    def delete(self, path: str, user: str | None = None):
        return self.client.delete(path, headers=self.headers(user))

    @staticmethod
    def headers(user: str | None = None, ip: str | None = "10.0.0.1") -> dict[str, str]:
        h = dict(H)
        if user:
            h["X-Holt-User"] = user
        if ip:
            h["X-Holt-Client-Ip"] = ip
        return h

    def wait(self, job_id: str, kind: str = "analyses", timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.get(f"/v1/{kind}/{job_id}").json()
            if body["status"] in ("done", "error"):
                return body
            time.sleep(0.05)
        raise AssertionError(f"job {job_id} did not finish: {body}")


@pytest.fixture
def make_harness(tmp_path):
    clients: list[TestClient] = []

    def build(run_jobs: bool = True, **overrides: Any) -> Harness:
        settings = make_settings(tmp_path, **overrides)
        services = Services(settings)
        if os.environ.get("HOLT_TEST_DATABASE_URL"):
            import asyncio

            from holt_server.db import Base

            async def reset():
                async with services.db.engine.begin() as conn:
                    await conn.run_sync(Base.metadata.drop_all)
                await services.db.engine.dispose()

            asyncio.run(reset())
        engine = FakeEngine()
        services.analysis_fn = engine

        async def canonical(repo: str) -> str:
            try:
                return KNOWN[repo.lower()]
            except KeyError:
                raise not_found_repo(repo) from None

        services.canonical = canonical
        services.provider_factory = lambda repo, as_of: None
        harness_specs: list[Any] = []

        def model_factory(spec):
            harness_specs.append(spec)
            return object()

        services.model_factory = model_factory
        client = TestClient(create_app(services=services, run_jobs=run_jobs))
        client.__enter__()
        clients.append(client)
        h = Harness(client, services, engine)
        h.model_specs = harness_specs
        return h

    yield build
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def h(make_harness) -> Harness:
    return make_harness()
