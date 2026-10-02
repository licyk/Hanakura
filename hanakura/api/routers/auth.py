"""Civitai authentication: connect, return from the provider, status, disconnect.

The browser never receives an access or refresh token. Only the callback is reachable without
the application's access token, because the browser arrives from Civitai with no header to
carry it; that request is still tied to the transaction and the browser that started it.
"""

import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.api.paths import public_prefix
from hanakura.core.auth.models import AuthStart, CivitaiAuthStatus, MethodRequest, StartRequest
from hanakura.core.errors import HanakuraError, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth/civitai", tags=["auth"], responses=ERROR_RESPONSES)

CALLBACK_PATH = "/api/v1/auth/civitai/callback"
BINDING_COOKIE = "hanakura_oauth"
COOKIE_MAX_AGE = 600


def callback_url(request: Request, services: ServicesDep) -> str:
    """The callback to use, taken from the configured allowlist or built for the bound address.

    The address is never taken from the Host header or forwarding headers: a callback has to
    match one registered with Civitai exactly, and an attacker must not be able to choose it.
    """
    base = getattr(request.app.state, "public_base_url", None)
    allowed = services.settings.settings.auth.civitai.redirect_uris
    if base:
        callback = f"{base}{CALLBACK_PATH}"
        if allowed and callback not in allowed:
            raise ValidationError("public_base_url does not match a registered auth.civitai.redirect_uris callback")
        return callback
    prefix = public_prefix(request)
    path = f"{prefix}{CALLBACK_PATH}"
    if allowed:
        origin = f"{request.url.scheme}://{request.url.netloc}"
        match = next((uri for uri in allowed if (urlsplit(uri).scheme, urlsplit(uri).netloc) == (request.url.scheme, request.url.netloc) and urlsplit(uri).path == path), None)
        if match is None:
            raise ValidationError(
                f"No callback is registered for {origin}. Add the exact URL to auth.civitai.redirect_uris and register it with Civitai, or use a manual API token."
            )
        return match
    host = services.settings.settings.server.host
    port = getattr(request.app.state, "bound_port", None) or services.settings.settings.server.port
    host = "127.0.0.1" if host in ("0.0.0.0", "::", "localhost") else host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}{path}"


@router.post("/start", operation_id="start_civitai_auth")
def start(request: Request, response: Response, services: ServicesDep, body: StartRequest | None = None) -> AuthStart:
    """Begin an authorization and return the URL for the user's browser."""
    return_to = (body.return_to if body else None) or None
    if return_to and (urlsplit(return_to).scheme or return_to.startswith("//")):
        raise ValidationError("return_to must be a path inside this application")
    start_result, secret = services.auth.start(callback_url(request, services), return_to)
    response.set_cookie(
        BINDING_COOKIE,
        secret,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Set only over HTTPS: a loopback deployment is plain HTTP and would drop the cookie.
        secure=urlsplit(getattr(request.app.state, "public_base_url", None) or str(request.url)).scheme == "https",
        path=f"{public_prefix(request)}/api/v1/auth/civitai",
    )
    return start_result


@router.get("/callback", operation_id="civitai_auth_callback", include_in_schema=False)
def callback(
    request: Request, services: ServicesDep, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None
) -> Response:
    """Where Civitai sends the browser back. Never shows a token, and keeps none in the URL."""
    binding = request.cookies.get(BINDING_COOKIE)
    target = "/#/settings"
    status = "error"
    if error:
        logger.info("Civitai authorization was refused: %s", error)
        if state:
            services.auth.transactions.discard(state)
    elif not code or not state:
        logger.info("A Civitai callback arrived without a code or state")
    else:
        try:
            target = services.auth.complete(state, code, binding)
            status = "connected"
        except HanakuraError as e:
            logger.info("Completing the Civitai authorization failed: %s", e)

    prefix = public_prefix(request)
    if prefix and target.startswith("/") and not target.startswith(f"{prefix}/"):
        target = f"{prefix}{target}"
    separator = "&" if "?" in target else "?"
    response = RedirectResponse(f"{target}{separator}civitai={status}", status_code=303)
    response.delete_cookie(BINDING_COOKIE, path=f"{prefix}/api/v1/auth/civitai")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/status", operation_id="get_civitai_auth_status")
def status(services: ServicesDep) -> CivitaiAuthStatus:
    return services.auth.status()


@router.post("/disconnect", operation_id="disconnect_civitai_auth")
def disconnect(services: ServicesDep) -> CivitaiAuthStatus:
    """Revoke and forget the OAuth credentials. The manual token is left untouched."""
    return services.auth.disconnect()


@router.post("/method", operation_id="set_civitai_auth_method")
def set_method(services: ServicesDep, body: MethodRequest) -> CivitaiAuthStatus:
    """Choose which credential to use. Nothing else ever changes this."""
    return services.auth.set_method(body.method)
