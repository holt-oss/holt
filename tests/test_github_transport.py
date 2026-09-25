"""The GitHub transport under failure: retries, rate limits, typed errors.

Every response here comes from `httpx.MockTransport`; nothing reaches GitHub.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from holt.evidence import github_graphql as gql
from holt.evidence.errors import AuthError, RateLimited, RepoNotFound, UpstreamError


def transport(responses, sleeps=None):
    """A GitHubGraphQL whose HTTP answers come from `responses`, in order."""
    queue = list(responses)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = httpx.Client(transport=httpx.MockTransport(handler))
    t = gql.GitHubGraphQL(
        token="t", client=client,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )
    return t, seen


def ok(data, errors=None):
    body = {"data": data}
    if errors:
        body["errors"] = errors
    return httpx.Response(200, json=body)


def test_5xx_is_retried_with_backoff_then_succeeds():
    sleeps: list[float] = []
    t, seen = transport(
        [httpx.Response(502), httpx.Response(503), ok({"x": 1})], sleeps
    )
    assert t.query("q") == {"x": 1}
    assert len(seen) == 3
    assert sleeps == [gql.BACKOFF_BASE_S, gql.BACKOFF_BASE_S * 2]


def test_timeouts_are_retried_and_then_raise_upstream():
    t, seen = transport([httpx.ReadTimeout("slow")] * gql.MAX_ATTEMPTS)
    with pytest.raises(UpstreamError) as exc:
        t.query("q")
    assert len(seen) == gql.MAX_ATTEMPTS
    assert "GitHub" in str(exc.value)


def test_persistent_5xx_raises_upstream():
    t, _ = transport([httpx.Response(500)] * gql.MAX_ATTEMPTS)
    with pytest.raises(UpstreamError):
        t.query("q")


def test_short_secondary_rate_limit_is_waited_out():
    sleeps: list[float] = []
    t, seen = transport(
        [httpx.Response(403, headers={"Retry-After": "7"}, text="secondary rate limit"),
         ok({"x": 1})],
        sleeps,
    )
    assert t.query("q") == {"x": 1}
    assert sleeps == [7.0]


def test_long_rate_limit_is_handed_back_with_retry_after():
    t, seen = transport([httpx.Response(429, headers={"Retry-After": "900"})])
    with pytest.raises(RateLimited) as exc:
        t.query("q")
    assert exc.value.retry_after == 900.0
    assert len(seen) == 1


def test_primary_rate_limit_reads_the_reset_header(monkeypatch):
    monkeypatch.setattr(gql.time, "time", lambda: 1000.0)
    t, _ = transport([httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1600"})])
    with pytest.raises(RateLimited) as exc:
        t.query("q")
    assert exc.value.retry_after == 600.0


def test_graphql_rate_limited_error_type_is_typed():
    t, _ = transport([ok(None, [{"type": "RATE_LIMITED", "message": "slow down"}])])
    with pytest.raises(RateLimited):
        t.query("q")


@pytest.mark.parametrize("status", [401, 403])
def test_bad_token_is_an_auth_error(status):
    t, _ = transport([httpx.Response(status, text="Bad credentials")])
    with pytest.raises(AuthError):
        t.query("q")


def test_missing_token_is_an_auth_error(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(AuthError):
        gql.GitHubGraphQL()


def test_typed_errors_are_still_runtime_errors():
    # The CLI catches RuntimeError and prints the message; that must keep working.
    for cls in (AuthError, RateLimited, RepoNotFound, UpstreamError):
        assert issubclass(cls, RuntimeError)


def test_missing_repository_is_repo_not_found():
    t, _ = transport([ok(
        {"rateLimit": {"remaining": 1, "resetAt": "x"}, "repository": None},
        [{"type": "NOT_FOUND", "message": "Could not resolve to a Repository with the name 'a/nope'."}],
    )])
    with pytest.raises(RepoNotFound) as exc:
        t.repo_meta("a", "nope", datetime.now(UTC))
    assert "a/nope" in str(exc.value)


def test_errors_alongside_data_keep_the_data():
    data = {"search": {"issueCount": 2, "pageInfo": {"hasNextPage": False, "endCursor": None},
                       "nodes": [{"number": 1}, None]}}
    t, _ = transport([ok(data, [{"type": "INTERNAL", "message": "one node failed"}])])
    assert t.query("q") == data
    assert t.partial_errors and t.partial_errors[0]["message"] == "one node failed"


def test_pull_request_pages_get_the_heavy_timeout():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions.get("timeout")
        return ok({"search": {"issueCount": 0, "pageInfo": {"hasNextPage": False,
                                                            "endCursor": None}, "nodes": []}})

    t = gql.GitHubGraphQL(token="t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    list(t.search_pull_requests("repo:a/b is:pr"))
    assert captured["timeout"]["read"] == gql.HEAVY_TIMEOUT_S


def test_docs_are_found_under_dot_github_and_as_rst():
    def handler(request: httpx.Request) -> httpx.Response:
        doc = json.loads(request.content)["query"]
        aliases = {}
        for line in doc.splitlines():
            line = line.strip()
            if ": object(expression:" in line:
                alias = line.split(":", 1)[0]
                path = line.split('expression:"', 1)[1].split('"', 1)[0].split(":", 1)[1]
                aliases[alias] = path
        repo = {}
        for alias, path in aliases.items():
            if path in ("README.rst", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"):
                repo[alias] = {"text": f"text of {path}"}
            else:
                repo[alias] = None
        return ok({"rateLimit": {"remaining": 1, "resetAt": "x"}, "repository": repo})

    t = gql.GitHubGraphQL(token="t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    docs = t.docs_at("a", "b", "abc123")
    assert docs["readme"] == {"text": "text of README.rst", "path": "README.rst"}
    # .github/ is listed before docs/, as GitHub itself prefers it.
    assert docs["contributing"]["path"] == ".github/CONTRIBUTING.md"

    records = list(gql.project_docs("a/b", docs, {"oid": "abc123",
                                                  "committedDate": "2026-01-01T00:00:00Z"}))
    by_id = {r.evidence_id: r for r in records}
    assert by_id["repo:a/b:readme"].url.endswith("/blob/abc123/README.rst")
    assert by_id["repo:a/b:contributing"].url.endswith("/blob/abc123/.github/CONTRIBUTING.md")


def test_docs_query_covers_case_variants_and_locations():
    _, aliases = gql.docs_query("abc")
    paths = {p for _, p in aliases.values()}
    for expected in ("README.md", "README.rst", "readme.md", ".github/CONTRIBUTING.md",
                     "docs/CONTRIBUTING.md", "contributing.md", "CONTRIBUTING.rst"):
        assert expected in paths


def test_issue_search_asks_for_open_issues_in_a_fixed_order():
    q = gql.issue_query("a/b", datetime(2026, 9, 1, tzinfo=UTC))
    assert "is:open" in q and "is:issue" in q
    assert "sort:created-desc" in q
    assert "created:<2026-09-01" in q


def test_issue_provider_uses_the_open_sorted_query():
    class Fake:
        def __init__(self):
            self.queries = []

        def search_issues(self, q, max_pages):
            self.queries.append(q)
            return iter(())

    from holt.types import Window

    fake = Fake()
    provider = gql.LiveGitHubIssueProvider(Window.PRE_T, transport=fake)
    provider.fetch("a/b")
    assert "is:open" in fake.queries[0] and "sort:" in fake.queries[0]
