"""The Civitai OAuth endpoints: authorization URL, code exchange, device grant, refresh, revoke, userinfo.

Authorization Code with PKCE, and the device grant, as a public client: no client secret is
shipped or stored. The authorization service is a fixed host, never derived from the editable
model-source base URL. Every error carries a ``reason`` in its detail (``models.AuthErrorReason``)
and the provider's own description, cut short, never a credential.
"""

import base64
import hashlib
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast, get_args
from urllib.parse import urlencode, urlsplit

import httpx

from hanakura.core.auth.models import AuthErrorReason, OAuthAccount
from hanakura.core.auth.store import OAuthCredentials
from hanakura.core.errors import AuthRequiredError, HanakuraError, SourceError

logger = logging.getLogger(__name__)

AUTHORIZE_PATH = "/api/auth/oauth/authorize"
TOKEN_PATH = "/api/auth/oauth/token"
USERINFO_PATH = "/api/auth/oauth/userinfo"
REVOKE_PATH = "/api/auth/oauth/revoke"
# Civitai polls device codes at their own path, not at the token endpoint.
DEVICE_PATH = "/api/auth/oauth/device"
DEVICE_TOKEN_PATH = "/api/auth/oauth/device-token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# Requests are made with an access token this long before it expires, so a queued download does
# not start with a token that dies mid-flight.
REFRESH_MARGIN_SECONDS = 60.0
DEFAULT_DEVICE_LIFETIME = 600.0
DEFAULT_DEVICE_INTERVAL = 5.0
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ReauthorizationRequired(AuthRequiredError):
    """The refresh token is gone or refused: only the user can fix this, by connecting again."""

    code = "reauthorization_required"


def make_verifier() -> str:
    """A PKCE code verifier: 43 to 128 unreserved characters."""
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")


