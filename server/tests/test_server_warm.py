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
    assert 250 <= len(seeds) <= 400
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


def test_budget_is_rechecked_as_it_goes(h, starter_mod):
    budget(h, 5000, 10)  # plenty at the first check, nearly gone at the next
    seeds = ["octo/one", "octo/two", "octo/three", "octo/four", "pallets/flask", "NixOS/nixpkgs"]
    result = run(h, seeds, starter=False, finds=False)
    assert result.stopped and result.reports_run == warm.BUDGET_EVERY


def test_rate_limited_job_stops_the_pass(h, starter_mod):
    from holt_server.errors import ApiError

    budget(h, 5000)
    h.engine.error = ApiError("rate_limited", "slow down", retry_after=60)
    result = run(h, ["octo/one", "octo/two"], starter=False, finds=False)
    assert result.stopped == "GitHub rate limit reached"
    assert result.reports_failed == 1


def test_dry_run_changes_nothing(h, starter_mod):
    async def boom():
        raise AssertionError("no GitHub in a dry run")

    h.svc.lookup.remaining = boom
    lines = []
    result = run(h, ["octo/one", "octo/two"], dry_run=True, say=lines.append)
    assert result.reports_run == 2 and result.finds_run == 23
    assert rows(h, Job) == [] and starter_mod.calls == {"find": 0, "issues": 0}
    assert "would analyse octo/one" in lines


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
                 starter=False, finds=False)
    assert "never finished" in result.stopped and result.reports_failed == 3


def test_seed_list_ships_inside_the_package():
    from pathlib import Path

    import holt_server

    assert warm.SEEDS.is_relative_to(Path(holt_server.__file__).parent)
    assert warm.SEEDS.is_file()
