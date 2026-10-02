"""Deployment paths shared by mounted apps, authentication and Socket.IO."""

from urllib.parse import urlsplit

from starlette import _utils
from starlette.requests import Request
from starlette.types import Scope


def route_path(scope: Scope) -> str:
    """Older Starlette strips mount prefixes; newer versions leave that to the router."""
    resolve = getattr(_utils, "get_route_path", None)
    return resolve(scope) if resolve is not None else scope.get("path", "")


def public_prefix(request: Request) -> str:
    base = getattr(request.app.state, "public_base_url", None)
    if base:
        return urlsplit(base).path.rstrip("/")
    root = request.scope.get("root_path", "").rstrip("/")
    return root + (getattr(request.app.state, "api_prefix", "") or "")


def validate_public_base_url(value: str | None) -> str | None:
    """Only the host application may supply this URL; never derive it from forwarded headers."""
    if value is None:
        return None
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
        raise ValueError("public_base_url must be an absolute HTTP(S) URL without credentials, query or fragment")
    if any(c.isspace() for c in value) or "\\" in value:
        raise ValueError("public_base_url contains invalid characters")
    return value.rstrip("/")
