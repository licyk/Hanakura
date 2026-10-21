"""Civitai authentication: one provider of the credential that requests actually use.

Two methods exist side by side and neither ever replaces the other by itself:

- **manual**, a personal API token the user saves in settings or an environment variable. It
  keeps working with no OAuth application registered, and is the default.
- **oauth**, tokens obtained through Authorization Code with PKCE or the device grant, kept in
  the credential store and refreshed automatically.

The method only changes when the user saves a manual token, completes an authorization, or asks
for a method explicitly. A failure, a disconnection or an expiry never switches method, because
the other method may belong to a different account.

A credential pair belongs to the client and authorization service that issued it: refreshing and
revoking go through them, whatever is configured now, so changing clients never sends an old
token to a new one.
"""

import logging
import threading
from collections.abc import Callable

import httpx

from hanakura.core.auth.clients import BUNDLED_PROFILES, ClientProfile, Flow, ResolvedClient, UnavailableReason, resolve_client, scope_granted
from hanakura.core.auth.device import MAX_DEVICE_SESSIONS, DevicePoller, Wait
from hanakura.core.auth.models import AuthErrorReason, AuthStart, CivitaiAuthStatus, CredentialSource, FlowChoice, LoginSession, OAuthAccount, OAuthState
from hanakura.core.auth.oauth_client import REFRESH_MARGIN_SECONDS, CivitaiOAuthClient, ReauthorizationRequired, reason_of
from hanakura.core.auth.store import CredentialLock, CredentialStore, OAuthCredentials
from hanakura.core.auth.transactions import Transaction, TransactionStore
from hanakura.core.errors import AuthRequiredError, ConflictError, HanakuraError, NotFoundError, SourceError, ValidationError
from hanakura.core.settings import SettingsService
from hanakura.core.settings.models import AuthMethod

logger = logging.getLogger(__name__)

TOKEN_ENV_NAME = "HANAKURA_SOURCES__CIVITAI__TOKEN"
DEFAULT_RETURN_TO = "/#/settings"

UNAVAILABLE_MESSAGES: dict[str, str] = {
    "disabled": "Civitai sign-in is turned off (auth.civitai.oauth_enabled).",
    "no_client": "Civitai sign-in needs an OAuth application: no bundled one has been verified yet, so set auth.civitai.oauth_client_id to the id of one registered with Civitai, or use an API token.",
    "issuer_mismatch": "The bundled sign-in only works with Civitai's own authorization service; set auth.civitai.oauth_client_id for another one.",
    "callback_unsupported": "Civitai cannot send the browser back to this address.",
}


