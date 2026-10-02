"""Map domain exceptions onto one JSON error shape."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from hanakura.core.errors import HanakuraError
from hanakura.core.record import Record


class ErrorResponse(Record):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


def error_response(status: int, code: str, message: str, detail: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": detail or {}}, headers=headers)


async def _domain_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HanakuraError)
    headers = None
    retry_after = exc.detail.get("retry_after") if isinstance(exc.detail, dict) else None
    if exc.http_status == 429 and retry_after is not None:
        headers = {"Retry-After": str(int(retry_after))}
    return error_response(exc.http_status, exc.code, exc.message, exc.detail, headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HanakuraError, _domain_error)


# Declared on routes so the generated client knows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}
