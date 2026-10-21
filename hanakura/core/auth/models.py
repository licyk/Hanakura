"""Records for Civitai authentication. None of them ever carries a token."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from hanakura.core.auth.clients import ClientSource, Flow, UnavailableReason
from hanakura.core.record import Record
from hanakura.core.settings.models import AuthMethod

# not_connected: no OAuth credentials. pending: an authorization is in flight.
# connected: usable credentials. reauthorization_required: the refresh token is gone or refused.
OAuthState = Literal["not_connected", "pending", "connected", "reauthorization_required"]

# Where the credential actually in use comes from. "environment" is an env override, which wins.
CredentialSource = Literal["none", "settings", "environment", "oauth"]

# One sign-in attempt, apart from the account's long-lived state: one tab's failure says nothing
# about the account another tab connected.
SessionStatus = Literal["pending", "exchanging", "connected", "denied", "expired", "cancelled", "failed"]

# Why an authorization failed, so the interface can say what to do rather than suggest a token.
AuthErrorReason = Literal[
    "insufficient_scope",
    "redirect_mismatch",
    "client_unavailable",
    "callback_unsupported",
    "network",
    "denied",
    "expired",
    "binding",
    "client_changed",
    "cancelled",
    "failed",
]

FlowChoice = Literal["auto", "browser", "device"]


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
    oauth_enabled: bool
    oauth_configured: bool
    """Whether an OAuth client can be resolved: one configured, or a verified bundled one."""
    client_source: ClientSource | None = None
    client_name: str | None = None
    """The application name Civitai shows when consent is asked, when it is known."""
    flows: list[Flow] = Field(default_factory=list)
    """The sign-in flows that can run in this deployment, best first."""
    unavailable_reason: UnavailableReason | None = None
    manual_token_configured: bool
    env_override: bool
    account: OAuthAccount | None = None
    scope: int | None = None
    expires_at: datetime | None = None
    error: str | None = None
    """Why the last OAuth step failed, for the interface to show. Never a credential."""
    error_code: AuthErrorReason | None = None


class AuthStart(Record):
    authorization_url: str
    """Where to send the user: Civitai's consent page, or for a device sign-in its verification page."""
    expires_at: datetime
    flow: Flow = "browser"
    session_id: str
    user_code: str | None = None
    """The short code a device sign-in asks the user to confirm. Not a credential."""
    verification_uri: str | None = None


class LoginSession(Record):
    """One sign-in attempt as its initiator may see it. Never holds a code, verifier or token."""

    id: str
    flow: Flow
    status: SessionStatus
    expires_at: datetime
    user_code: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None
    error: str | None = None
    error_code: AuthErrorReason | None = None


class StartRequest(Record):
    return_to: str | None = Field(default=None, description="Path inside the app to return to; must be relative")
    flow: FlowChoice = "auto"


class MethodRequest(Record):
    method: AuthMethod
