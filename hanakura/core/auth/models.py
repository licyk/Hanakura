"""Records for Civitai authentication. None of them ever carries a token."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from hanakura.core.record import Record
from hanakura.core.settings.models import AuthMethod

# not_connected: no OAuth credentials. pending: an authorization is in flight.
# connected: usable credentials. reauthorization_required: the refresh token is gone or refused.
OAuthState = Literal["not_connected", "pending", "connected", "reauthorization_required"]

# Where the credential actually in use comes from. "environment" is an env override, which wins.
CredentialSource = Literal["none", "settings", "environment", "oauth"]


class OAuthAccount(Record):
    """The minimum needed to show whose account is connected."""

    id: str | None = None
    username: str | None = None


class CivitaiAuthStatus(Record):
    method: AuthMethod
    """The method the user selected."""
    effective_method: AuthMethod
    """The method requests actually use, which an environment override can force to manual."""
    credential_source: CredentialSource
    oauth_state: OAuthState
    oauth_configured: bool
    """Whether a client id is configured, without which no authorization can start."""
    manual_token_configured: bool
    env_override: bool
    account: OAuthAccount | None = None
    scope: int | None = None
    expires_at: datetime | None = None
    error: str | None = None
    """Why the last OAuth step failed, for the interface to show. Never a credential."""


class AuthStart(Record):
    authorization_url: str
    expires_at: datetime


class StartRequest(Record):
    return_to: str | None = Field(default=None, description="Path inside the app to return to; must be relative")


class MethodRequest(Record):
    method: AuthMethod
