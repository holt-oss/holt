"""GitHub access for the server: the token pool and a cheap repo lookup.

GraphQL goes through the engine's own transport (`holt.evidence.github_graphql`),
so retries, rate-limit handling and the typed errors are the engine's; the
lookup tries one REST request first, and falls back to GraphQL. The
pool's transport (`PooledGraphQL`) also tells the pool what GitHub said about
each token, so a dead or used-up token is skipped until it can work again.

The pool is the GitHub App when one is set up (github_app.py), else the
tokens in `GITHUB_TOKENS`. Logs name them "the GitHub App" or by their place
in `GITHUB_TOKENS` ("token #2"), never by value.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from holt.about import help_links, language_shares, license_name, readme_excerpt, readme_line
from holt.evidence.errors import AuthError, Forbidden, GitHubError, RateLimited
from holt.evidence.github_graphql import (
    MAX_ATTEMPTS,
    MAX_RATE_LIMIT_WAIT_S,
    GitHubGraphQL,
)
from holt_server import github_app
from holt_server.errors import ApiError, github_rate_limited, upstream

log = logging.getLogger("holt_server.github")

LOOKUP = """
query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) { nameWithOwner isPrivate }
}
"""
# The same lookup over REST, which has a budget of its own: Holt reads GitHub
# almost entirely through GraphQL, so this takes a GraphQL point off every
# uncached report. GitHub redirects a renamed repository's old name here.
REPO_URL = "https://api.github.com/repos/{owner}/{name}"
REST_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
# Search by name (GitHub's REST search), and how many matches are kept.
SEARCH_URL = "https://api.github.com/search/repositories"
SEARCH_RESULTS = 5

RATE_LIMIT = "query { rateLimit { remaining resetAt } }"

# Where the details query looks for a README (its first sentence is kept, not
# the file), first found wins.
README_PATHS = ("README.md", "README.rst", "readme.md")
README_FIELDS = "".join(
    f'  readme{i}: object(expression: "HEAD:{path}") {{ ... on Blob {{ text }} }}\n'
    for i, path in enumerate(README_PATHS))
# Repositories per details query. GitHub charges about one point for a query
# of up to a hundred small lookups.
DETAILS_BATCH = 100
DETAILS_FIELDS = """
  nameWithOwner description stargazerCount pushedAt isArchived isFork isPrivate
  primaryLanguage { name }
  languages(first: 3, orderBy: {field: SIZE, direction: DESC}) { totalSize edges { size node { name } } }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  forkCount createdAt homepageUrl parent { nameWithOwner }
  licenseInfo { spdxId name } issues(states: OPEN) { totalCount }
  defaultBranchRef { name }
  pullRequests { totalCount } openPrs: pullRequests(states: OPEN) { totalCount }
  hasDiscussionsEnabled contributingGuidelines { url }
  latestRelease { tagName publishedAt url }