def challenge_for(verifier: str) -> str:
    """The S256 challenge: base64url of the SHA256 of the verifier, without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def parse_scope(value: Any) -> int | None:
    """The granted scope bitmask. Civitai sends a number, a decimal string, or a one-item list of either."""
    if isinstance(value, list):
        return parse_scope(value[0]) if len(value) == 1 else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def reason_of(error: Exception) -> AuthErrorReason:
    """The ``reason`` an error carries, else "failed"."""
    detail = getattr(error, "detail", None) or {}
    reason = detail.get("reason")
    return cast("AuthErrorReason", reason) if reason in get_args(AuthErrorReason) else "failed"


def _reason_for(error: str, description: str, status: int) -> AuthErrorReason:
    if error == "invalid_scope":
        return "insufficient_scope"
    if error in ("invalid_client", "unauthorized_client"):
        return "client_unavailable"
    if error == "access_denied":
        return "denied"
    if error == "expired_token":
        return "expired"
    if "redirect_uri" in description or error == "redirect_uri_mismatch":
        return "redirect_mismatch"
    if status == 429 or status >= 500:
        return "network"
    return "failed"


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: float
    interval: float


DevicePoll = Literal["pending", "slow_down"]


class CivitaiOAuthClient:
    def __init__(self, client: Callable[[], httpx.Client], issuer: str, client_id: str) -> None:
        self._client = client
        self.base_url = issuer.rstrip("/")
        self.client_id = client_id

    # -- authorization ------------------------------------------------------

    def authorization_url(self, redirect_uri: str, state: str, verifier: str, scope: int) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": str(scope),
                "state": state,
                "code_challenge": challenge_for(verifier),
                "code_challenge_method": "S256",
            }
        )
        return f"{self.base_url}{AUTHORIZE_PATH}?{query}"

    def device_authorization(self, scope: int) -> DeviceAuthorization:
        """Ask for a device code. Only the user code and verification page are ever shown."""
        body = self._post(DEVICE_PATH, {"client_id": self.client_id, "scope": str(scope)}, "Civitai device authorization")
        device_code, user_code = body.get("device_code"), body.get("user_code")
        if not isinstance(device_code, str) or not device_code or not isinstance(user_code, str) or not user_code:
            raise SourceError("Civitai device authorization: the answer had no device or user code", {"reason": "failed"})
        verification_uri = body.get("verification_uri")
        if not isinstance(verification_uri, str) or not self.trusted_verification_url(verification_uri):
            # Never send the user to a page the authorization service does not own.
            raise SourceError("Civitai device authorization: the verification page is not on Civitai", {"reason": "failed"})
        complete = body.get("verification_uri_complete")
        if not isinstance(complete, str) or not self.trusted_verification_url(complete):
            complete = None
        return DeviceAuthorization(
            device_code, user_code, verification_uri, complete, _positive(body.get("expires_in"), DEFAULT_DEVICE_LIFETIME), _positive(body.get("interval"), DEFAULT_DEVICE_INTERVAL)
        )

    def trusted_verification_url(self, url: str) -> bool:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        issuer_host = (urlsplit(self.base_url).hostname or "").lower()
        civitai = host == "civitai.com" or host.endswith(".civitai.com")
        return parts.scheme == "https" and not parts.username and not parts.password and (host == issuer_host or (civitai and issuer_host.endswith("civitai.com")))

    # -- tokens -------------------------------------------------------------

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> OAuthCredentials:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        return self._credentials(self._post(TOKEN_PATH, data, "Civitai token exchange"))

    def poll_device(self, device_code: str) -> OAuthCredentials | DevicePoll:
        """One poll. Returns the credentials, or whether to keep waiting or slow down; raises when it is over."""
        data = {"grant_type": DEVICE_GRANT, "device_code": device_code, "client_id": self.client_id}
        try:
            response = self._client().post(f"{self.base_url}{DEVICE_TOKEN_PATH}", data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise SourceError(f"Civitai device sign-in: {type(e).__name__}", {"reason": "network"}) from e
        if response.status_code == 429:
            return "slow_down"
        if response.status_code >= 400:
            error, _ = self._error_fields(response)
            if error == "authorization_pending":
                return "pending"
            if error == "slow_down":
                return "slow_down"
            raise self._error(response, "Civitai device sign-in")
        return self._credentials(self._json(response, "Civitai device sign-in"))

    def refresh(self, refresh_token: str) -> OAuthCredentials:
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}
        try:
            body = self._post(TOKEN_PATH, data, "Civitai token refresh")
        except AuthRequiredError as e:
            # A refused refresh token cannot be retried; the user has to authorize again.
            raise ReauthorizationRequired(str(e), e.detail) from e
        credentials = self._credentials(body)
        if credentials.refresh_token is None:
            # The provider rotates the pair; keep the old refresh token only if none came back.
            credentials = credentials.model_copy(update={"refresh_token": refresh_token})
        return credentials

    def revoke(self, token: str, token_type: str = "refresh_token") -> None:
        """Ask the provider to drop the token. Civitai answers 200 either way, so success is not proof."""
        self._post(REVOKE_PATH, {"token": token, "token_type_hint": token_type, "client_id": self.client_id}, "Civitai token revocation")

    def userinfo(self, access_token: str) -> OAuthAccount:
        try:
            response = self._client().get(f"{self.base_url}{USERINFO_PATH}", headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as e:
            raise SourceError(f"Civitai userinfo: {type(e).__name__}", {"reason": "network"}) from e
        if response.status_code >= 400:
            raise self._error(response, "Civitai userinfo")
        body = self._json(response, "Civitai userinfo")
        identifier = body.get("sub") or body.get("id") or body.get("userId")
        username = body.get("preferred_username") or body.get("username") or body.get("name")
        return OAuthAccount(id=str(identifier) if identifier is not None else None, username=str(username) if username else None)

    # -- helpers ------------------------------------------------------------

    def _post(self, path: str, data: dict[str, str], what: str) -> dict[str, Any]:
        try:
            response = self._client().post(f"{self.base_url}{path}", data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            # The exception text can carry the request URL; its type says enough.
            raise SourceError(f"{what}: {type(e).__name__}", {"reason": "network"}) from e
        if response.status_code >= 400:
            raise self._error(response, what)
        return self._json(response, what)

    @staticmethod
    def _json(response: httpx.Response, what: str) -> dict[str, Any]:
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError as e:
            raise SourceError(f"{what}: the response was not JSON", {"reason": "failed"}) from e
        return body if isinstance(body, dict) else {}

    @staticmethod
    def _error_fields(response: httpx.Response) -> tuple[str, str]:
        try:
            body = response.json()
        except ValueError:
            return "", ""
        if not isinstance(body, dict):
            return "", ""
        error = _CONTROL.sub(" ", str(body.get("error") or ""))[:64]
        description = _CONTROL.sub(" ", str(body.get("error_description") or ""))[:200]
        return error, description

    @classmethod
    def _error(cls, response: httpx.Response, what: str) -> HanakuraError:
        """Turn an error response into a domain error, with the provider's reason but no secrets."""
        error, description = cls._error_fields(response)
        detail = description or error
        message = f"{what}: HTTP {response.status_code}{f' ({detail})' if detail else ''}"
        info = {"reason": _reason_for(error, description, response.status_code), "error": error}
        if response.status_code in (400, 401, 403):
            return AuthRequiredError(message, info)
        return SourceError(message, info)

    def _credentials(self, body: dict[str, Any]) -> OAuthCredentials:
        access_token = body.get("access_token")
        if not access_token:
            raise SourceError("Civitai returned no access token", {"reason": "failed"})
        expires_in = body.get("expires_in")
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=float(expires_in)) if isinstance(expires_in, (int, float, str)) and str(expires_in).isdigit() else None
        return OAuthCredentials(
            access_token=str(access_token),
            refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
            expires_at=expires_at,
            scope=parse_scope(body.get("scope")),
            client_id=self.client_id,
            issuer=self.base_url,
            obtained_at=datetime.now(tz=timezone.utc),
        )


def _positive(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
