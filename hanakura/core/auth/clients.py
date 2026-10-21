"""Which OAuth client an authorization runs as: one the user or host registered, or a bundled one.

An explicit ``auth.civitai.oauth_client_id`` always wins and is never replaced by a bundled client.
Without one, the first bundled profile marked ``verified`` is used. ``verified`` means a real
sign-in with the configuration Hanakura sends — this client, its callback, the default scope —
was seen to succeed; it promises no particular permission, grant or token lifecycle, and the
evidence and its limits are in AGENTS.md §15. With no verified profile, the interface asks for a
client id.
"""

from dataclasses import dataclass
from typing import Literal

from hanakura.core.settings.models import CIVITAI_AUTH_BASE_URL, CivitaiAuthSettings

Flow = Literal["browser", "device"]
ClientSource = Literal["bundled", "custom"]
# Why no authorization can start. "callback_unsupported" is decided by the deployment, not here.
UnavailableReason = Literal["disabled", "no_client", "issuer_mismatch", "callback_unsupported"]

# UserRead, which Civitai grants on every token whatever was asked for.
USER_READ = 1


@dataclass(frozen=True)
class ClientProfile:
    """A public client that ships with Hanakura. Its id identifies an application, it is no secret."""

    key: str
    client_id: str
    name: str
    """The application name Civitai shows on its consent screen."""
    flows: frozenset[Flow]
    callback_path: str | None
    """The exact loopback callback path the client is registered with; None for Hanakura's own."""
    verified: bool
    evidence: str


BUNDLED_PROFILES: tuple[ClientProfile, ...] = (
    # Civitai's own ComfyUI nodes. Its source (civitai-comfy-nodes@1bcb195) registers loopback
    # callbacks at /civitai/callback, and the authorization service matches a loopback redirect on
    # any port. Its device grant is refused, and so is scope 5 (both checked 2026-10-21); a browser
    # sign-in with scope 1 succeeded and a download worked afterwards, as reported by the user.
    ClientProfile(
        key="civitai-comfy-nodes",
        client_id="2d61872c-9aa9-4dbc-93c3-899c222842c1",
        name="Civitai ComfyNodes",
        flows=frozenset({"browser"}),
        callback_path="/civitai/callback",
        verified=True,
        evidence="user-reported 2026-10-21: a scope 1 sign-in and a download succeeded (AGENTS.md section 15)",
    ),
)


@dataclass(frozen=True)
class ResolvedClient:
    """The client an authorization runs as, with everything that must not change underneath it."""

    client_id: str
    issuer: str
    scope: int
    source: ClientSource
    name: str | None
    flows: frozenset[Flow]
    callback_path: str | None

    @property
    def snapshot(self) -> tuple[str, str, int]:
        """What a pending authorization is bound to; a change cancels it."""
        return (self.client_id, self.issuer, self.scope)


def default_profile(profiles: tuple[ClientProfile, ...] = BUNDLED_PROFILES) -> ClientProfile | None:
    return next((p for p in profiles if p.verified), None)


def resolve_client(config: CivitaiAuthSettings, profiles: tuple[ClientProfile, ...] = BUNDLED_PROFILES) -> tuple[ResolvedClient | None, UnavailableReason | None]:
    """Return the effective client, or None and why there is none."""
    if not config.oauth_enabled:
        return None, "disabled"
    issuer = config.oauth_base_url.rstrip("/")
    if config.oauth_client_id:
        # A custom application is registered with Hanakura's own callback; whether it also has the
        # device grant only Civitai knows, and it says so plainly when it does not.
        return ResolvedClient(config.oauth_client_id, issuer, config.oauth_scope, "custom", None, frozenset({"browser", "device"}), None), None
    profile = default_profile(profiles)
    if profile is None:
        return None, "no_client"
    if issuer != CIVITAI_AUTH_BASE_URL:
        # A bundled client is registered with Civitai's own service and means nothing elsewhere.
        return None, "issuer_mismatch"
    return ResolvedClient(profile.client_id, issuer, config.oauth_scope, "bundled", profile.name, profile.flows, profile.callback_path), None


def scope_granted(granted: int | None, requested: int) -> bool:
    """Whether every requested bit was granted. An unknown grant is not taken as the request."""
    return granted is not None and (granted & requested) == requested
