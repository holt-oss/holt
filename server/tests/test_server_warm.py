"""The warm pass, with the engine, starter module and GitHub budget faked."""

from __future__ import annotations

import sys
import types

import pytest
from holt_server import warm
from holt_server.db import BADGE_PRIORITY, FindCache, Job, StarterCache


@pytest.fixture(autouse=True)
def quick_polling(monkeypatch):
    monkeypatch.setattr(warm, "POLL_S", 0.02)


@pytest.fixture
def starter_mod(monkeypatch):
    mod = types.ModuleType("holt.starter")
    mod.calls = {"find": 0, "issues": 0}

    def find(languages, topics, hacktoberfest, token, limit, screen=None, progress=None,
             days=7):
        mod.calls["find"] += 1
        return [{"repo": "octo/one", "verdict": "viable", "stats": {}, "issues": []}]

    def starter_issues(repo, token, limit, as_of=None):
        mod.calls["issues"] += 1
        return [{"number": 1, "title": "t"}]

    mod.find, mod.starter_issues = find, starter_issues
    monkeypatch.setitem(sys.modules, "holt.starter", mod)
    return mod


def budget(h, *values):
    """GitHub points left, in turn, for each budget check (last one repeats)."""
    seq = list(values)

    async def remaining():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    h.svc.lookup.remaining = remaining


def rows(h, model):
    from sqlalchemy import select

    async def q():
        async with h.svc.db.session() as s:
            return (await s.execute(select(model))).scalars().all()
    return h.client.portal.call(q)


def run(h, seeds, **kw):
    return h.client.portal.call(lambda: warm.warm_once(h.svc, seeds=seeds, **kw))


def test_seed_file_parsing(tmp_path):
    path = tmp_path / "seeds.txt"
    path.write_text("# comment\n\npallets/flask\nhttps://github.com/Pallets/Flask\n"
                    "octo/one  # trailing\nnot a repo\n", encoding="utf-8")
    assert warm.load_seeds(path) == ["pallets/flask", "octo/one"]


def test_committed_seed_list_is_usable():
    seeds = warm.load_seeds()
    assert 9500 <= len(seeds) <= 10500
    assert len({s.lower() for s in seeds}) == len(seeds)


def test_profiles_match_the_web_pages():
    keys = {p.key for p in warm.profiles()}
    assert len(keys) == len(warm.profiles()) == 23
    tab = warm.Profile(("javascript", "typescript"), True)
    assert tab.key in keys and warm.Profile(("python",), False).key in keys
    assert warm.Profile((), True).key in keys  # "All languages"


def test_full_pass_then_nothing_left_to_do(h, starter_mod):
    budget(h, 5000)
    h.wait(h.post("/v1/analyses", {"repo": "octo/one"}).json()["job_id"])  # already fresh
    result = run(h, ["octo/one", "octo/two", "pallets/flask"])
    assert (result.reports_run, result.reports_fresh, result.reports_failed) == (2, 1, 0)
    assert result.starter_run == 3 and result.finds_run == 23 and result.stopped is None
    warm_jobs = [j for j in rows(h, Job) if j.priority == BADGE_PRIORITY]
    assert len(warm_jobs) == 2 + 23  # reports and finds, all at badge priority
    assert len(rows(h, StarterCache)) == 3 and len(rows(h, FindCache)) == 23

    again = run(h, ["octo/one", "octo/two", "pallets/flask"])
    assert (again.reports_run, again.starter_run, again.finds_run) == (0, 0, 0)
    assert (again.reports_fresh, again.starter_fresh, again.finds_fresh) == (3, 3, 23)


def test_warmed_pages_cost_visitors_nothing(make_harness, starter_mod):
    h = make_harness(HOLT_ANON_RATE_PER_HOUR=1, HOLT_ANON_READ_RATE_PER_HOUR=1)
    budget(h, 5000)
    run(h, ["octo/one", "octo/two"])
    calls = dict(starter_mod.calls)
    for _ in range(5):
        r = h.post("/v1/find", {"languages": ["python"], "hacktoberfest": True}, ip="9.9.9.9")
        assert r.status_code == 200
        assert h.post("/v1/find", {"languages": ["javascript", "typescript"],
                                   "hacktoberfest": True}, ip="9.9.9.9").status_code == 200
        assert h.get("/v1/repos/octo/two/starter-issues", ip="9.9.9.9").status_code == 200
        assert h.post("/v1/analyses", {"repo": "octo/two"}, ip="9.9.9.9").status_code == 200
    assert starter_mod.calls == calls  # no GitHub work at request time


def test_stops_when_github_budget_runs_low(h, starter_mod):
    budget(h, 100)
    result = run(h, ["octo/one", "octo/two"])
    assert result.stopped.startswith("GitHub points left 100")
    assert result.reports_run == 0 and rows(h, Job) == []


