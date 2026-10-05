"""The warm pass when GitHub can't answer for some seeds, or asks it to slow
down: failed seeds go to the back and wait, a rate limit pauses the pass
instead of ending it, and the healthy seeds behind are still reported.
The engine is faked; the last tests put the real token pool and transport
under it, answered by `httpx.MockTransport`. Nothing reaches GitHub."""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta

import httpx
import pytest
from holt_server import engine, github, warm
from holt_server.db import WarmFailure, now, utc
from holt_server.errors import ApiError, not_found_repo, upstream
from sqlalchemy import select, update

from conftest import canned_report
from holt.evidence import github_graphql as gql
from test_server_github_limits import (
    Clock,
    FakeGitHub,
    bad_gateway,
    forbidden,
    missing,
    secondary_limit,
)

HOUR = timedelta(hours=1)


class Time:
    """The pass's clock for its pauses: a wait is over as soon as it starts."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def pauses(monkeypatch) -> Time:
    time = Time()
    monkeypatch.setattr(warm, "POLL_S", 0.02)
    monkeypatch.setattr(warm, "clock", time.clock)
    monkeypatch.setattr(warm, "sleep", time.sleep)
    return time


def slow_down(retry_after=None) -> ApiError:
    return ApiError("rate_limited", "GitHub is asking us to slow down.", retry_after=retry_after)


class Engine:
    """Wraps the fake engine: `errors[repo]` fails that repository's report
    (a list fails it that many times, then it works)."""

    def __init__(self, h) -> None:
        self.errors: dict[str, object] = {}
        self.calls: list[str] = []
        self.lock = threading.Lock()
        self.running = 0
        self.peak_when_slow = 0
        self.slowed = False
        self.real = h.svc.analysis_fn
        h.svc.analysis_fn = self

        async def remaining():
            return 5000

        h.svc.lookup.remaining = remaining

    def __call__(self, **kw):
        repo = kw["repo"]
        with self.lock:
            self.calls.append(repo)
            self.running += 1
            if self.slowed:
                self.peak_when_slow = max(self.peak_when_slow, self.running)
            err = self.errors.get(repo)
            if isinstance(err, list):
                err = err.pop(0) if err else None
        try:
            if err is not None:
                if getattr(err, "code", "") == "rate_limited":
                    self.slowed = True
                raise err
            return self.real(**kw)
        finally:
            with self.lock:
                self.running -= 1


def run(h, seeds, **kw):
    kw = {"starter": False, "meta": False, "finds": False, **kw}
    return h.client.portal.call(lambda: warm.warm_once(h.svc, seeds=seeds, **kw))


def failures(h) -> dict[str, WarmFailure]:
    async def q():
        async with h.svc.db.session() as s:
            return {f.repo: f for f in (await s.execute(select(WarmFailure))).scalars()}
    return h.client.portal.call(q)


def make_due(h, repo):
    """As if `repo`'s wait were over."""
    async def go():
        async with h.svc.db.session() as s:
            await s.execute(update(WarmFailure).where(WarmFailure.repo == repo)
                            .values(retry_at=now() - HOUR))
            await s.commit()
    h.client.portal.call(go)


SEEDS = ["octo/one", "octo/two", "octo/three"]


def test_a_failed_seed_waits_then_goes_last_and_each_failure_doubles_the_wait(h):
    eng = Engine(h)
    eng.errors["octo/one"] = upstream()
    h.svc.settings.warm_max_age_hours = 0  # every seed is due every pass

    first = run(h, SEEDS, parallel=1)
    assert (first.reports_run, first.reports_failed, first.skipped_failed) == (2, 1, 0)
    row = failures(h)["octo/one"]
    assert (row.code, row.failures) == ("upstream", 1)
    assert 5.9 * HOUR < utc(row.retry_at) - now() < 6.1 * HOUR

    eng.calls.clear()
    again = run(h, SEEDS, parallel=1)
    assert eng.calls == ["octo/two", "octo/three"]  # not asked for again so soon
    assert (again.reports_run, again.reports_failed, again.skipped_failed) == (2, 0, 1)
    assert "1 skipped as recently failed" in again.summary()
    assert "1 still without a current report" in again.summary()

    make_due(h, "octo/one")
    eng.calls.clear()
    third = run(h, SEEDS, parallel=1)
    assert eng.calls == ["octo/two", "octo/three", "octo/one"]  # due again: at the back
    assert (third.reports_failed, third.skipped_failed, third.failed_last) == (1, 0, 1)
    row = failures(h)["octo/one"]
    assert row.failures == 2 and 11.9 * HOUR < utc(row.retry_at) - now() < 12.1 * HOUR

    make_due(h, "octo/one")
    del eng.errors["octo/one"]
    assert run(h, SEEDS, parallel=1).reports_run == 3
    assert failures(h) == {}  # a report was made: nothing to remember


