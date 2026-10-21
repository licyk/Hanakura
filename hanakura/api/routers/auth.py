"""Civitai authentication: sign in, return from the provider, sessions, status, disconnect.

The browser never receives an access or refresh token, a code verifier or a device code. Only
the callbacks are reachable without the application's access token, because the browser arrives
from Civitai with no header to carry it; such a request is still tied to the sign-in and the
browser that started it.
"""

import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.api.paths import public_prefix
from hanakura.core.auth.clients import ResolvedClient
from hanakura.core.auth.models import AuthErrorReason, AuthStart, CivitaiAuthStatus, LoginSession, MethodRequest, StartRequest
from hanakura.core.auth.oauth_client import reason_of
from hanakura.core.errors import HanakuraError, ValidationError
from hanakura.core.net.ports import is_loopback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth/civitai", tags=["auth"], responses=ERROR_RESPONSES)
# The bundled client's fixed loopback callback, served only at the root of a standalone server.
root_router = APIRouter()

AUTH_PATH = "/api/v1/auth/civitai"
CALLBACK_PATH = f"{AUTH_PATH}/callback"
ROOT_CALLBACK_PATH = "/civitai/callback"
BINDING_COOKIE = "hanakura_oauth"
# The root callback lies outside the auth path, so it gets a cookie of its own carrying the same binding.
ROOT_BINDING_COOKIE = "hanakura_oauth_cb"
# Long enough for a device code, which Civitai keeps for fifteen minutes.
COOKIE_MAX_AGE = 960
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _bracket(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _loopback_request_host(request: Request) -> str | None:
    """The loopback name the browser used, so the callback reaches the host its cookie was set for."""
    host = (request.url.hostname or "").strip("[]")
    return host if host in LOOPBACK_NAMES else None


def callback_url(request: Request, services: ServicesDep, client: ResolvedClient | None = None) -> str:
    """The callback to use, from the configured allowlist or built for the bound address.

    The address is never taken from forwarding headers, and a Host header is only trusted as far
    as the security middleware already checked it: a loopback name. A callback has to match one
    registered with Civitai, and an attacker must not be able to choose it. Raises
    ``ValidationError`` when Civitai has no way back to this deployment.
    """
    if client is not None and client.callback_path:
        return _root_callback(request, services, client.callback_path)
    base = getattr(request.app.state, "public_base_url", None)
    allowed = services.settings.settings.auth.civitai.redirect_uris
    if base:
        callback = f"{base}{CALLBACK_PATH}"
        if allowed and callback not in allowed:
            raise ValidationError("public_base_url does not match a registered auth.civitai.redirect_uris callback", {"reason": "callback_unsupported"})
        return callback
    prefix = public_prefix(request)
    path = f"{prefix}{CALLBACK_PATH}"
    if allowed:
        origin = f"{request.url.scheme}://{request.url.netloc}"
        match = next((uri for uri in allowed if (urlsplit(uri).scheme, urlsplit(uri).netloc) == (request.url.scheme, request.url.netloc) and urlsplit(uri).path == path), None)
        if match is None:
            raise ValidationError(
                f"No callback is registered for {origin}. Add the exact URL to auth.civitai.redirect_uris and register it with Civitai, or use a manual API token.",
                {"reason": "callback_unsupported"},
            )
        return match
    bound = getattr(request.app.state, "bound_host", None) or services.settings.settings.server.host
    port = getattr(request.app.state, "bound_port", None) or services.settings.settings.server.port
    host = _loopback_request_host(request)
    if host is None:
        if bound in ("0.0.0.0", "::"):
            # The browser is on another machine: its own localhost is not this server.
            raise ValidationError(
                "Civitai can only call back to an address registered for this server: list it in auth.civitai.redirect_uris, or sign in with a device code.",
                {"reason": "callback_unsupported"},
            )
        host = "127.0.0.1" if bound == "localhost" else bound
    return f"http://{_bracket(host)}:{port}{path}"


def _root_callback(request: Request, services: ServicesDep, path: str) -> str:
    """A loopback callback at a fixed root path, as a bundled client's registration requires."""
    bound = getattr(request.app.state, "bound_host", None) or services.settings.settings.server.host
    if not getattr(request.app.state, "root_callback", False) or public_prefix(request) or not is_loopback(bound):
        raise ValidationError(
            f"The bundled Civitai sign-in returns to {path} on this computer, which needs Hanakura served locally at the root of its address. "
            "Sign in with a device code, use an API token, or set your own OAuth application.",
            {"reason": "callback_unsupported"},
        )
    host = _loopback_request_host(request) or "127.0.0.1"
    port = getattr(request.app.state, "bound_port", None) or request.url.port or services.settings.settings.server.port
    return f"http://{_bracket(host)}:{port}{path}"


def _browser_callback(request: Request, services: ServicesDep) -> tuple[str | None, str | None]:
    client = services.auth.resolved()[0]
    if client is None:
        return None, None
    try:
        return callback_url(request, services, client), None
    except ValidationError as e:
        return None, e.message


def _secure(request: Request) -> bool:
    # Set only over HTTPS: a loopback deployment is plain HTTP and would drop the cookie.
    return urlsplit(getattr(request.app.state, "public_base_url", None) or str(request.url)).scheme == "https"


@router.post("/start", operation_id="start_civitai_auth")
def start(request: Request, response: Response, services: ServicesDep, body: StartRequest | None = None) -> AuthStart:
    """Begin a sign-in: a browser one returns Civitai's consent page, a device one its code."""
    body = body or StartRequest()
    return_to = body.return_to or None
    if return_to and (urlsplit(return_to).scheme or return_to.startswith("//")):
        raise ValidationError("return_to must be a path inside this application")
    client = services.auth.require_client()
    redirect, unavailable = _browser_callback(request, services)
    flow = services.auth.choose_flow(body.flow, redirect is not None, unavailable)
    result, secret = services.auth.start(redirect, return_to, flow=flow, binding_secret=request.cookies.get(BINDING_COOKIE))
    prefix = public_prefix(request)
    response.set_cookie(BINDING_COOKIE, secret, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=_secure(request), path=f"{prefix}{AUTH_PATH}")
    if flow == "browser" and client.callback_path:
        response.set_cookie(ROOT_BINDING_COOKIE, secret, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=_secure(request), path=client.callback_path)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/sessions/{session_id}", operation_id="get_civitai_auth_session")
def session(request: Request, response: Response, services: ServicesDep, session_id: str) -> LoginSession:
    """A sign-in's state, for the browser that started it. Reading it never contacts Civitai."""
    response.headers["Cache-Control"] = "no-store"
    return services.auth.session(session_id, request.cookies.get(BINDING_COOKIE))


@router.post("/sessions/{session_id}/cancel", operation_id="cancel_civitai_auth_session")
def cancel_session(request: Request, services: ServicesDep, session_id: str) -> LoginSession:
    """Cancel a sign-in; whatever it would have connected is never stored. Cancelling twice is harmless."""
    return services.auth.cancel_session(session_id, request.cookies.get(BINDING_COOKIE))


def _reason_for_callback_error(error: str, description: str) -> AuthErrorReason:
    if error == "access_denied":
        return "denied"
    if error == "invalid_scope":
        return "insufficient_scope"
    if error in ("invalid_client", "unauthorized_client"):
        return "client_unavailable"
    if "redirect_uri" in description:
        return "redirect_mismatch"
    return "failed"


def _finish(request: Request, services: ServicesDep, code: str | None, state: str | None, error: str | None, error_description: str | None, root: bool) -> Response:
    """Shared by both callbacks. Never shows a token, and keeps no authorization data in the URL."""
    cookie_name = ROOT_BINDING_COOKIE if root else BINDING_COOKIE
    binding = request.cookies.get(cookie_name)
    target = "/#/settings"
    status = "error"
    reason: AuthErrorReason = "failed"
    if error:
        error = _CONTROL.sub(" ", error)[:64]
        description = _CONTROL.sub(" ", error_description or "")[:200]
        reason = _reason_for_callback_error(error, description)
        logger.info("Civitai authorization was refused: %s", error)
        if state:
            services.auth.deny(state, binding, reason, f"Civitai refused the authorization ({description or error}).")
    elif not code or not state:
        logger.info("A Civitai callback arrived without a code or state")
    else:
        try:
            target = services.auth.complete(state, code, binding, root_callback=root)
            status = "connected"
        except HanakuraError as e:
            reason = reason_of(e)
            logger.info("Completing the Civitai authorization failed: %s", e)

    prefix = public_prefix(request)
    if prefix and target.startswith("/") and not target.startswith(f"{prefix}/"):
        target = f"{prefix}{target}"
    separator = "&" if "?" in target else "?"
    outcome = "civitai=connected" if status == "connected" else f"civitai=error&civitai_reason={reason}"
    response = RedirectResponse(f"{target}{separator}{outcome}", status_code=303)
    # The binding stays while another sign-in from this browser still needs it.
    if not services.auth.transactions.binding_in_use(binding):
        response.delete_cookie(BINDING_COOKIE, path=f"{prefix}{AUTH_PATH}", httponly=True, samesite="lax", secure=_secure(request))
        if root:
            response.delete_cookie(ROOT_BINDING_COOKIE, path=ROOT_CALLBACK_PATH, httponly=True, samesite="lax", secure=_secure(request))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/callback", operation_id="civitai_auth_callback", include_in_schema=False)
def callback(
    request: Request, services: ServicesDep, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None
) -> Response:
    """Where Civitai sends the browser back for an application registered with this path."""
    return _finish(request, services, code, state, error, error_description, root=False)


@root_router.get(ROOT_CALLBACK_PATH, include_in_schema=False)
def root_callback(
    request: Request, services: ServicesDep, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None
) -> Response:
    """Where Civitai sends the browser back for the bundled client, on a standalone local server only."""
    client = services.auth.resolved()[0]
    if client is None or client.callback_path != ROOT_CALLBACK_PATH or public_prefix(request):
        raise HTTPException(status_code=404)
    return _finish(request, services, code, state, error, error_description, root=True)


@router.get("/status", operation_id="get_civitai_auth_status")
def status(request: Request, services: ServicesDep) -> CivitaiAuthStatus:
    redirect, _unavailable = _browser_callback(request, services)
    return services.auth.status(browser_available=redirect is not None, browser_reason="callback_unsupported" if redirect is None else None)


@router.post("/disconnect", operation_id="disconnect_civitai_auth")
def disconnect(services: ServicesDep) -> CivitaiAuthStatus:
    """Cancel sign-ins in flight, forget the OAuth credentials and ask Civitai to revoke them. The manual token is left untouched."""
    return services.auth.disconnect()


@router.post("/method", operation_id="set_civitai_auth_method")
def set_method(services: ServicesDep, body: MethodRequest) -> CivitaiAuthStatus:
    """Choose which credential to use. Nothing else ever changes this."""
    return services.auth.set_method(body.method)


class CallbackQueryFilter(logging.Filter):
    """Keeps an authorization code or state out of the access log, should a host turn it on."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            path, _, _query = args[2].partition("?")
            if path.endswith(ROOT_CALLBACK_PATH):
                record.args = (*args[:2], f"{path}?[redacted]", *args[3:])
        return True


def redact_callback_logs() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, CallbackQueryFilter) for f in access.filters):
        access.addFilter(CallbackQueryFilter())
