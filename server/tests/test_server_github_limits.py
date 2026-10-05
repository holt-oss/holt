"""What the token pool makes of GitHub's refusals: a repository GitHub can't
answer for (502/504), the hourly budget running out, "slow down" (a secondary
limit), a plain 403, and a repository that isn't there. Every response comes
from `httpx.MockTransport`; nothing reaches GitHub."""

from __future__ import annotations

import contextvars
import json

import httpx
import pytest
from holt_server import github
from holt_server.errors import ApiError
from holt_server.github import GitHubLookup, TokenPool

from holt.evidence import github_graphql as gql
from holt.evidence.errors import Forbidden, RateLimited, RepoNotFound, UpstreamError

SECONDARY = {"message": "You have exceeded a secondary rate limit. Please wait a few "
                        "minutes before you try again."}


def bad_gateway(request):
    return httpx.Response(502)


def secondary_limit(request):
    return httpx.Response(403, headers={"Retry-After": "300", "x-ratelimit-remaining": "4042"},
                          json=SECONDARY)


def forbidden(request):
    return httpx.Response(403, headers={"x-ratelimit-remaining": "4042"},
                          json={"message": "Resource not accessible by integration"})


def missing(request):
    return httpx.Response(200, json={
        "data": {"repository": None},
        "errors": [{"type": "NOT_FOUND", "path": ["repository"],
                    "message": "Could not resolve to a Repository with the name 'gone/away'."}]})


class FakeGitHub:
    """GraphQL only. `answers["owner/name"]` answers that repository's
    queries; any other gets its name back, and the points left."""

    def __init__(self) -> None:
        self.answers: dict[str, object] = {}
        self.asked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        v = json.loads(request.content).get("variables") or {}
        repo = f"{v['owner']}/{v['name']}" if "owner" in v else "rateLimit"
        self.asked.append(repo)
        if repo in self.answers:
            return self.answers[repo](request)
        return httpx.Response(200, json={"data": {
            "repository": {"nameWithOwner": repo, "isPrivate": False},
            "rateLimit": {"remaining": 4042, "resetAt": "2099-01-01T00:00:00Z"}}})


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class World:
    def __init__(self, tokens=("tok",)) -> None:
        self.github = FakeGitHub()
        self.http = httpx.Client(transport=httpx.MockTransport(self.github))
        self.clock = Clock()
        self.pool = TokenPool(list(tokens), clock=self.clock)

    def ask(self, repo: str, transport=None):
        owner, _, name = repo.partition("/")
        return (transport or self.pool.transport(self.http)).query(
            github.LOOKUP, owner=owner, name=name)


@pytest.fixture
def w(monkeypatch) -> World:
    monkeypatch.setattr(gql, "BACKOFF_BASE_S", 0)
    return World()


def test_a_502_is_that_repositorys_failure_and_the_token_stays_in(w):
    w.github.answers["big/repo"] = bad_gateway
    with pytest.raises(UpstreamError):
        w.ask("big/repo")
    assert w.pool.held() is None and w.pool.states()[0].usable
    assert w.ask("octo/one")["repository"]["nameWithOwner"] == "octo/one"


def test_background_work_asks_twice_and_people_four_times(w):
    w.github.answers["big/repo"] = bad_gateway
    with pytest.raises(UpstreamError):
        w.ask("big/repo")
    assert w.github.asked.count("big/repo") == gql.MAX_ATTEMPTS

    def in_the_background():
        github.background.set(True)
        with pytest.raises(UpstreamError):
            w.ask("big/repo")

    w.github.asked.clear()
    contextvars.copy_context().run(in_the_background)
    assert w.github.asked.count("big/repo") == github.BACKGROUND_ATTEMPTS == 2


