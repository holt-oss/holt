"""Running the Holt engine for one job. Synchronous; the jobs runner calls it
in a worker thread.

Progress: if `holt.agent.pipeline.analyze` accepts a progress callback (being
added separately), it is passed one. Either way, the provider and the model
client are wrapped so fetches, model stages and verification emit coarse
stages of their own, so a stream never sits silent for a minute.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from holt.agent import pipeline
from holt.types import EvidenceRecord, Window
from holt_server import report as report_mod
from holt_server.errors import ApiError, github_rate_limited, not_found_repo, upstream

Emit = Callable[[str, float], None]

FETCHING = "Fetching pull requests"
READING = "Reading threads"
CHECKING = "Checking evidence"
WRITING = "Writing the report"

# Model stage label -> (stage, progress). Labels are the ones `holt.agent.stages`
# passes to `ModelClient.complete`.
MODEL_STAGES = {
    "classify": (READING, 0.4),
    "opportunity": (READING, 0.5),
    "outcomes": (READING, 0.6),
    "narrate": (WRITING, 0.85),
}

PROGRESS_PARAMS = ("progress", "on_progress", "on_stage", "callback")


class Progress:
    """Never goes backwards, whichever source reports first."""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self.value = 0.0
        self.stage = ""
        # Once the engine reports progress itself, its stages win and the
        # coarse ones from the wrappers are dropped, so the two cannot alternate.
        self.engine_driven = False

    def __call__(self, stage: str | None, value: float | None = None) -> None:
        value = self.value if value is None else max(self.value, min(float(value), 0.99))
        stage = stage or self.stage
        if stage == self.stage and value == self.value:
            return
        self.stage, self.value = stage, value
        self._emit(stage, round(value, 3))

    def auto(self, stage: str, value: float) -> None:
        if not self.engine_driven:
            self(stage, value)

    def from_engine(self, *args: Any, **kwargs: Any) -> None:
        """Adapter for the engine's own callback, whatever its exact shape."""
        self.engine_driven = True
        values = list(args) + list(kwargs.values())
        stage = next((v for v in values if isinstance(v, str)), None)
        frac = next((float(v) for v in values
                     if isinstance(v, (int, float)) and not isinstance(v, bool)
                     and 0.0 <= float(v) <= 1.0), None)
        if stage is None:
            for v in values:  # an event object with .stage / .progress
                stage = stage or getattr(v, "stage", None) or getattr(v, "label", None)
                frac = frac if frac is not None else getattr(v, "progress", None)
        if stage or frac is not None:
            self(stage if isinstance(stage, str) else None, frac)


class WatchedProvider:
    """Delegates to the real provider; remembers what it read and says so."""

    def __init__(self, inner, progress: Progress) -> None:
        self.inner = inner
        self.progress = progress
        self.records: list[EvidenceRecord] = []
        self._resolving = False

    def fetch(self, request: str, /, **params: object) -> list[EvidenceRecord]:
        self.progress.auto(FETCHING, 0.05)
        records = self.inner.fetch(request, **params)
        self.records.extend(records)
        self.progress.auto(READING, 0.3)
        return records

    def resolve(self, evidence_id: str):
        if not self._resolving:
            self._resolving = True
            self.progress.auto(CHECKING, 0.75)
        return self.inner.resolve(evidence_id)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


class WatchedModel:
    def __init__(self, inner, progress: Progress) -> None:
        self.inner = inner
        self.progress = progress

    @property
    def replayed(self) -> bool:
        return self.inner.replayed

    @property
    def usage(self):
        return self.inner.usage

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict:
        if label in MODEL_STAGES:
            self.progress.auto(*MODEL_STAGES[label])
        return self.inner.complete(label=label, system=system, prompt=prompt, schema=schema)


def progress_param(fn) -> str | None:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return None
    return next((p for p in PROGRESS_PARAMS if p in params), None)


def live_provider(token: str, as_of: datetime, max_pages: int = 8):
    from holt.evidence.github_graphql import GitHubGraphQL, LiveGitHubProvider

    return LiveGitHubProvider(
        Window.PRE_T, cutoff=as_of, transport=GitHubGraphQL(token=token), max_pages=max_pages
    )


def analyze(
    *,
    repo: str,
    mode: str,
    days: int,
    provider,
    model,
    emit: Emit,
    as_of: datetime,
) -> dict[str, Any]:
    """One report, as the JSON in API.md. Raises `ApiError` on known failures."""
    progress = Progress(emit)
    watched = WatchedProvider(provider, progress)
    try:
        if mode == "ai":
            client = WatchedModel(model, progress)
            fn = pipeline.analyze
            kwargs: dict[str, Any] = {"contributor_days": days, "as_of": as_of}
            if name := progress_param(fn):
                kwargs[name] = progress.from_engine
            assessment, trace = fn(repo, watched, client, **kwargs)
        else:
            fn = pipeline.analyze_without_model
            kwargs = {"contributor_days": days, "as_of": as_of}
            if name := progress_param(fn):
                kwargs[name] = progress.from_engine
            assessment, trace = fn(repo, watched, **kwargs)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- translated, never swallowed
        raise translate(exc, repo, byok=getattr(model, "byok", False)) from exc

    progress(WRITING, 0.95)
    cost = None
    if mode == "ai" and model is not None:
        usage = model.usage
        cost = {
            "model": ", ".join(usage.models) or getattr(getattr(model, "spec", None), "model", ""),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
    return report_mod.build(
        repo=repo, mode=mode, assessment=assessment, signals=trace.signals,
        records=watched.records, cost=cost, generated_at=datetime.now(UTC),
    )


def translate(exc: Exception, repo: str, byok: bool = False) -> ApiError:
    """Engine and SDK failures -> the error codes in API.md."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (403, 429):
            from holt_server.github import retry_after_from

            return github_rate_limited(retry_after_from(exc.response))
        return upstream()
    if isinstance(exc, httpx.HTTPError):
        return upstream()
    message = str(exc)
    if "not found or not public" in message:
        return not_found_repo(repo)
    if "GraphQL error" in message:
        if "RATE_LIMITED" in message:
            return github_rate_limited()
        if "NOT_FOUND" in message:
            return not_found_repo(repo)
        return upstream()
    module = type(exc).__module__ or ""
    if module.startswith(("openai", "anthropic")):
        name = type(exc).__name__
        if byok and name in ("AuthenticationError", "PermissionDeniedError"):
            return ApiError(
                "needs_key",
                "Your AI provider rejected the API key you saved. Check it in "
                "your settings, or remove it to use your free reports.",
            )
        if name == "RateLimitError":
            return ApiError("rate_limited", "The AI model is busy right now. "
                            "Please try again in a few minutes.", retry_after=120)
        return upstream("The AI model")
    if isinstance(exc, (ValueError, KeyError)) and module.startswith("json"):
        return upstream("The AI model")
    return ApiError("internal", "Something went wrong while reading this repository. "
                    "Please try again in a minute.")
