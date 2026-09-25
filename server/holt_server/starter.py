"""Adapter over `holt.starter` (starter issues and repo finding).

`holt.starter` is being written separately. It is imported lazily, on every
call, so the endpoints answer 501 until it lands and start working the moment
it does, with no server change. The coded-against signatures are:

    starter_issues(repo, token, limit, as_of=None) -> list[StarterIssue-like]
    find(languages, topics, hacktoberfest, token, limit, screen=None, progress=None)
        -> list[result-like]

Results may be dicts, dataclasses or plain objects; they are normalised to the
StarterIssue and find-result shapes in API.md here.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from datetime import date, datetime
from enum import Enum
from typing import Any

from holt_server.errors import ApiError
from holt_server.report import iso

NOT_READY = (
    "Finding starter issues isn't available yet. It's coming soon; for now, "
    "run a report on a repository you have in mind."
)


def module():
    try:
        return importlib.import_module("holt.starter")
    except ImportError:
        return None


def function(name: str):
    mod = module()
    fn = getattr(mod, name, None) if mod is not None else None
    if fn is None:
        raise ApiError("not_implemented", NOT_READY, status=501)
    return fn


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


def issue(obj: Any, repo: str | None = None) -> dict[str, Any]:
    number = _get(obj, "number")
    url = _get(obj, "url")
    if not url and repo and number is not None:
        url = f"https://github.com/{repo}/issues/{number}"
    comments = _get(obj, "comments", 0)
    if isinstance(comments, (list, tuple)):
        comments = len(comments)
    return {
        "number": number,
        "title": _get(obj, "title", ""),
        "url": url,
        "labels": [_plain(x) for x in (_get(obj, "labels") or [])],
        "created_at": _plain(_get(obj, "created_at")),
        "comments": int(comments or 0),
        "why": [str(x) for x in (_get(obj, "why") or [])],
    }


STAT_KEYS = ("outsider_attempts", "outsider_merged", "distinct_outsiders",
             "first_time_merged_authors", "no_reply", "median_first_response_hours",
             "bot_share")


def find_result(obj: Any) -> dict[str, Any]:
    from holt.agent.signals import Signals
    from holt.agent.verdict import headline as headline_for
    from holt_server.report import stats as signal_stats

    repo = _get(obj, "repo") or _get(obj, "name_with_owner") or ""
    verdict = _plain(_get(obj, "verdict", "viable"))
    raw_stats = _get(obj, "stats") or _get(obj, "signals") or {}
    if isinstance(raw_stats, Signals):
        stats = signal_stats(raw_stats)
    else:
        stats = {k: v for k, v in _plain(raw_stats).items() if k in STAT_KEYS}
    try:
        headline = headline_for(verdict)
    except ValueError:
        headline = _get(obj, "headline") or ""
    stars = _get(obj, "stars", _get(obj, "stargazer_count"))
    language = _get(obj, "language", _get(obj, "primary_language"))
    if isinstance(language, dict):  # GraphQL's `primaryLanguage { name }`
        language = language.get("name")
    return {
        "repo": repo,
        "headline": headline,
        "verdict": verdict,
        # Optional; null when the finder did not supply them.
        "description": _get(obj, "description") or None,
        "language": language or None,
        "stars": int(stars) if isinstance(stars, (int, float)) else None,
        "stats": stats,
        "issues": [issue(i, repo) for i in (_get(obj, "issues") or [])],
    }


def run_starter_issues(repo: str, token: str, limit: int) -> list[dict[str, Any]]:
    fn = function("starter_issues")
    return [issue(i, repo) for i in (fn(repo, token, limit) or [])][:limit]


def cached_screen(cached, token: str, days: int, http=None):
    """A `find` screen that answers from a fresh cached rules report when there
    is one (no GitHub call) and crawls at screening depth otherwise."""
    from datetime import UTC, datetime

    from holt.agent.landing import Area
    from holt.starter import GitHub, RepoScreen, rules_screen

    fallback = rules_screen(GitHub(token=token, client=http), datetime.now(UTC), days)

    def screen(repo: str):
        report = cached(repo) if cached else None
        if not report:
            return fallback(repo)
        return RepoScreen(
            verdict=report["verdict"],
            stats={k: v for k, v in (report.get("stats") or {}).items() if k in STAT_KEYS},
            landing=[Area(a["path"], a["merged"], a["attempted"])
                     for a in report.get("landing") or []],
        )

    return screen


def run_find(*, languages: list[str], topics: list[str], hacktoberfest: bool, days: int,
             limit: int, token: str, emit, cached=None, http=None) -> dict[str, Any]:
    """`holt.starter.find`, normalised. `cached(repo)` returns a fresh cached
    rules report (dict) or None; when given, screening uses it first."""
    fn = function("find")
    kwargs: dict[str, Any] = {}
    params = inspect.signature(fn).parameters
    if cached is not None and "screen" in params:
        try:
            kwargs["screen"] = cached_screen(cached, token, days, http)
        except (ImportError, AttributeError):
            pass  # an engine without the screen helpers: find screens itself
    if "progress" in params:
        def progress(*args: Any, **kw: Any) -> None:
            values = list(args) + list(kw.values())
            stage = next((v for v in values if isinstance(v, str)), None)
            frac = next((float(v) for v in values if isinstance(v, (int, float))
                         and not isinstance(v, bool) and 0 <= float(v) <= 1), None)
            if stage or frac is not None:
                emit(stage or "Looking for repositories", min(frac or 0.0, 0.99))
        kwargs["progress"] = progress
    for name in ("days", "contributor_days"):
        if name in params:
            kwargs[name] = days
    emit("Looking for repositories", 0.05)
    raw = fn(languages, topics, hacktoberfest, token, limit, **kwargs) or []
    if isinstance(raw, dict):
        raw = raw.get("results", [])
    results = [find_result(r) for r in raw]
    # API.md: only repositories whose rules verdict is `viable`.
    return {"results": [r for r in results if r["verdict"] == "viable"][:limit]}