def test_budget_is_rechecked_before_every_report(h, starter_mod):
    budget(h, 5000, 10)  # plenty at the first check, nearly gone at the next
    seeds = ["octo/one", "octo/two", "octo/three", "octo/four", "pallets/flask", "NixOS/nixpkgs"]
    result = run(h, seeds, starter=False, finds=False)
    assert result.stopped.startswith("GitHub points left 10") and result.reports_run == 1


def test_rate_limited_job_stops_the_pass(h, starter_mod):
    from holt_server.errors import ApiError

    budget(h, 5000)
    h.engine.error = ApiError("rate_limited", "slow down", retry_after=60)
    seeds = ["octo/one", "octo/two", "octo/three", "octo/four", "pallets/flask", "NixOS/nixpkgs"]
    result = run(h, seeds, starter=False, finds=False)
    assert result.stopped.startswith("GitHub asked us to slow down (a rate limit")
    assert "again in about 1 minute" in result.stopped
    # A rate limit is no repository's failure, and only the reports already
    # in flight were asked for.
    assert result.reports_failed == 0 and result.left == len(seeds)
    assert 1 <= len(h.engine.calls) <= h.svc.settings.warm_parallel < len(seeds)


def test_dry_run_changes_nothing(h, starter_mod):
    async def boom():
        raise AssertionError("no GitHub in a dry run")

    h.svc.lookup.remaining = boom
    lines = []
    result = run(h, ["octo/one", "octo/two"], dry_run=True, say=lines.append)
    assert result.reports_run == 2 and result.finds_run == 23
    assert rows(h, Job) == [] and starter_mod.calls == {"find": 0, "issues": 0}
    assert "would analyse octo/one" in lines
    assert f"the reports would use about {2 * warm.REPORT_POINTS_TYPICAL} GitHub points" in (
        result.summary())


def test_a_timed_out_job_fails_its_repo_and_the_pass_goes_on(h, starter_mod, monkeypatch):
    budget(h, 5000)
    real = warm.Warmer._run_job

    async def flaky(self, job):
        if job.repo == "octo/one":
            raise TimeoutError("job for octo/one still running after 900s")
        return await real(self, job)

    monkeypatch.setattr(warm.Warmer, "_run_job", flaky)
    result = run(h, ["octo/one", "octo/two"], starter=False, finds=False)
    assert result.stopped is None
    assert (result.reports_run, result.reports_failed) == (1, 1)
    assert "octo/one: timed out" in result.failures


def test_repeated_timeouts_stop_the_pass(h, starter_mod, monkeypatch):
    budget(h, 5000)

    async def never(self, job):
        raise TimeoutError("still running")

    monkeypatch.setattr(warm.Warmer, "_run_job", never)
    result = run(h, ["octo/one", "octo/two", "octo/three", "octo/four"],
                 starter=False, finds=False, parallel=1)
    assert "never finished" in result.stopped and result.reports_failed == 3


def test_seed_list_ships_inside_the_package():
    from pathlib import Path

    import holt_server

    assert warm.SEEDS.is_relative_to(Path(holt_server.__file__).parent)
    assert warm.SEEDS.is_file()


# --- several reports in flight -------------------------------------------------------

MANY = [f"octo/r{i}" for i in range(7)]


def until(check, timeout=20.0):
    import time

    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


class Held:
    """Wraps the fake engine: counts the reports running at once, and holds
    each until `release` is set (or `hold_until` of them are running)."""

    def __init__(self, h, hold_until: int | None = None):
        import threading

        self.release = threading.Event()
        self.lock = threading.Lock()
        self.running = self.peak = 0
        self.hold_until = hold_until
        self.real = h.svc.analysis_fn
        h.svc.analysis_fn = self

    def __call__(self, **kw):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
            if self.hold_until and self.running >= self.hold_until:
                self.release.set()
        try:
            self.release.wait(30)
            return self.real(**kw)
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture
def short_jobs(monkeypatch):
    # A test that goes wrong fails in seconds instead of waiting 15 minutes.
    monkeypatch.setattr(warm, "JOB_TIMEOUT_S", 45)


def test_keeps_warm_parallel_reports_in_flight(make_harness, short_jobs):
    # A badge lane wider than the pass: the pass is what keeps it at three.
    h = make_harness(HOLT_BADGE_CONCURRENCY=5, HOLT_WARM_PARALLEL=3)
    budget(h, 5000)
    held = Held(h, hold_until=3)  # each waits until three are running
    result = run(h, MANY, starter=False, meta=False, finds=False)
    assert (result.reports_run, result.stopped) == (len(MANY), None)
    assert held.peak == 3
    assert all(j.priority == BADGE_PRIORITY for j in rows(h, Job))


