"""Running the Holt engine for one job. Synchronous; the jobs runner calls it
in a worker thread.

The engine reports its own plain-English stages through `progress=`; this
passes them on, never letting the bar go backwards and holding back the final
"Done" until the report has actually been written down.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from holt.agent import pipeline
from holt.evidence.errors import AuthError, GitHubError, RateLimited, RepoNotFound
from holt.types import EvidenceRecord, Window
from holt_server import report as report_mod
from holt_server.errors import ApiError, github_rate_limited, not_found_repo, upstream

Emit = Callable[[str, float], None]

FINAL_STAGE = "Writing the report"


class Progress:
    """Forwards engine stages; never goes backwards, never reports 1.0 itself."""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self.value = 0.0
        self.stage = ""

    def __call__(self, stage: str, value: float) -> None:
        if stage == "Done":
            return  # the job is done when the result is stored, not before
        value = max(self.value, min(float(value), 0.99))
        if (stage, value) == (self.stage, self.value):
            return
        self.stage, self.value = stage, value
        self._emit(stage, round(value, 3))


class RecordingProvider:
    """Delegates to the real provider and keeps what it read.

    The report needs the records for landing areas and evidence URLs, and the
    provider API has no other way to hand them back.
    """

    def __init__(self, inner) -> None:
        self.inner = inner
        self.records: list[EvidenceRecord] = []

    def fetch(self, request: str, /, **params: object) -> list[EvidenceRecord]:
        records = self.inner.fetch(request, **params)
        self.records.extend(records)
        return records

    def resolve(self, evidence_id: str):
        return self.inner.resolve(evidence_id)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def live_provider(token: str, as_of: datetime, max_pages: int = 8, http=None):
    from holt.evidence.github_graphql import GitHubGraphQL, LiveGitHubProvider

    return LiveGitHubProvider(
        Window.PRE_T, cutoff=as_of, transport=GitHubGraphQL(token=token, client=http),
        max_pages=max_pages,
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
    recording = RecordingProvider(provider)
    try:
        if mode == "ai":
            assessment, trace = pipeline.analyze(
                repo, recording, model, contributor_days=days, as_of=as_of,
                progress=progress)
        else:
            assessment, trace = pipeline.analyze_without_model(
                repo, recording, contributor_days=days, as_of=as_of, progress=progress)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- translated, never swallowed
        raise translate(exc, repo, byok=getattr(model, "byok", False)) from exc

    progress(FINAL_STAGE, 0.95)
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
        records=recording.records, cost=cost, generated_at=datetime.now(UTC),
    )


def translate(exc: Exception, repo: str, byok: bool = False) -> ApiError:
    """Engine and SDK failures -> the error codes in API.md."""
    if isinstance(exc, RepoNotFound):
        return not_found_repo(repo)
    if isinstance(exc, RateLimited):
        return github_rate_limited(round(exc.retry_after) if exc.retry_after else 600)
    if isinstance(exc, AuthError):
        # The server's token, not the user's doing; the detail stays in the log.
        return upstream()
    if isinstance(exc, GitHubError):
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
    if isinstance(exc, ValueError) and module.startswith("json"):
        return upstream("The AI model")
    return ApiError("internal", "Something went wrong while reading this repository. "
                    "Please try again in a minute.")
