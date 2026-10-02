"""The Civitai OAuth endpoints: authorization URL, code exchange, refresh, revoke, userinfo.

Authorization Code with PKCE, as a public client: no client secret is shipped or stored. The
authorization service is a fixed host, never derived from the editable model-source base URL.
"""

import base64
import hashlib
import logging
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from hanakura.core.auth.models import OAuthAccount
from hanakura.core.auth.store import OAuthCredentials
from hanakura.core.errors import AuthRequiredError, SourceError

logger = logging.getLogger(__name__)

AUTHORIZE_PATH = "/api/auth/oauth/authorize"
TOKEN_PATH = "/api/auth/oauth/token"
USERINFO_PATH = "/api/auth/oauth/userinfo"
REVOKE_PATH = "/api/auth/oauth/revoke"
# Requests are made with an access token this long before it expires, so a queued download does
# not start with a token that dies mid-flight.
REFRESH_MARGIN_SECONDS = 60.0


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


class CivitaiOAuthClient:
    def __init__(self, client: Callable[[], httpx.Client], base_url: str, client_id: str) -> None:
        self._client = client
        self.base_url = base_url.rstrip("/")
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

    def refresh(self, refresh_token: str) -> OAuthCredentials:
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}
        try:
            body = self._post(TOKEN_PATH, data, "Civitai token refresh")
        except AuthRequiredError as e:
            # A refused refresh token cannot be retried; the user has to authorize again.
            raise ReauthorizationRequired(str(e)) from e
        credentials = self._credentials(body)
        if credentials.refresh_token is None:
            # The provider rotates the pair; keep the old refresh token only if none came back.
            credentials = credentials.model_copy(update={"refresh_token": refresh_token})
        return credentials

    def revoke(self, token: str, token_type: str = "refresh_token") -> None:
        """Ask the provider to drop the token. A failure here is reported, never fatal."""
        self._post(REVOKE_PATH, {"token": token, "token_type_hint": token_type, "client_id": self.client_id}, "Civitai token revocation")

    def userinfo(self, access_token: str) -> OAuthAccount:
        try:
            response = self._client().get(f"{self.base_url}{USERINFO_PATH}", headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as e:
            raise SourceError(f"Civitai userinfo: {e}") from e
        if response.status_code >= 400:
            raise self._error(response, "Civitai userinfo")
        body = response.json()
        identifier = body.get("sub") or body.get("id") or body.get("userId")
        return OAuthAccount(id=str(identifier) if identifier is not None else None, username=body.get("username") or body.get("name"))

    # -- helpers ------------------------------------------------------------

    def _post(self, path: str, data: dict[str, str], what: str) -> dict[str, Any]:
        try:
            response = self._client().post(f"{self.base_url}{path}", data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise SourceError(f"{what}: {e}") from e
        if response.status_code >= 400:
            raise self._error(response, what)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as e:
            raise SourceError(f"{what}: the response was not JSON") from e

    @staticmethod
    def _error(response: httpx.Response, what: str) -> Exception:
        """Turn an error response into a domain error, with the provider's reason but no secrets."""
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("error_description") or body.get("error") or "")[:200]
        except ValueError:
            detail = ""
        message = f"{what}: HTTP {response.status_code}{f' ({detail})' if detail else ''}"
        if response.status_code in (400, 401, 403):
            return AuthRequiredError(message)
        return SourceError(message)

    def _credentials(self, body: dict[str, Any]) -> OAuthCredentials:
        access_token = body.get("access_token")
        if not access_token:
            raise SourceError("Civitai returned no access token")
        expires_in = body.get("expires_in")
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=float(expires_in)) if isinstance(expires_in, (int, float, str)) and str(expires_in).isdigit() else None
        scope = body.get("scope")
        return OAuthCredentials(
            access_token=str(access_token),
            refresh_token=str(body["refresh_token"]) if body.get("refresh_token") else None,
            expires_at=expires_at,
            scope=int(scope) if isinstance(scope, (int, str)) and str(scope).isdigit() else None,
            client_id=self.client_id,
            obtained_at=datetime.now(tz=timezone.utc),
        )