class CivitaiAuthService:
    def __init__(
        self,
        settings: SettingsService,
        store: CredentialStore,
        client: Callable[[], httpx.Client],
        transactions: TransactionStore | None = None,
        lock: CredentialLock | None = None,
        profiles: tuple[ClientProfile, ...] = BUNDLED_PROFILES,
        device_wait: Wait | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._client = client
        self.transactions = transactions or TransactionStore()
        self.profiles = profiles
        self._lock = lock or CredentialLock(settings.data_dir)
        self._memory_lock = threading.RLock()
        self._last_error: str | None = None
        self._last_error_code: AuthErrorReason | None = None
        # Set when the provider refuses the refresh token: the stored pair is then dead, and only
        # the user can fix it by connecting again. Kept so the account can still be named.
        self._needs_reauthorization = False
        # Raised by every connection and disconnection, so a refresh that was already running
        # cannot write the old pair back afterwards.
        self._epoch = 0
        self.device = DevicePoller(self.transactions, self._oauth_client_for, self._commit_device, wait=device_wait)
        # Saving a manual token selects manual mode, however it was saved: the API, the command
        # line or an edited settings file.
        self._known_token = self.manual_token()
        settings.on_change(self._on_settings_changed)

    def _on_settings_changed(self, _settings: object) -> None:
        token = self.manual_token()
        previous, self._known_token = self._known_token, token
        if token and token != previous and self.config.method != "manual":
            logger.info("A Civitai API token was saved; using manual authentication")
            self.settings.update({"auth": {"civitai": {"method": "manual"}}})
        # A sign-in in flight runs as the client it started with; once that changes, it cannot finish.
        current = self.resolved()[0]
        snapshot = current.snapshot if current else None
        self.transactions.cancel_all("client_changed", "The sign-in settings changed while signing in. Start again.", keep=lambda t: t.client.snapshot == snapshot)

    def close(self) -> None:
        """Stop every sign-in still waiting; nothing they would have stored is written afterwards."""
        self.device.close()

    # -- configuration ------------------------------------------------------

    @property
    def config(self):  # type: ignore[no-untyped-def]
        return self.settings.settings.auth.civitai

    def resolved(self) -> tuple[ResolvedClient | None, UnavailableReason | None]:
        """The client a new authorization would run as, or why there is none."""
        return resolve_client(self.config, self.profiles)

    @property
    def oauth_configured(self) -> bool:
        return self.resolved()[0] is not None

    def require_client(self) -> ResolvedClient:
        client, reason = self.resolved()
        if client is None:
            raise ValidationError(UNAVAILABLE_MESSAGES[reason or "no_client"], {"reason": "client_unavailable", "unavailable": reason})
        return client

    def _oauth_client_for(self, client: ResolvedClient) -> CivitaiOAuthClient:
        return CivitaiOAuthClient(self._client, client.issuer, client.client_id)

    def _credential_client(self, credentials: OAuthCredentials) -> CivitaiOAuthClient:
        """The client that issued this pair; only it may refresh or revoke it."""
        if not credentials.client_id:
            raise ReauthorizationRequired("The stored Civitai connection does not say which application issued it; connect again.")
        # Every pair saved before the issuer was recorded came from the configured service, which
        # could only ever be changed by hand.
        issuer = credentials.issuer or self.config.oauth_base_url
        return CivitaiOAuthClient(self._client, issuer, credentials.client_id)

    def env_override(self) -> bool:
        """Whether an environment variable supplies the manual token, which takes precedence."""
        return TOKEN_ENV_NAME in self.settings.env_override_names()

    def manual_token(self) -> str | None:
        source = self.settings.settings.sources.get("civitai")
        return source.token if source else None

    # -- the credential in use ----------------------------------------------

    def effective(self) -> tuple[AuthMethod, str | None, CredentialSource]:
        """Return the method requests use, the token to send, and where it came from."""
        token = self.manual_token()
        if self.env_override() and token:
            # An environment override wins, and is reported as such.
            return "manual", token, "environment"
        if self.config.method == "oauth":
            access = self._valid_access_token()
            return "oauth", access, "oauth" if access else "none"
        return "manual", token, "settings" if token else "none"

    def headers(self) -> dict[str, str]:
        """The Authorization header for Civitai's own host, or nothing when anonymous."""
        _, token, _ = self.effective()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def on_unauthorized(self) -> bool:
        """Called once after a 401. Refreshes an OAuth token and reports whether to retry."""
        method, _, source = self.effective()
        if method != "oauth" or source != "oauth":
            return False
        credentials = self.store.load()
        if credentials is None or not credentials.refresh_token:
            return False
        try:
            self._refresh(credentials, force=True)
        except ReauthorizationRequired as e:
            self._needs_reauthorization = True
            self._fail(str(e), "expired")
            return False
        except (AuthRequiredError, SourceError) as e:
            logger.info("Refreshing the Civitai token after a 401 failed: %s", e)
            return False
        return True

    def _valid_access_token(self) -> str | None:
        credentials = self.store.load()
        if credentials is None:
            return None
        if not credentials.expires_within(REFRESH_MARGIN_SECONDS):
            return credentials.access_token
        if not credentials.refresh_token:
            self._fail("The access token expired and there is no refresh token.", "expired")
            return None
        try:
            return self._refresh(credentials).access_token
        except ReauthorizationRequired as e:
            self._needs_reauthorization = True
            self._fail(str(e), "expired")
            return None
        except (AuthRequiredError, SourceError) as e:
            # A network failure or a rate limit must not throw the credentials away.
            logger.warning("Could not refresh the Civitai token: %s", e)
            self._fail(str(e), "network")
            return credentials.access_token if not credentials.expires_within(0) else None

    def _refresh(self, credentials: OAuthCredentials, force: bool = False) -> OAuthCredentials:
        """Refresh the pair, once, even when several threads or processes ask at the same time."""
        with self._memory_lock, self._lock:
            epoch = self._epoch
            # Another thread or process may have refreshed while this one waited for the lock.
            current = self.store.load()
            if current is None:
                raise ReauthorizationRequired("The Civitai connection was removed.")
            if not force and not current.expires_within(REFRESH_MARGIN_SECONDS):
                return current
            if force and current.access_token != credentials.access_token:
                return current
            if not current.refresh_token:
                raise ReauthorizationRequired("There is no refresh token; connect Civitai again.")
            client = self._credential_client(current)
            refreshed = client.refresh(current.refresh_token)
            refreshed = refreshed.model_copy(update={"account": current.account, "scope": refreshed.scope or current.scope})
            if epoch != self._epoch:
                # Disconnected while this refresh was running: the new pair must not come back.
                logger.info("Discarding a refreshed Civitai token because the account was disconnected")
                raise ReauthorizationRequired("The Civitai connection was removed.")
            self.store.save(refreshed)
            self._last_error = self._last_error_code = None
            self._needs_reauthorization = False
            return refreshed

    # -- connecting ---------------------------------------------------------

    def choose_flow(self, requested: FlowChoice, browser_available: bool = True, browser_reason: str | None = None) -> Flow:
        """The flow to run: the one asked for, or for ``auto`` the best one this deployment supports."""
        client = self.require_client()
        usable = self._usable_flows(client, browser_available)
        if requested != "auto":
            if requested == "browser" and not browser_available and "browser" in client.flows:
                raise ValidationError(browser_reason or UNAVAILABLE_MESSAGES["callback_unsupported"], {"reason": "callback_unsupported"})
            if requested not in client.flows:
                raise ValidationError(f"The {client.name or 'configured'} OAuth application does not support {requested} sign-in.", {"reason": "client_unavailable"})
            return requested
        if not usable:
            message = browser_reason or UNAVAILABLE_MESSAGES["callback_unsupported"]
            raise ValidationError(f"{message} Use an API token or an OAuth application of your own that allows device sign-in.", {"reason": "callback_unsupported"})
        return usable[0]

    @staticmethod
    def _usable_flows(client: ResolvedClient, browser_available: bool) -> list[Flow]:
        order: tuple[Flow, ...] = ("browser", "device")
        return [f for f in order if f in client.flows and (f != "browser" or browser_available)]

    def start(self, redirect_uri: str | None = None, return_to: str | None = None, flow: Flow = "browser", binding_secret: str | None = None) -> tuple[AuthStart, str]:
        """Begin an authorization. Returns what the user must open and the browser-binding secret."""
        client = self.require_client()
        if flow == "device":
            return self._start_device(client, return_to, binding_secret)
        if not redirect_uri:
            raise ValidationError("A browser sign-in needs a callback address.", {"reason": "callback_unsupported"})
        transaction, secret = self.transactions.create_browser(client, redirect_uri, return_to or DEFAULT_RETURN_TO, binding_secret)
        url = self._oauth_client_for(client).authorization_url(redirect_uri, transaction.state or "", transaction.verifier or "", client.scope)
        self._last_error = self._last_error_code = None
        return AuthStart(authorization_url=url, expires_at=transaction.expires_at, flow="browser", session_id=transaction.id), secret

    def _start_device(self, client: ResolvedClient, return_to: str | None, binding_secret: str | None) -> tuple[AuthStart, str]:
        if len(self.transactions.active("device")) >= MAX_DEVICE_SESSIONS:
            raise ConflictError("Too many device sign-ins are waiting; finish or cancel one first.", {"reason": "failed"})
        grant = self._oauth_client_for(client).device_authorization(client.scope)
        transaction, secret = self.transactions.create_device(client, grant, return_to or DEFAULT_RETURN_TO, binding_secret)
        self.device.start(transaction)
        start = AuthStart(
            authorization_url=grant.verification_uri_complete or grant.verification_uri,
            expires_at=transaction.expires_at,
            flow="device",
            session_id=transaction.id,
            user_code=grant.user_code,
            verification_uri=grant.verification_uri,
        )
        return start, secret

    def complete(self, state: str, code: str, binding_secret: str | None, root_callback: bool = False) -> str:
        """Finish a browser authorization. Returns where to send the browser. Raises on refusal.

        ``root_callback`` says the browser came back through the bundled client's root path, which
        only a sign-in sent there may use.
        """
        transaction = self.transactions.claim(state, binding_secret)
        if transaction is None:
            self._fail("The authorization could not be matched to the browser that started it, or it expired.", "binding")
            raise ConflictError(self._last_error or "", {"reason": "binding"})
        try:
            if (transaction.client.callback_path is not None) != root_callback:
                raise ConflictError("The authorization came back to a different address than it was sent from.", {"reason": "binding"})
            if not code:
                raise ValidationError("Civitai returned no authorization code.", {"reason": "failed"})
            client = self._oauth_client_for(transaction.client)
            credentials = client.exchange(code, transaction.verifier or "", transaction.redirect_uri or "")
            self._commit(transaction, credentials)
        except HanakuraError as e:
            reason = reason_of(e)
            self.transactions.finish(transaction, "failed", reason, str(e))
            self._fail(str(e), reason)
            raise
        return transaction.return_to

    def deny(self, state: str, binding_secret: str | None, reason: AuthErrorReason, message: str) -> None:
        """Civitai sent the browser back with a refusal; end that browser's sign-in with the reason."""
        if self.transactions.deny(state, binding_secret, reason, message) is not None:
            self._fail(message, reason)

    def _commit_device(self, transaction: Transaction, credentials: OAuthCredentials) -> None:
        if not self.transactions.begin_exchange(transaction):
            self._discard(transaction.client, credentials)
            return
        try:
            self._commit(transaction, credentials)
        except HanakuraError as e:
            self.transactions.finish(transaction, "failed", reason_of(e), str(e))

    def _commit(self, transaction: Transaction, credentials: OAuthCredentials) -> None:
        """Store a new pair, if the session that asked for it is still wanted. Raises otherwise."""
        if not scope_granted(credentials.scope, transaction.scope):
            self._discard(transaction.client, credentials)
            granted = "nothing it reported" if credentials.scope is None else str(credentials.scope)
            raise AuthRequiredError(
                f"Civitai granted {granted} instead of the permissions asked for ({transaction.scope}): reading models and the account.", {"reason": "insufficient_scope"}
            )
        client = self._oauth_client_for(transaction.client)
        try:
            account = client.userinfo(credentials.access_token)
        except (AuthRequiredError, SourceError) as e:
            # The identity is only shown in the interface; failing to read it is not fatal.
            logger.info("Could not read the Civitai account information: %s", e)
            account = OAuthAccount()
        credentials = credentials.model_copy(update={"account": account})
        with self._memory_lock, self._lock:
            current = self.resolved()[0]
            # Past this point nothing can cancel the session: a disconnect waits for the lock and
            # then removes what this stores, as the later of the two actions.
            if current is None or current.snapshot != transaction.client.snapshot or not self.transactions.begin_commit(transaction):
                refused: AuthErrorReason = "cancelled" if transaction.status == "cancelled" else "client_changed"
                self._discard(transaction.client, credentials)
                raise ConflictError("The sign-in was cancelled, or its settings changed, before it finished.", {"reason": refused})
            try:
                self.store.save(credentials)
            except Exception as e:
                self.transactions.finish(transaction, "failed", "failed", f"The credentials could not be stored: {type(e).__name__}", committed=True)
                raise
            self._epoch += 1
            self._last_error = self._last_error_code = None
            self._needs_reauthorization = False
        # The method changes only once the credentials are safely stored, and the session reads as
        # connected only once the method has.
        self.settings.update({"auth": {"civitai": {"method": "oauth"}}})
        self.transactions.finish(transaction, "connected", committed=True)

    def _discard(self, client: ResolvedClient, credentials: OAuthCredentials) -> None:
        """Hand back a pair nobody will use. Best effort: it expires on its own anyway."""
        token = credentials.refresh_token or credentials.access_token
        try:
            self._oauth_client_for(client).revoke(token, "refresh_token" if credentials.refresh_token else "access_token")
        except HanakuraError as e:
            logger.info("Could not hand back an unused Civitai token: %s", e)

    def session(self, session_id: str, binding_secret: str | None) -> LoginSession:
        """A sign-in's state, for the browser that started it. Never contacts Civitai."""
        transaction = self.transactions.get(session_id, binding_secret)
        if transaction is None:
            raise NotFoundError("No such sign-in for this browser.")
        return transaction.view()

    def cancel_session(self, session_id: str, binding_secret: str | None) -> LoginSession:
        transaction = self.transactions.cancel(session_id, binding_secret)
        if transaction is None:
            raise NotFoundError("No such sign-in for this browser.")
        return transaction.view()

    def wait_session(self, session_id: str, binding_secret: str | None, timeout: float | None = None) -> LoginSession:
        """Wait until a sign-in ends, or the timeout passes, and return its state."""
        transaction = self.transactions.get(session_id, binding_secret)
        if transaction is None:
            raise NotFoundError("No such sign-in for this browser.")
        transaction.done.wait(timeout)
        return transaction.view()

    def disconnect(self) -> CivitaiAuthStatus:
        """Cancel sign-ins in flight, drop the local credentials, then ask Civitai to revoke them. Keeps the manual token."""
        self.transactions.cancel_all("cancelled", "The account was disconnected while signing in.")
        with self._memory_lock, self._lock:
            credentials = self.store.load()
            self._epoch += 1
            self._needs_reauthorization = False
            self.store.clear()
        message = None
        if credentials is not None:
            token = credentials.refresh_token or credentials.access_token
            hint = "refresh_token" if credentials.refresh_token else "access_token"
            try:
                self._credential_client(credentials).revoke(token, hint)
            except HanakuraError as e:
                message = f"The local connection was removed, but Civitai may still list this authorization: {e}"
                logger.info("%s", message)
        # The method is left as the user chose it; nothing silently selects the manual token.
        self._last_error = message
        self._last_error_code = "network" if message else None
        return self.status()

    def set_method(self, method: AuthMethod) -> CivitaiAuthStatus:
        """Choose the method explicitly, which is the only way to move between accounts."""
        if method == "oauth" and self.store.load() is None:
            raise ConflictError("Connect a Civitai account before selecting OAuth.")
        self.settings.update({"auth": {"civitai": {"method": method}}})
        return self.status()

    def _fail(self, message: str, code: AuthErrorReason) -> None:
        self._last_error = message
        self._last_error_code = code

    # -- status -------------------------------------------------------------

    def status(self, browser_available: bool = True, browser_reason: UnavailableReason | None = None) -> CivitaiAuthStatus:
        """The account's state. ``browser_available`` is the deployment's answer to whether Civitai can call back."""
        credentials = self.store.load()
        method, _token, source = self.effective()
        client, reason = self.resolved()
        flows: list[Flow] = []
        if client is not None:
            flows = self._usable_flows(client, browser_available)
            if not flows:
                reason = browser_reason or "callback_unsupported"
        state: OAuthState = "not_connected"
        if self.transactions.pending:
            state = "pending"
        if credentials is not None:
            state = "connected"
            if self._needs_reauthorization or (credentials.expires_within(0) and not credentials.refresh_token):
                state = "reauthorization_required"
        elif self.config.method == "oauth":
            state = "reauthorization_required"
        return CivitaiAuthStatus(
            method=self.config.method,
            effective_method=method,
            credential_source=source,
            oauth_state=state,
            oauth_enabled=self.config.oauth_enabled,
            oauth_configured=client is not None,
            client_source=client.source if client else None,
            client_name=client.name if client else None,
            flows=flows,
            unavailable_reason=reason,
            manual_token_configured=bool(self.manual_token()),
            env_override=self.env_override(),
            account=credentials.account if credentials else None,
            scope=credentials.scope if credentials else None,
            expires_at=credentials.expires_at if credentials else None,
            error=self._last_error,
            error_code=self._last_error_code,
        )

    @property
    def storage_description(self) -> str:
        return self.store.description