def test_peoples_checks_still_go_before_queued_warm_reports(make_harness, short_jobs):
    h = make_harness(HOLT_JOB_CONCURRENCY=1, HOLT_BADGE_CONCURRENCY=1, HOLT_WARM_PARALLEL=3)
    budget(h, 5000)
    held = Held(h)
    try:
        # Two people's checks hold both lanes (the badge lane takes people's
        # jobs too), so the pass's three reports wait in the queue.
        h.post("/v1/analyses", {"repo": "octo/one"})
        h.post("/v1/analyses", {"repo": "octo/three"})
        until(lambda: held.running == 2)
        warming = h.client.portal.start_task_soon(lambda: warm.warm_once(
            h.svc, seeds=MANY[:4], starter=False, meta=False, finds=False))
        until(lambda: [j.status for j in rows(h, Job) if j.priority == BADGE_PRIORITY]
              == ["queued"] * 3)
        person = h.post("/v1/analyses", {"repo": "octo/two"}).json()["job_id"]
    finally:
        held.release.set()
    assert warming.result(timeout=60).reports_run == 4
    jobs = {j.id: j for j in rows(h, Job)}
    queued_warm = [j for j in jobs.values()
                   if j.priority == BADGE_PRIORITY and j.created_at <= jobs[person].created_at]
    assert len(queued_warm) == 3  # queued before the person's check...
    assert all(jobs[person].started_at <= j.started_at for j in queued_warm)  # ...started after


def test_budget_guard_counts_the_reports_in_flight(make_harness, short_jobs):
    h = make_harness(HOLT_BADGE_CONCURRENCY=3, HOLT_WARM_PARALLEL=3)
    held = Held(h)
    checks = []

    async def remaining():
        checks.append(1)
        if len(checks) == 3:
            held.release.set()  # the two in flight may finish now
        # Room for this report and one in flight, not two.
        return h.svc.settings.warm_min_points + warm.REPORT_POINTS + 5

    h.svc.lookup.remaining = remaining
    result = run(h, MANY, starter=False, meta=False, finds=False)
    assert result.stopped == (f"GitHub points left {1500 + warm.REPORT_POINTS + 5}, "
                              f"{1500 - warm.REPORT_POINTS + 5} after the 2 reports in "
                              "flight, < 1500")
    assert len(checks) == 3 and result.reports_run == 2  # the two in flight finished
    assert len(h.engine.calls) == 2


def test_wait_for_budget_waits_instead_of_stopping(h, monkeypatch):
    monkeypatch.setattr(warm, "BUDGET_WAIT_S", 0.01)
    budget(h, 5000, 100, 100, 5000)
    lines = []
    result = run(h, MANY[:3], starter=False, meta=False, finds=False, parallel=1,
                 wait_for_budget=True, say=lines.append)
    assert (result.reports_run, result.stopped) == (3, None)
    assert sum("looking again" in line for line in lines) == 2


# --- seeds that can't take outside work go last ----------------------------------------


def test_closed_and_dormant_seeds_go_last(h):
    from datetime import timedelta

    from holt_server.db import ENGINE_VERSION, RepoMeta, Report, now

    from conftest import canned_report

    def meta(repo, **kw):
        return RepoMeta(repo_key=repo.lower(), repo=repo, **kw)

    def report(repo, codes):
        return Report(repo=repo, repo_key=repo.lower(), mode="rules", days=7,
                      report={**canned_report(repo, verdict="not_viable"), "rule_codes": codes},
                      created_at=now() - timedelta(days=3), engine_version=ENGINE_VERSION)

    async def add():
        async with h.svc.db.session() as s:
            s.add_all([
                report("octo/one", ["prs_closed"]),                   # GitHub's PR settings
                report("octo/two", ["merges", "slow_note"]),          # an ordinary answer
                meta("octo/two", pushed_at=now() - timedelta(days=5)),
                meta("octo/three", pushed_at=now() - timedelta(days=200)),  # dormant
                meta("octo/four", archived=True),
                report("NixOS/nixpkgs", ["inactive"]),
            ])
            await s.commit()

    h.client.portal.call(add)
    seeds = ["octo/one", "octo/two", "octo/three", "octo/four", "NixOS/nixpkgs", "pallets/flask"]
    ordered, back = h.client.portal.call(lambda: warm.quiet_last(h.svc, seeds))
    assert ordered == ["octo/two", "pallets/flask",
                       "octo/one", "octo/three", "octo/four", "NixOS/nixpkgs"]
    assert back == 4

    lines = []
    result = run(h, seeds, dry_run=True, starter=False, meta=False, finds=False,
                 say=lines.append)
    assert [x.removeprefix("would analyse ") for x in lines if x.startswith("would")] == ordered
    assert result.quiet_last == 4 and "4 closed or dormant seeds last" in result.summary()


def test_seed_rename_is_fixed():
    seeds = {s.lower() for s in warm.load_seeds()}
    assert "czaydev/better-payment" in seeds and "furkanczay/better-payment" not in seeds
