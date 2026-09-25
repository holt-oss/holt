"""The error envelope from API.md, and the messages a beginner reads.

Every failure leaves the server as `{"error": {"code", "message"}}`, plus
`retry_after` for `rate_limited`. Messages are written for someone who has never
heard of GraphQL or an API quota.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

STATUS = {
    "unauthorized": 401,
    "not_found": 404,
    "invalid_repo": 400,
    "invalid_request": 400,
    "rate_limited": 429,
    "quota_exceeded": 402,
    "needs_key": 403,
    "upstream": 502,
    "internal": 500,
    "not_implemented": 501,
    "invalid_signature": 400,
    "already_subscribed": 409,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None,
                 status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.status = status or STATUS.get(code, 400)

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            err["retry_after"] = self.retry_after
        return err


def error_response(err: ApiError) -> JSONResponse:
    headers = {"Retry-After": str(err.retry_after)} if err.retry_after is not None else None
    return JSONResponse({"error": err.body()}, status_code=err.status, headers=headers)


def install(app) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg", "invalid value")
        return error_response(ApiError(
            "invalid_request", f"The request was not understood ({where}: {msg})."))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response(ApiError("not_found", "There is nothing at this address."))
        if exc.status_code == 405:
            return error_response(ApiError(
                "invalid_request", "That method is not allowed here.", status=405))
        return error_response(ApiError("internal", str(exc.detail), status=exc.status_code))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        return error_response(ApiError(
            "internal", "Something went wrong on our side. Please try again in a minute."))


def not_found_repo(repo: str) -> ApiError:
    return ApiError(
        "not_found",
        f"We couldn't find {repo} on GitHub. Check the spelling; private "
        "repositories can't be checked.",
    )


def github_rate_limited(retry_after: int = 600) -> ApiError:
    return ApiError(
        "rate_limited",
        "GitHub is asking us to slow down. Please try again in a few minutes.",
        retry_after=retry_after,
    )


def upstream(what: str = "GitHub") -> ApiError:
    return ApiError(
        "upstream",
        f"{what} didn't answer properly just now. Please try again in a minute.",
    )