def test_a_secondary_limit_holds_every_reader_until_github_says(w, caplog):
    in_flight = w.pool.transport(w.http)  # a report already reading
    w.github.answers["octo/one"] = secondary_limit
    with caplog.at_level("WARNING", logger="holt_server.github"), pytest.raises(RateLimited) as exc:
        w.ask("octo/one")
    assert (exc.value.retry_after, exc.value.secondary) == (300.0, True)
    assert "not the hourly points" in caplog.text and "300s" in caplog.text
    hold = w.pool.held()
    assert (hold.seconds, hold.secondary) == (300.0, True)

    # Nothing more is sent while it lasts: not by a new reader, not by the
    # report in flight, not by a check of the points left.
    w.github.asked.clear()
    with pytest.raises(ApiError) as refused:
        w.pool.transport(w.http)
    assert (refused.value.code, refused.value.retry_after) == ("rate_limited", 300)
    with pytest.raises(RateLimited) as held:
        w.ask("octo/two", in_flight)
    assert (held.value.retry_after, held.value.secondary) == (300.0, True)
    assert GitHubLookup(w.pool, w.http)._remaining() == 0
    assert w.github.asked == []

    w.clock.now += 301
    assert w.pool.held() is None
    assert w.ask("octo/two", in_flight)["repository"]["nameWithOwner"] == "octo/two"
    assert GitHubLookup(w.pool, w.http)._remaining() == 4042


def test_a_short_limit_is_sat_out_by_a_persons_check_and_handed_back_by_background_work(w):
    waits: list[float] = []
    w.pool.sleep = waits.append
    answers = [httpx.Response(403, headers={"Retry-After": "7"}, json=SECONDARY)]
    w.github.answers["octo/one"] = lambda request: answers.pop() if answers else httpx.Response(
        200, json={"data": {"repository": {"nameWithOwner": "octo/one", "isPrivate": False}}})
    assert w.ask("octo/one")["repository"]["nameWithOwner"] == "octo/one"
    assert waits == [7.0]

    def in_the_background():
        github.background.set(True)
        w.github.answers["octo/two"] = lambda request: httpx.Response(
            403, headers={"Retry-After": "7"}, json=SECONDARY)
        with pytest.raises(RateLimited) as exc:
            w.ask("octo/two")
        assert exc.value.secondary

    w.clock.now += 60
    contextvars.copy_context().run(in_the_background)
    assert waits == [7.0]  # the warm pass is told, and slows down


def test_the_hourly_budget_running_out_waits_for_its_reset(w, monkeypatch, caplog):
    monkeypatch.setattr(gql.time, "time", w.clock)
    w.github.answers["octo/one"] = lambda request: httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(w.clock.now + 600)},
        json={"message": "API rate limit exceeded for installation."})
    with caplog.at_level("WARNING", logger="holt_server.github"), pytest.raises(RateLimited) as exc:
        w.ask("octo/one")
    assert (exc.value.retry_after, exc.value.secondary) == (600.0, False)
    assert "hourly points" in caplog.text and "not the hourly points" not in caplog.text
    hold = w.pool.held()
    assert (hold.seconds, hold.secondary) == (600.0, False)


def test_a_403_that_is_not_a_limit_fails_the_request_and_keeps_the_token(w):
    w.github.answers["closed/repo"] = forbidden
    with pytest.raises(Forbidden):
        w.ask("closed/repo")
    assert w.pool.held() is None and w.pool.states()[0].usable
    assert w.ask("octo/one")["repository"]["nameWithOwner"] == "octo/one"


def test_a_token_github_refuses_every_time_is_left_out():
    # A token that can read nothing answers 403 to everything: after a few in
    # a row with no answer in between, it is the token.
    world = World(tokens=("dead", "good"))
    world.github.answers["closed/a"] = world.github.answers["closed/b"] = forbidden
    world.github.answers["closed/c"] = forbidden
    dead = world.pool.transport(world.http, index=0)
    for repo in ("closed/a", "closed/b", "closed/c"):
        with pytest.raises(Forbidden):
            world.ask(repo, dead)
    assert [s.usable for s in world.pool.states()] == [False, True]
    assert {world.pool.next() for _ in range(3)} == {"good"}


def test_a_missing_repository_is_not_found_and_the_token_stays_in(w):
    w.github.answers["gone/away"] = missing
    with pytest.raises(RepoNotFound):
        w.ask("gone/away")
    assert w.pool.held() is None and w.pool.states()[0].usable
