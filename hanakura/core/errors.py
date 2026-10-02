"""Domain exceptions shared by the API and the command line."""

from typing import Any


class HanakuraError(Exception):
    """Base class for every error the wrappers translate."""

    code = "internal_error"
    http_status = 500
    exit_code = 1

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(HanakuraError):
    """A requested object does not exist."""

    code = "not_found"
    http_status = 404
    exit_code = 2


class ConflictError(HanakuraError):
    """The target already exists, or the object is in a state that forbids the operation."""

    code = "conflict"
    http_status = 409
    exit_code = 3


class InvalidPathError(HanakuraError):
    """A path is outside its root, or a name is not allowed."""

    code = "invalid_path"
    http_status = 400
    exit_code = 4


class ValidationError(HanakuraError):
    """An input value is not acceptable."""

    code = "invalid_input"
    http_status = 400
    exit_code = 4


class AuthRequiredError(HanakuraError):
    """The source needs a token."""

    code = "auth_required"
    http_status = 401
    exit_code = 5


class SourceError(HanakuraError):
    """An upstream service failed."""

    code = "source_error"
    http_status = 502
    exit_code = 6


class RateLimitedError(SourceError):
    """An upstream service answered 429."""

    code = "rate_limited"
    http_status = 429

    def __init__(self, message: str, retry_after: float | None = None, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message, {**(detail or {}), "retry_after": retry_after})
        self.retry_after = retry_after