def test_the_wait_grows_to_a_week_and_no_further():
    hours = [warm.retry_delay("upstream", n) / HOUR for n in range(1, 9)]
    assert hours == [6, 12, 24, 48, 96, 168, 168, 168]
    assert warm.retry_delay("not_found", 1) == warm.retry_delay("not_found", 5) == 30 * 24 * HOUR


def test_a_report_made_some_other_way_clears_the_failure(h):
    eng = Engine(h)
    eng.errors["octo/one"] = [upstream()]
    run(h, SEEDS)
    assert "octo/one" in failures(h)
    h.wait(h.post("/v1/analyses", {"repo": "octo/one"}).json()["job_id"])  # a person's check
    again = run(h, SEEDS)
    assert (again.reports_fresh, again.skipped_failed) == (3, 0) and failures(h) == {}


def test_missing_repositories_are_remembered_and_listed_for_the_seed_list(h):
    eng = Engine(h)
    eng.errors["gone/away"] = not_found_repo("gone/away")
    first = run(h, ["gone/away", *SEEDS])
    assert first.reports_run == 3 and first.not_found == ["gone/away"]
    row = failures(h)["gone/away"]
    assert row.code == "not_found" and 29 * 24 * HOUR < utc(row.retry_at) - now()

    eng.calls.clear()
    again = run(h, ["gone/away", *SEEDS])
    assert "gone/away" not in eng.calls and again.skipped_failed == 1
    assert again.not_found == ["gone/away"]  # still listed, every pass, until the list is fixed
    assert "1 not on GitHub" in again.summary()


def test_ten_failing_seeds_at_the_head_dont_keep_the_healthy_ones_waiting(h, pauses):
    eng = Engine(h)
    bad = [f"big/r{i}" for i in range(10)]
    for repo in bad:
        eng.errors[repo] = upstream()
    lines: list[str] = []
    result = run(h, [*bad, *SEEDS], parallel=1, say=lines.append)
    assert (result.reports_run, result.reports_failed, result.stopped) == (3, 10, None)
    # Five in a row from GitHub's side: a short pause each time, never the end.
    assert result.pauses == 2 and sum("pausing" in line for line in lines) == 2
    assert pauses.waits == [warm.BREAKER_PAUSE_S] * 2
    assert set(failures(h)) == set(bad)

    eng.calls.clear()
    again = run(h, [*bad, *SEEDS])
    assert eng.calls == [] and again.skipped_failed == 10 and again.pauses == 0


def test_a_slow_down_pauses_the_pass_then_goes_one_at_a_time(make_harness, pauses):
    h = make_harness(HOLT_BADGE_CONCURRENCY=3, HOLT_WARM_PARALLEL=3)
    eng = Engine(h)
    eng.errors["octo/r0"] = [slow_down()]  # once; then GitHub answers again
    seeds = [f"octo/r{i}" for i in range(6)]
    lines: list[str] = []
    result = run(h, seeds, wait_for_budget=True, say=lines.append)
    assert (result.reports_run, result.reports_failed, result.stopped) == (6, 0, None)
    assert result.pauses == 1 and any("slow down" in line for line in lines)
    assert failures(h) == {}  # not the repository's failure
    assert eng.calls.count("octo/r0") == 2  # asked again after the wait
    assert pauses.waits == [warm.LIMIT_WAIT_S]
    assert eng.peak_when_slow == 1


def test_without_wait_for_budget_a_slow_down_ends_the_pass_and_says_so(h):
    eng = Engine(h)
    eng.errors["octo/one"] = slow_down(retry_after=300)
    result = run(h, SEEDS, parallel=1)
    assert result.stopped == ("GitHub asked us to slow down (a rate limit, not a failing "
                              "repository); it takes requests again in about 5 minutes. "
                              "Run again then, or with --wait-for-budget to wait here")
    assert result.reports_failed == 0 and failures(h) == {}


def test_a_slow_down_that_never_ends_stops_the_pass_and_says_so(h, pauses):
    eng = Engine(h)
    eng.errors["octo/one"] = slow_down()
    result = run(h, SEEDS, parallel=1, wait_for_budget=True)
    assert result.pauses == warm.MAX_LIMITS_IN_A_ROW
    assert result.stopped.startswith(
        f"GitHub asked us to slow down {warm.MAX_LIMITS_IN_A_ROW + 1} times in a row")
    assert pauses.waits == [300, 600, 1200, 2400, 3600, 3600]  # longer each time, to an hour
    assert failures(h) == {}