"""

# A second language is named beside the primary one when it is at least this
# share of the code. GitHub's primary language is only the largest by bytes:
# microsoft/TypeScript is mostly Go since its compiler port, and one tag of
# "Go" read as a mistake.
SECOND_LANGUAGE_SHARE = 0.10

LOOKUP_TIMEOUT_S = 15.0
# The people a report's About lists: GitHub's own contributors list (most
# commits first), bots left out. A few more are asked for than shown, so a bot
# or two near the top still leaves a full list.
TOP_CONTRIBUTORS = 10
TOP_CONTRIBUTORS_ASKED = 15
# Profile names looked up per GraphQL query (one `user` alias each).
NAMES_PER_QUERY = 100

# A token with fewer GraphQL points left than this is skipped until its reset:
# one analysis costs a couple of hundred.
LOW_POINTS = 250
# How long a token GitHub refused (401/403) is left out before it is tried again.
DEAD_SECONDS = 600.0
# How long a rate-limited token is left out when GitHub gave no reset time.
LIMITED_SECONDS = 300.0
# A 403 that isn't a rate limit is about what was asked for. This many in a
# row on one token, with no answer in between, and it is the token.
FORBIDDEN_IN_A_ROW = 3
# Tries per GraphQL query for background work (people's checks get the
# engine's MAX_ATTEMPTS). A repository GitHub times out on answers 502 after
# working on it for ten seconds, every try; a warm pass comes back to it later.
BACKGROUND_ATTEMPTS = 2

# Set by the jobs runner around a job's worker thread (asyncio.to_thread copies
# it in). When the event is set the job has timed out, and the next GitHub
# call in that thread gives up instead of spending more points.
job_stop: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "holt_job_stop", default=None)


# Set by the jobs runner for badge refreshes and warm reports: work nobody is
# waiting on. It asks GitHub less insistently, and hands a "slow down" back at
# once (so the warm pass slows down) instead of sitting it out in the job.
background: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "holt_background_job", default=False)


class JobStopped(Exception):
    """The job this work belongs to has timed out; stop doing it."""


def check_stop() -> None:
    stop = job_stop.get()
    if stop is not None and stop.is_set():
        raise JobStopped


class StaticToken:
    """One token from `GITHUB_TOKENS`."""

    renews = False

    def __init__(self, token: str, label: str) -> None:
        self._token = token
        self.label = label

    def token(self) -> str:
        return self._token

    def invalidate(self, token: str) -> None:
        pass


@dataclass
class TokenState:
    remaining: int | None = None
    reset_at: float | None = None  # epoch seconds, when `remaining` refills
    out_until: float = 0.0  # epoch seconds; refused or rate-limited until then
    reason: str = ""  # "refused", "limited" (hourly budget) or "secondary"
    forbidden: int = 0  # 403s in a row that weren't rate limits


@dataclass(frozen=True)
class Hold:
    """GitHub has rate-limited every token: nothing can be read for `seconds`.
    `secondary`: it asked us to slow down, with points to spare."""

    seconds: float
    secondary: bool


@dataclass(frozen=True)
class TokenView:
    remaining: int | None
    reset_at: float | None
    usable: bool


class TokenPool:
    """`GITHUB_TOKENS` (or the GitHub App), handed out round-robin, skipping the
    ones that can't work.

    A token is skipped while GitHub is refusing it (a bad or revoked token),
    while it is rate-limited, and while its points-left (read from every
    reply, see `PooledGraphQL`) are below `LOW_POINTS` and its reset time has
    not come. When every token is out, the caller gets a plain "try again"
    error instead of a GitHub failure halfway through a job.

    Only GitHub saying so takes a token out. A 502 or 504 is the failure of
    the one query (usually a repository too big to answer for), and so is a
    403 that isn't a rate limit. A rate limit holds the token for as long as
    GitHub asked, for every reader, the reports already in flight included:
    asking again during a secondary limit is what makes GitHub extend it.

    The GitHub App renews its own token: when GitHub refuses one, the app gets
    a new one on the next lease, and is only left out when GitHub won't issue
    one at all.
    """

    def __init__(self, tokens: list, clock=time.time, sleep=time.sleep) -> None:
        self._tokens = [t if hasattr(t, "renews") else StaticToken(t, f"token #{i + 1}")
                        for i, t in enumerate(tokens)]
        self._state = [TokenState() for _ in self._tokens]
        self._cursor = 0
        self._lock = threading.Lock()
        self._clock = clock
        self.sleep = sleep
        # GraphQL points this process has seen spent, for /metrics: each drop
        # in a token's points-left between two replies (other readers of the
        # same token included).
        self.points_used = 0

    def __bool__(self) -> bool:
        return bool(self._tokens)

    def __len__(self) -> int:
        return len(self._tokens)

    def label(self, index: int) -> str:
        return self._tokens[index].label

    def next(self) -> str:
        return self.lease()[1]

    def lease(self) -> tuple[int, str]:
        """The next usable token and its index."""
        if not self._tokens:
            raise ApiError(
                "internal",
                "This server isn't set up to read GitHub yet. Please try again later.",
            )
        with self._lock:
            now = self._clock()
            n = len(self._tokens)
            chosen = None
            for step in range(n):
                i = (self._cursor + step) % n
                if self._usable(i, now):
                    self._cursor = (i + 1) % n
                    chosen = i
                    break
            else:
                waits = [self._back_at(i) - now for i in range(n)
                         if self._state[i].reason != "refused"]
        if chosen is not None:
            # Outside the lock: the app may be fetching a new token.
            return chosen, self.token(chosen)
        if waits:
            wait = max(60, round(min(waits)))
            log.warning("every GitHub token is rate-limited or used up; next back in %ds", wait)
            raise github_rate_limited(wait)
        log.error("GitHub refused every token it was given (%s)",
                  ", ".join(t.label for t in self._tokens))
        raise upstream()

    def token(self, index: int) -> str:
        """Token `index`'s current value. For the GitHub App this may fetch a
        new one; if GitHub won't issue it, the app is left out like a refused
        or rate-limited token and the caller gets the matching `ApiError`."""
        try:
            return self._tokens[index].token()
        except AuthError as exc:
            self._bench(index, "refused", DEAD_SECONDS)
            log.error("GitHub won't issue a token to %s (%s); leaving it out for %d minutes",
                      self.label(index), exc.detail, DEAD_SECONDS // 60)
            raise upstream() from None
        except RateLimited as exc:
            self.note_rate_limited(index, exc.retry_after, exc.secondary)
            raise github_rate_limited(round(exc.retry_after or LIMITED_SECONDS)) from None
        except GitHubError as exc:
            log.warning("couldn't get a token for %s: %s", self.label(index),
                        getattr(exc, "detail", type(exc).__name__))
            raise upstream() from None

    def _usable(self, i: int, now: float) -> bool:
        st = self._state[i]
        if st.out_until > now:
            return False
        if st.remaining is not None and st.remaining < LOW_POINTS:
            if st.reset_at is not None and st.reset_at > now:
                return False
            st.remaining = None  # reset has passed; find out afresh
        st.reason = ""
        return True

    def _back_at(self, i: int) -> float:
        st = self._state[i]
        low = (st.reset_at or 0.0) if (st.remaining or 0) < LOW_POINTS else 0.0
        return max(st.out_until, low)

    def points_left(self) -> int | None:
        """GraphQL points left across the tokens usable now, as GitHub last
        reported them (no call); None while any usable token's count is unknown."""
        with self._lock:
            now = self._clock()
            usable = [self._state[i] for i in range(len(self._tokens)) if self._usable(i, now)]
            if any(st.remaining is None for st in usable):
                return None
            return sum(st.remaining or 0 for st in usable)

    def states(self) -> list[TokenView]:
        """Each token as GitHub last reported it, for /metrics (no call, and
        nothing changed). A count whose reset time has passed is out of date,
        so it reads as unknown."""
        with self._lock:
            now = self._clock()
            out = []
            for st in self._state:
                known = st.remaining is not None and not (
                    st.reset_at is not None and st.reset_at <= now)
                low = known and st.remaining < LOW_POINTS
                out.append(TokenView(remaining=st.remaining if known else None,
                                     reset_at=st.reset_at if known else None,
                                     usable=st.out_until <= now and not low))
            return out

    def limited_for(self, index: int) -> tuple[float, bool]:
        """(seconds token `index` is still held for a rate limit, whether it
        is a secondary one); 0 seconds when it isn't held."""
        with self._lock:
            st = self._state[index]
            left = st.out_until - self._clock()
            if left <= 0 or st.reason not in ("limited", "secondary"):
                return 0.0, False
            return left, st.reason == "secondary"

    def held(self) -> Hold | None:
        """The rate limit keeping every token out, or None while one can read."""
        waits = [self.limited_for(i) for i in range(len(self._tokens))]
        if not waits or any(seconds <= 0 for seconds, _ in waits):
            return None
        seconds, secondary = min(waits)
        return Hold(seconds, secondary)

    def transport(self, http: httpx.Client | None = None,
                  index: int | None = None) -> PooledGraphQL:
        """A GraphQL client on the next usable token (or on token `index`)."""
        if index is None:
            index, token = self.lease()
        else:
            token = self.token(index)
        return PooledGraphQL(self, index, token, client=http,
                             attempts=BACKGROUND_ATTEMPTS if background.get() else MAX_ATTEMPTS)

    # --- what GitHub said ----------------------------------------------------

    def note_points(self, index: int, remaining: Any, reset_at: Any = None) -> None:
        try:
            left = int(remaining)
        except (TypeError, ValueError):
            return
        reset = _epoch(reset_at)
        with self._lock:
            st = self._state[index]
            was_low = st.remaining is not None and st.remaining < LOW_POINTS
            if st.remaining is not None and left < st.remaining:
                self.points_used += st.remaining - left
            st.remaining, st.reset_at = left, reset
        if left < LOW_POINTS and not was_low:
            log.warning("%s is nearly used up (%d points left); skipping it "
                        "until it resets", self.label(index), left)

    def note_refused(self, index: int, detail: str, token: str | None = None) -> None:
        """GitHub refused token `index` (the value it refused, if known)."""
        source = self._tokens[index]
        if source.renews:
            if token is not None:
                source.invalidate(token)
            log.warning("GitHub refused %s's token (%s); getting a new one",
                        source.label, detail)
            return
        self._bench(index, "refused", DEAD_SECONDS)
        log.error("GitHub refused %s (%s); leaving it out for %d minutes",
                  source.label, detail, DEAD_SECONDS // 60)

    def note_rate_limited(self, index: int, retry_after: float | None,
                          secondary: bool = False) -> None:
        """GitHub rate-limited token `index`: nobody reads with it for as long
        as GitHub asked."""
        wait = retry_after if retry_after else LIMITED_SECONDS
        if self.limited_for(index)[0] >= wait - 1:
            return  # already held that long: another reader was told the same
        self._bench(index, "secondary" if secondary else "limited", wait)
        if secondary:
            log.warning("GitHub asked %s to slow down (too much at once, not the hourly "
                        "points); leaving it out for %ds", self.label(index), round(wait))
        else:
            log.warning("%s is rate-limited (hourly points used up); leaving it out for %ds",
                        self.label(index), round(wait))

    def note_forbidden(self, index: int, detail: str, token: str | None = None) -> None:
        """GitHub answered 403 to a query on token `index`, and not for a rate
        limit: the query's failure, until it is all the token ever gets."""
        with self._lock:
            self._state[index].forbidden += 1
            count = self._state[index].forbidden
        if count >= FORBIDDEN_IN_A_ROW:
            self.note_ok(index)
            self.note_refused(index, f"{count} refusals in a row: {detail}", token)

    def note_ok(self, index: int) -> None:
        self._state[index].forbidden = 0

    def _bench(self, index: int, reason: str, seconds: float) -> None:
        with self._lock:
            st = self._state[index]
            st.out_until = self._clock() + seconds
            st.reason = reason


def _epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


class PooledGraphQL(GitHubGraphQL):
    """The engine's GraphQL client, reporting each token's health to the pool.

    Also where a timed-out job's thread stops: every query first checks the
    job's stop flag.
    """

    def __init__(self, pool: TokenPool, index: int, token: str,
                 client: httpx.Client | None = None, attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(token=token, client=client, sleep=pool.sleep, attempts=attempts)
        self.pool = pool
        self.index = index

    def query(self, document: str, *, timeout: float | None = None,
              **variables: object) -> dict[str, Any]:
        check_stop()
        self._wait_out_the_limit()
        # The GitHub App's token is renewed while a long job runs.
        self.token = self.pool.token(self.index)
        try:
            return super().query(document, timeout=timeout, **variables)
        except AuthError as exc:
            self.pool.note_refused(self.index, str(exc)[:40], self.token)
            raise
        except Forbidden as exc:
            self.pool.note_forbidden(self.index, exc.detail[:60], self.token)
            raise
        except RateLimited as exc:
            self.pool.note_rate_limited(self.index, exc.retry_after, exc.secondary)
            raise

    def _wait_out_the_limit(self) -> None:
        """Send nothing while GitHub has this token rate-limited, whoever was
        told: a person's check sits a short wait out, anything else gets the
        wait back as `RateLimited`."""
        wait, secondary = self.pool.limited_for(self.index)
        if wait <= 0:
            return
        if background.get() or wait > MAX_RATE_LIMIT_WAIT_S:
            raise RateLimited(wait, secondary)
        self._sleep(wait)

    def _limited(self, wait: float, secondary: bool) -> None:
        self.pool.note_rate_limited(self.index, wait, secondary)
        if background.get():
            raise RateLimited(wait, secondary)

    def _data(self, body: dict[str, Any]) -> dict[str, Any]:
        limit = ((body or {}).get("data") or {}).get("rateLimit")
        if limit:
            self.pool.note_points(self.index, limit.get("remaining"), limit.get("resetAt"))
        data = super()._data(body)
        self.pool.note_ok(self.index)
        return data


# GitHub shows ":books:" in a description as an emoji; the API sends the code.
EMOJI_CODE = re.compile(r":[a-z0-9_+-]+:\s*")


def main_languages(node: dict[str, Any]) -> list[str]:
    """The primary language, then a second one if it's a real share of the code."""
    primary = (node.get("primaryLanguage") or {}).get("name")
    langs = node.get("languages") or {}
    total = langs.get("totalSize") or 0
    out = [primary] if primary else []
    for edge in langs.get("edges") or []:
        name = ((edge or {}).get("node") or {}).get("name")
        if not name or name in out:
            continue
        if total and (edge.get("size") or 0) / total >= SECOND_LANGUAGE_SHARE:
            out.append(name)
        break  # only the largest language after the primary one is considered
    return out[:2]


def _links(node: dict[str, Any]) -> list[dict[str, str]]:
    """Where a newcomer finds the rules and help: the contributing guide,
    GitHub Discussions, then the README's docs and chat links."""
    out = []
    contributing = (node.get("contributingGuidelines") or {}).get("url")
    if contributing:
        out.append({"kind": "contributing", "url": contributing})
    if node.get("hasDiscussionsEnabled") and node.get("nameWithOwner"):
        out.append({"kind": "discussions", "url": f"https://github.com/{node['nameWithOwner']}/discussions"})
    readme = next((text for i in range(len(README_PATHS))
                   if (text := (node.get(f"readme{i}") or {}).get("text"))), None)
    return out + help_links(readme, node.get("nameWithOwner"))


def _readme(node: dict[str, Any]) -> str | None:
    """The top of the repository's Markdown README (a .rst one is left out:
    the page renders Markdown only)."""
    for i, path in enumerate(README_PATHS):
        text = (node.get(f"readme{i}") or {}).get("text")
        if text and path.lower().endswith(".md"):
            return readme_excerpt(text)
    return None


def _release(node: dict[str, Any]) -> dict[str, Any] | None:
    r = node.get("latestRelease") or {}
    if not r.get("tagName") or not r.get("url"):
        return None
    return {"tag": r["tagName"], "published_at": r.get("publishedAt"), "url": r["url"]}


def _details(node: dict[str, Any]) -> dict[str, Any]:
    topics = [((t or {}).get("topic") or {}).get("name")
              for t in ((node.get("repositoryTopics") or {}).get("nodes") or [])]
    return {
        "repo": node.get("nameWithOwner"),
        "description": EMOJI_CODE.sub("", node.get("description") or "").strip() or None,
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "languages": main_languages(node),
        "stars": int(node.get("stargazerCount") or 0),
        "topics": [t for t in topics if t],
        "pushed_at": node.get("pushedAt"),
        "archived": bool(node.get("isArchived")),
        "fork": bool(node.get("isFork")),
        "forks": node.get("forkCount"),
        "open_issues": (node.get("issues") or {}).get("totalCount"),
        "pull_requests": (node.get("pullRequests") or {}).get("totalCount"),
        "open_pull_requests": (node.get("openPrs") or {}).get("totalCount"),
        # GraphQL has no contributor count; `details` fills it from REST.
        "contributors": None,
        "license": license_name(node.get("licenseInfo")),
        "homepage": (node.get("homepageUrl") or "").strip() or None,
        "language_shares": language_shares(node.get("languages")),
        "created_at": node.get("createdAt"),
        "default_branch": (node.get("defaultBranchRef") or {}).get("name"),
        "fork_of": (node.get("parent") or {}).get("nameWithOwner"),
        "readme_line": next((line for i in range(len(README_PATHS))
                             if (line := readme_line((node.get(f"readme{i}") or {}).get("text")))),
                            None),
        "readme": _readme(node),
        "links": _links(node),
        "latest_release": _release(node),
    }


def _rate_limited(response: Any) -> bool:
    """A REST answer that means "slow down". GitHub also answers 403 when a
    repository's history is too large to list its contributors (NixOS/nixpkgs)
    with quota to spare: that is about the one repository, and must not stop
    the rest of a batch."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    headers = getattr(response, "headers", None) or {}
    text = str(getattr(response, "text", "") or "").lower()
    return headers.get("x-ratelimit-remaining") == "0" or "rate limit" in text


@dataclass
class RepoInfo:
    name_with_owner: str


class GitHubLookup:
    """Checks a repository exists and returns GitHub's casing for its name.

    One REST request per call (no GraphQL points). Done before a job is
    queued, so a typo gets `not_found` at once instead of a failed job a minute
    later.
    """

    def __init__(self, pool: TokenPool, http: httpx.Client) -> None:
        self.pool = pool
        self.http = http
        # GraphQL points the `details` queries have cost, as GitHub reported.
        self.points_used = 0

    async def repo(self, repo: str) -> RepoInfo:
        return await asyncio.to_thread(self._repo, repo)

    def _repo(self, repo: str) -> RepoInfo:
        owner, _, name = repo.partition("/")
        found = self._repo_rest(owner, name)
        if found is None:
            found = self._repo_graphql(repo, owner, name)
        if not found or found.get("isPrivate"):
            from holt_server.errors import not_found_repo

            raise not_found_repo(repo)
        return RepoInfo(name_with_owner=found["nameWithOwner"])

    def _repo_rest(self, owner: str, name: str) -> dict[str, Any] | None:
        """`{"nameWithOwner", "isPrivate"}`, `{}` when GitHub says there's no
        such repository, or None when REST didn't answer (rate-limited, down,
        or the token refused): then the GraphQL lookup decides."""
        index, token = self.pool.lease()
        try:
            response = self.http.get(
                REPO_URL.format(owner=quote(owner, safe=""), name=quote(name, safe="")),
                headers={**REST_HEADERS, "Authorization": f"Bearer {token}"},
                timeout=LOOKUP_TIMEOUT_S, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("REST repository lookup failed (%s); asking GraphQL", type(exc).__name__)
            return None
        if response.status_code == 404:
            return {}
        if response.status_code == 401:
            self.pool.note_refused(index, "401 Unauthorized", token)
        if response.status_code != 200:
            log.warning("REST repository lookup answered %d; asking GraphQL",
                        response.status_code)
            return None
        try:
            body = response.json()
            return {"nameWithOwner": body["full_name"], "isPrivate": bool(body.get("private"))}
        except (ValueError, KeyError, TypeError):
            log.warning("REST repository lookup sent an unexpected answer; asking GraphQL")
            return None

    def _repo_graphql(self, repo: str, owner: str, name: str) -> dict[str, Any] | None:
        from holt_server.engine import translate

        try:
            data = self.pool.transport(self.http).query(
                LOOKUP, timeout=LOOKUP_TIMEOUT_S, owner=owner, name=name)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise translate(exc, repo) from exc
        return data.get("repository")

    async def details(self, repos: list[str]) -> dict[str, dict[str, Any] | None]:
        """Description, language, stars, topics, last push and the rest of the
        report's "About" (repo_meta) for up to
        `DETAILS_BATCH` repositories, in one GraphQL query. Keyed by the
        requested `owner/repo`; None for one that is missing or private."""
        return await asyncio.to_thread(self._details_with_people, repos)

    def _details_with_people(self, repos: list[str]) -> dict[str, dict[str, Any] | None]:
        out = self._details(repos)
        for repo, d in out.items():
            if d is None:
                continue
            try:
                d["contributors"] = self._contributors(repo)
                d["top_contributors"] = self._top_contributors(repo)
            except RateLimited:
                break  # the rest are read tomorrow; counts are a nicety
        self._name_people(out)
        return out

    def _contributors(self, repo: str) -> int | None:
        """People who have committed to the repository, or None when GitHub
        wouldn't say. One REST request asking for a page of one: the number of
        pages in the `Link` header is the count. Anonymous committers count."""
        owner, _, name = repo.partition("/")
        index, token = self.pool.lease()
        try:
            response = self.http.get(
                REPO_URL.format(owner=quote(owner, safe=""), name=quote(name, safe="")) + "/contributors",
                params={"per_page": 1, "anon": 1},
                headers={**REST_HEADERS, "Authorization": f"Bearer {token}"},
                timeout=LOOKUP_TIMEOUT_S, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("REST contributor count failed (%s)", type(exc).__name__)
            return None
        if response.status_code == 401:
            self.pool.note_refused(index, "401 Unauthorized", token)
        if response.status_code == 204:
            return 0  # an empty repository
        if _rate_limited(response):
            raise RateLimited(retry_after=None)
        if response.status_code != 200:
            return None
        last = (response.links.get("last") or {}).get("url", "")
        page = re.search(r"[?&]page=(\d+)", last)
        if page:
            return int(page.group(1))
        try:
            return len(response.json())
        except (ValueError, TypeError):
            return None

    def _top_contributors(self, repo: str) -> list[dict[str, Any]] | None:
        """The repository's most active committers, in GitHub's order (most
        commits first), bots left out: `{"login", "url", "avatar_url",
        "contributions"}` each, the name added by `_name_people`. None when
        GitHub wouldn't say, so the stored list is kept."""
        owner, _, name = repo.partition("/")
        index, token = self.pool.lease()
        try:
            response = self.http.get(
                REPO_URL.format(owner=quote(owner, safe=""), name=quote(name, safe="")) + "/contributors",
                params={"per_page": TOP_CONTRIBUTORS_ASKED},
                headers={**REST_HEADERS, "Authorization": f"Bearer {token}"},
                timeout=LOOKUP_TIMEOUT_S, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning("REST top contributors failed (%s)", type(exc).__name__)
            return None
        if response.status_code == 401:
            self.pool.note_refused(index, "401 Unauthorized", token)
        if response.status_code == 204:
            return []  # an empty repository
        if _rate_limited(response):
            raise RateLimited(retry_after=None)
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except (ValueError, TypeError):
            return None
        people = []
        for p in body if isinstance(body, list) else []:
            login = (p or {}).get("login") if isinstance(p, dict) else None
            if not login or p.get("type") != "User" or login.lower().endswith("[bot]"):
                continue
            people.append({"login": login, "url": p.get("html_url"), "avatar_url": p.get("avatar_url"),
                           "contributions": p.get("contributions")})
        return people[:TOP_CONTRIBUTORS]

    def _name_people(self, out: dict[str, dict[str, Any] | None]) -> None:
        """Each listed contributor's GitHub profile name, `NAMES_PER_QUERY`
        people per GraphQL query for the whole batch. A name GitHub doesn't
        have, or a query that fails, leaves it None (the page shows the
        login): names are a nicety and never hold up the details."""
        people = [p for d in out.values() if d for p in d.get("top_contributors") or []]
        logins = sorted({p["login"] for p in people})
        names: dict[str, str | None] = {}
        for start in range(0, len(logins), NAMES_PER_QUERY):
            chunk = logins[start:start + NAMES_PER_QUERY]
            params = ", ".join(f"$l{i}:String!" for i in range(len(chunk)))
            parts = "\n  ".join(f"u{i}: user(login:$l{i}) {{ name }}" for i in range(len(chunk)))
            document = f"query({params}) {{\n  {parts}\n  rateLimit {{ cost remaining resetAt }}\n}}\n"
            transport = self.pool.transport(self.http)
            try:
                data = transport.query(document, timeout=LOOKUP_TIMEOUT_S,
                                       **{f"l{i}": login for i, login in enumerate(chunk)})
            except Exception as exc:  # noqa: BLE001 - names are a nicety
                log.warning("contributor names query failed (%s)", type(exc).__name__)
                continue
            finally:
                self.points_used += getattr(transport, "points_used", 0) or 0
            for i, login in enumerate(chunk):
                node = data.get(f"u{i}")
                names[login] = node.get("name") if isinstance(node, dict) else None
        for p in people:
            p["name"] = (str(names.get(p["login"]) or "").strip()[:100]) or None

    async def search(self, name: str) -> list[dict[str, Any]]:
        """Public repositories whose name matches `name`, most starred first, as
        [{"repo", "description", "stars"}]: how a bare "excalidraw" becomes
        excalidraw/excalidraw. Forks are left out, so a famous project isn't
        buried under copies of itself. One REST search request (a budget of its
        own, apart from the GraphQL points reports use)."""
        return await asyncio.to_thread(self._search, name)

    def _search(self, name: str) -> list[dict[str, Any]]:
        index, token = self.pool.lease()
        try:
            response = self.http.get(
                SEARCH_URL,
                params={"q": f"{name} in:name fork:false", "sort": "stars", "order": "desc",
                        "per_page": SEARCH_RESULTS},
                headers={**REST_HEADERS, "Authorization": f"Bearer {token}"},
                timeout=LOOKUP_TIMEOUT_S)
        except httpx.HTTPError as exc:
            log.warning("REST repository search failed (%s)", type(exc).__name__)
            raise upstream() from exc
        if response.status_code == 401:
            self.pool.note_refused(index, "401 Unauthorized", token)
            raise upstream()
        if response.status_code in (403, 429):
            raise RateLimited(retry_after=None)
        if response.status_code == 422:
            return []  # GitHub won't search for that text
        if response.status_code != 200:
            raise upstream()
        try:
            items = response.json().get("items") or []
        except (ValueError, AttributeError):
            raise upstream() from None
        return [{"repo": it["full_name"], "description": (it.get("description") or "").strip() or None,
                 "stars": int(it.get("stargazers_count") or 0)}
                for it in items if isinstance(it, dict) and it.get("full_name") and not it.get("private")]

    def _details(self, repos: list[str]) -> dict[str, dict[str, Any] | None]:
        from holt.evidence.errors import RepoNotFound

        if len(repos) > DETAILS_BATCH:
            raise ValueError(f"at most {DETAILS_BATCH} repositories per query")
        if not repos:
            return {}
        params, parts, variables = [], [], {}
        for i, repo in enumerate(repos):
            owner, _, name = repo.partition("/")
            params.append(f"$o{i}:String!, $n{i}:String!")
            parts.append(f"r{i}: repository(owner:$o{i}, name:$n{i}) {{ ...details }}")
            variables[f"o{i}"], variables[f"n{i}"] = owner, name
        document = (f"query({', '.join(params)}) {{\n  " + "\n  ".join(parts)
                    + "\n  rateLimit { cost remaining resetAt }\n}\n"
                    + f"fragment details on Repository {{{DETAILS_FIELDS}{README_FIELDS}}}")
        from holt_server.engine import translate

        transport = self.pool.transport(self.http)
        try:
            data = transport.query(document, timeout=LOOKUP_TIMEOUT_S * 2, **variables)
        except RepoNotFound:
            data = {}  # every one of them is gone
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise translate(exc, repos[0]) from exc
        finally:
            self.points_used += getattr(transport, "points_used", 0) or 0
        out: dict[str, dict[str, Any] | None] = {}
        for i, repo in enumerate(repos):
            node = data.get(f"r{i}")
            out[repo] = None if not node or node.get("isPrivate") else _details(node)
        return out

    async def remaining(self) -> int:
        """The fewest GraphQL points left on any working token (checking is free).

        A token GitHub refuses is left out (and the pool skips it); if none
        answer, 0. A token held by a rate limit counts as 0 and is not asked:
        `pool.held()` says how long for, and which kind.
        """
        return await asyncio.to_thread(self._remaining)

    def _remaining(self) -> int:
        counts = []
        for index in range(len(self.pool)):
            if self.pool.limited_for(index)[0] > 0:
                counts.append(0)  # held by a rate limit: don't ask during it
                continue
            try:
                data = self.pool.transport(self.http, index=index).query(
                    RATE_LIMIT, timeout=LOOKUP_TIMEOUT_S)
            except AuthError:
                continue
            except ApiError as exc:  # the app couldn't get a token
                if exc.code == "rate_limited":
                    counts.append(0)
                continue
            except RateLimited:
                counts.append(0)
                continue
            counts.append(int((data.get("rateLimit") or {}).get("remaining") or 0))
        return min(counts) if counts else 0


def build_pool(settings, http: httpx.Client) -> TokenPool:
    """The GitHub App when it is set up, else `GITHUB_TOKENS`.

    A half-configured app raises `github_app.AppConfigError` (the server
    doesn't start) rather than quietly reading with a person's tokens.
    """
    app = github_app.from_settings(settings, http)
    if app is None:
        return TokenPool(settings.token_list)
    log.info("reading GitHub as %s (app %s, installation %s)",
             app.label, app.app_id, app.installation_id)
    if settings.token_list:
        log.info("GITHUB_TOKENS is set but not used while the GitHub App is set up")
    return TokenPool([app])
