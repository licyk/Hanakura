"""Civitai authentication: one provider of the credential that requests actually use.

Two methods exist side by side and neither ever replaces the other by itself:

- **manual**, a personal API token the user saves in settings or an environment variable. It
  keeps working with no OAuth application registered, and is the default.
- **oauth**, tokens obtained through Authorization Code with PKCE, kept in the credential store
  and refreshed automatically.

The method only changes when the user saves a manual token, completes an authorization, or asks
for a method explicitly. A failure, a disconnection or an expiry never switches method, because
the other method may belong to a different account.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from hanakura.core.auth.models import AuthStart, CivitaiAuthStatus, CredentialSource, OAuthAccount, OAuthState
from hanakura.core.auth.oauth_client import REFRESH_MARGIN_SECONDS, CivitaiOAuthClient, ReauthorizationRequired
from hanakura.core.auth.store import CredentialLock, CredentialStore, OAuthCredentials
from hanakura.core.auth.transactions import Transaction, TransactionStore
from hanakura.core.errors import AuthRequiredError, ConflictError, SourceError, ValidationError
from hanakura.core.settings import SettingsService
from hanakura.core.settings.models import AuthMethod

logger = logging.getLogger(__name__)

TOKEN_ENV_NAME = "HANAKURA_SOURCES__CIVITAI__TOKEN"
DEFAULT_RETURN_TO = "/#/settings"


class CivitaiAuthService:
    def __init__(
        self,
        settings: SettingsService,
        store: CredentialStore,
        client: Callable[[], httpx.Client],
        transactions: TransactionStore | None = None,
        lock: CredentialLock | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self._client = client
        self.transactions = transactions or TransactionStore()
        self._lock = lock or CredentialLock(settings.data_dir)
        self._memory_lock = threading.RLock()
        self._last_error: str | None = None
        # Set when the provider refuses the refresh token: the stored pair is then dead, and only
        # the user can fix it by connecting again. Kept so the account can still be named.
        self._needs_reauthorization = False
        # Raised by every disconnection, so a refresh that was already running cannot write the
        # credentials back afterwards.
        self._epoch = 0
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

    # -- configuration ------------------------------------------------------

    @property
    def config(self):  # type: ignore[no-untyped-def]
        return self.settings.settings.auth.civitai

    @property
    def oauth_configured(self) -> bool:
        return bool(self.config.oauth_client_id)

    def _oauth_client(self) -> CivitaiOAuthClient:
        client_id = self.config.oauth_client_id
        if not client_id:
            raise ValidationError("Civitai OAuth is not configured: set auth.civitai.oauth_client_id to the client id of a registered OAuth application.")
        return CivitaiOAuthClient(self._client, self.config.oauth_base_url, client_id)

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
            self._last_error = str(e)
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
            self._last_error = "The access token expired and there is no refresh token."
            return None
        try:
            return self._refresh(credentials).access_token
        except ReauthorizationRequired as e:
            self._needs_reauthorization = True
            self._last_error = str(e)
            return None
        except (AuthRequiredError, SourceError) as e:
            # A network failure or a rate limit must not throw the credentials away.
            logger.warning("Could not refresh the Civitai token: %s", e)
            self._last_error = str(e)
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
            refreshed = self._oauth_client().refresh(current.refresh_token)
            refreshed = refreshed.model_copy(update={"account": current.account, "scope": refreshed.scope or current.scope})
            if epoch != self._epoch:
                # Disconnected while this refresh was running: the new pair must not come back.
                logger.info("Discarding a refreshed Civitai token because the account was disconnected")
                raise ReauthorizationRequired("The Civitai connection was removed.")
            self.store.save(refreshed)
            self._last_error = None
            self._needs_reauthorization = False
            return refreshed

    # -- connecting ---------------------------------------------------------

    def start(self, redirect_uri: str, return_to: str | None = None) -> tuple[AuthStart, str]:
        """Begin an authorization. Returns the URL to open and the browser-binding secret."""
        client = self._oauth_client()
        transaction, secret = self.transactions.create(redirect_uri, return_to or DEFAULT_RETURN_TO, self.config.oauth_scope, client.client_id)
        url = client.authorization_url(redirect_uri, transaction.state, transaction.verifier, transaction.scope)
        self._last_error = None
        expires_at = datetime.fromtimestamp(datetime.now(tz=timezone.utc).timestamp() + self.transactions.ttl, tz=timezone.utc)
        return AuthStart(authorization_url=url, expires_at=expires_at), secret

    def complete(self, state: str, code: str, binding_secret: str | None) -> str:
        """Finish an authorization. Returns where to send the browser. Raises on refusal."""
        transaction = self.transactions.claim(state, binding_secret)
        if transaction is None:
            self._last_error = "The authorization could not be matched to the browser that started it, or it expired."
            raise ConflictError(self._last_error)
        if not code:
            self._last_error = "Civitai returned no authorization code."
            raise ValidationError(self._last_error)
        try:
            credentials = self._exchange(transaction, code)
        except (AuthRequiredError, SourceError, ValidationError) as e:
            self._last_error = str(e)
            raise
        self._save_connected(credentials)
        return transaction.return_to

    def _exchange(self, transaction: Transaction, code: str) -> OAuthCredentials:
        client = self._oauth_client()
        credentials = client.exchange(code, transaction.verifier, transaction.redirect_uri)
        try:
            account = client.userinfo(credentials.access_token)
        except (AuthRequiredError, SourceError) as e:
            # The identity is only shown in the interface; failing to read it is not fatal.
            logger.info("Could not read the Civitai account information: %s", e)
            account = OAuthAccount()
        return credentials.model_copy(update={"account": account, "scope": credentials.scope or transaction.scope})

    def _save_connected(self, credentials: OAuthCredentials) -> None:
        with self._memory_lock, self._lock:
            self.store.save(credentials)
            self._epoch += 1
            self._last_error = None
            self._needs_reauthorization = False
        # The method changes only once the credentials are safely stored.
        self.settings.update({"auth": {"civitai": {"method": "oauth"}}})

    def disconnect(self) -> CivitaiAuthStatus:
        """Revoke remotely where possible, then drop the local credentials. Keeps the manual token."""
        with self._memory_lock, self._lock:
            credentials = self.store.load()
            self._epoch += 1
            self._needs_reauthorization = False
            self.store.clear()
        message = None
        if credentials is not None and self.oauth_configured:
            token = credentials.refresh_token or credentials.access_token
            hint = "refresh_token" if credentials.refresh_token else "access_token"
            try:
                self._oauth_client().revoke(token, hint)
            except (AuthRequiredError, SourceError, ValidationError) as e:
                message = f"The local connection was removed, but Civitai may still list this authorization: {e}"
                logger.info("%s", message)
        # The method is left as the user chose it; nothing silently selects the manual token.
        self._last_error = message
        return self.status()

    def set_method(self, method: AuthMethod) -> CivitaiAuthStatus:
        """Choose the method explicitly, which is the only way to move between accounts."""
        if method == "oauth" and self.store.load() is None:
            raise ConflictError("Connect a Civitai account before selecting OAuth.")
        self.settings.update({"auth": {"civitai": {"method": method}}})
        return self.status()

    # -- status -------------------------------------------------------------

    def status(self) -> CivitaiAuthStatus:
        credentials = self.store.load()
        method, _token, source = self.effective()
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
            oauth_configured=self.oauth_configured,
            manual_token_configured=bool(self.manual_token()),
            env_override=self.env_override(),
            account=credentials.account if credentials else None,
            scope=credentials.scope if credentials else None,
            expires_at=credentials.expires_at if credentials else None,
            error=self._last_error,
        )

    @property
    def storage_description(self) -> str:
        return self.store.description