def test_how_long_a_slow_down_waits():
    assert warm.limit_wait(300, 1) == 300  # what GitHub asked
    assert warm.limit_wait(300, 3) == 1200  # and longer each time it says so again
    assert warm.limit_wait(300, 9) == warm.LIMIT_WAIT_MAX_S


def test_progress_is_said_as_the_pass_goes(h, monkeypatch):
    monkeypatch.setattr(warm, "PROGRESS_EVERY", 2)
    eng = Engine(h)
    eng.errors["octo/one"] = upstream()
    lines: list[str] = []
    run(h, [*SEEDS, "octo/four"], parallel=1, say=lines.append)
    assert [line for line in lines if line.startswith("progress: ")] == [
        "progress: 2 of 4 seeds looked at: 1 reports run, 0 fresh, 1 failed; "
        "0 skipped as recently failed; 2 to go",
        "progress: 4 of 4 seeds looked at: 3 reports run, 0 fresh, 1 failed; "
        "0 skipped as recently failed; 0 to go"]


def test_a_dry_run_shows_the_same_queue_and_remembers_nothing(h):
    eng = Engine(h)
    eng.errors["octo/one"] = upstream()
    run(h, SEEDS)
    before = failures(h)["octo/one"].retry_at
    lines: list[str] = []
    result = run(h, SEEDS, dry_run=True, say=lines.append)
    assert "would analyse octo/one" not in lines and result.skipped_failed == 1
    assert failures(h)["octo/one"].retry_at == before


# --- the real pool and transport under the pass, GitHub faked --------------------------


class GitHubUnderThePass:
    """Each report reads its repository once through the server's own pool
    and transport, as the engine's first query does, and fails the way the
    engine's errors are translated."""

    def __init__(self, h, monkeypatch) -> None:
        monkeypatch.setattr(gql, "BACKOFF_BASE_S", 0)
        self.github = FakeGitHub()
        self.clock = Clock()
        http = httpx.Client(transport=httpx.MockTransport(self.github))
        h.svc.pool = github.TokenPool(["tok"], clock=self.clock)
        h.svc.provider_factory = lambda repo, as_of: h.svc.pool.transport(http)
        h.svc.analysis_fn = self.report

        async def remaining():
            return 5000

        h.svc.lookup.remaining = remaining

    def report(self, *, repo, mode, days, provider, **kw):
        owner, _, name = repo.partition("/")
        try:
            provider.query(github.LOOKUP, owner=owner, name=name)
        except Exception as exc:  # noqa: BLE001 -- as engine.analyze does
            raise engine.translate(exc, repo) from exc
        return canned_report(repo, mode, days)


def test_each_of_githubs_refusals_fails_only_its_own_seed(h, monkeypatch):
    world = GitHubUnderThePass(h, monkeypatch)
    bad = [f"big/r{i}" for i in range(10)]
    for repo in bad:
        world.github.answers[repo] = bad_gateway
    world.github.answers["closed/repo"] = forbidden
    world.github.answers["gone/away"] = missing
    result = run(h, [*bad, "closed/repo", "gone/away", *SEEDS], wait_for_budget=True)

    assert (result.reports_run, result.reports_failed, result.stopped) == (3, 12, None)
    assert h.svc.pool.held() is None  # no 502 or 403 was taken for a rate limit
    assert {f.repo: f.code for f in failures(h).values()} == {
        **dict.fromkeys(bad, "upstream"), "closed/repo": "upstream", "gone/away": "not_found"}
    assert result.not_found == ["gone/away"]
    # A warm report asks twice, not four times, for a repository GitHub can't answer for.
    assert world.github.asked.count("big/r0") == github.BACKGROUND_ATTEMPTS

    world.github.asked.clear()
    again = run(h, [*bad, "closed/repo", "gone/away", *SEEDS], wait_for_budget=True)
    assert again.skipped_failed == 12 and world.github.asked == []


def test_a_secondary_limit_mid_pass_is_waited_out_and_the_pass_finishes(h, monkeypatch,
                                                                         pauses):
    world = GitHubUnderThePass(h, monkeypatch)
    answers = [secondary_limit]
    world.github.answers["octo/two"] = lambda request: (
        answers.pop()(request) if answers else httpx.Response(200, json={"data": {
            "repository": {"nameWithOwner": "octo/two", "isPrivate": False}}}))
    lines: list[str] = []

    def say(line: str) -> None:
        lines.append(line)
        if "slow down" in line:
            world.clock.now += 301  # the five minutes GitHub asked for go by

    result = run(h, SEEDS, parallel=1, wait_for_budget=True, say=say)
    assert (result.reports_run, result.reports_failed, result.stopped) == (3, 0, None)
    assert result.pauses == 1 and failures(h) == {}
    assert any("waiting 5 minutes" in line for line in lines) and pauses.waits == [300]
