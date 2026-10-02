"""Access control for an API that can delete and move files (plan section 5.5).

- The ``Host`` header must name the bound host or a loopback name, which blocks DNS rebinding.
- A state-changing request from a browser must come from the page's own origin, or from an
  origin listed in ``server.allowed_origins``.
- When ``server.access_token`` is set, every API and socket request must carry it, as a bearer
  header, the ``hanakura_token`` cookie, or a ``token`` query parameter.
"""

import hmac
import json
from collections.abc import Callable
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from hanakura.api.paths import route_path
from hanakura.core.net.ports import is_loopback

TOKEN_COOKIE = "hanakura_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
# Paths that must work without a token: the UI shell has to load so it can ask for one.
PUBLIC_PATHS = ("/api/v1/app/health",)
# The OAuth callback only. A browser arriving from Civitai carries no Authorization header, so
# this one path and method is exempt from the access token; it is still checked against the
# transaction and the browser that started it, and the Host check still applies. The other
# /api/v1/auth routes keep normal access control.
OAUTH_CALLBACK_PATH = "/api/v1/auth/civitai/callback"
PROTECTED_PREFIXES = ("/api/", "/ws/", "/openapi.json", "/docs")


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):
        return host_header[1:].split("]")[0]
    return host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header


def request_token(scope: Scope, headers: dict[str, str]) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    cookie_header = headers.get("cookie")
    if cookie_header:
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:  # noqa: BLE001 - a malformed cookie is simply ignored
            cookie = SimpleCookie()
        if TOKEN_COOKIE in cookie:
            return cookie[TOKEN_COOKIE].value
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("token")
    return values[0] if values else None


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        bound_host: Callable[[], str],
        allowed_origins: Callable[[], list[str]],
        access_token: Callable[[], str | None],
        extra_hosts: set[str] | None = None,
        prefix: str = "",
    ) -> None:
        self.app = app
        self.bound_host = bound_host
        self.allowed_origins = allowed_origins
        self.access_token = access_token
        self.extra_hosts = extra_hosts or set()
        # Everything this package serves may sit under a prefix chosen by a host application.
        self.prefix = prefix
        self.public_paths = tuple(f"{prefix}{p}" for p in PUBLIC_PATHS)
        self.protected_prefixes = tuple(f"{prefix}{p}" for p in PROTECTED_PREFIXES)
        self.callback_path = f"{prefix}{OAUTH_CALLBACK_PATH}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        problem = self._check(scope, headers)
        if problem is not None:
            status, code, message = problem
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            body = json.dumps({"code": code, "message": message, "detail": {}}).encode()
            await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _check(self, scope: Scope, headers: dict[str, str]) -> tuple[int, str, str] | None:
        bound = self.bound_host()
        remote_mode = not is_loopback(bound)
        host = _hostname(headers.get("host", ""))
        if not remote_mode and host not in LOOPBACK_NAMES | {bound} | self.extra_hosts:
            return 400, "bad_host", "Host not allowed"

        method = scope.get("method", "GET")
        origin = headers.get("origin")
        if method not in SAFE_METHODS or scope["type"] == "websocket":
            if origin:
                own = f"{'https' if scope.get('scheme') in ('https', 'wss') else 'http'}://{headers.get('host', '')}"
                if origin != own and origin not in self.allowed_origins() and urlsplit(origin).netloc != headers.get("host", ""):
                    return 403, "bad_origin", "Cross-origin request refused"
            elif headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
                return 403, "bad_origin", "Cross-site request refused"

        token = self.access_token()
        path = route_path(scope)
        is_callback = path == self.callback_path and method == "GET"
        needs_token = path.startswith(self.protected_prefixes) and not path.startswith(self.public_paths) and not is_callback
        if token and needs_token:
            given = request_token(scope, headers)
            if not given or not hmac.compare_digest(given, token):
                return 401, "auth_required", "An access token is required"
        return None
