"""Civitai authentication: OAuth with PKCE, and the manual token that must keep working."""

import base64
import hashlib
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from hanakura.core.auth import store as store_module
from hanakura.core.auth.clients import ClientProfile, ResolvedClient, default_profile, resolve_client
from hanakura.core.auth.device import MAX_DEVICE_SESSIONS
from hanakura.core.auth.oauth_client import REFRESH_MARGIN_SECONDS, CivitaiOAuthClient, ReauthorizationRequired, challenge_for, make_verifier, parse_scope
from hanakura.core.auth.store import FileCredentialStore, KeyringCredentialStore, OAuthCredentials, open_store
from hanakura.core.auth.transactions import TransactionStore
from hanakura.core.context import build_services
from hanakura.core.errors import AuthRequiredError, ConflictError, NotFoundError, SourceError, ValidationError
from hanakura.core.settings import SettingsService
from hanakura.core.settings.models import CivitaiAuthSettings

CLIENT_ID = "hanakura-test"
REDIRECT = "http://127.0.0.1:7865/api/v1/auth/civitai/callback"
CUSTOM = ResolvedClient(CLIENT_ID, "https://auth.civitai.com", 5, "custom", None, frozenset({"browser", "device"}), None)


class Provider:
    """A stand-in for auth.civitai.com that records what it was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.tokens = 0
        self.revoked: list[str] = []
        self.refresh_fails: Exception | httpx.Response | None = None
        self.expires_in = 3600
        self.last_refresh_token: str | None = None
        self.scope: object = "5"
        self.device: dict[str, object] = {
            "device_code": "the-device-code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://auth.civitai.com/login/oauth/device",
            "verification_uri_complete": "https://auth.civitai.com/login/oauth/device?code=ABCD-EFGH",
            "expires_in": 900,
            "interval": 5,
        }
        # What each device-token poll answers, in order; "ok" issues tokens. Then it stays pending.
        self.polls: list[object] = []
        self.on_poll = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth/oauth/device":
            return httpx.Response(200, json=self.device)
        if path == "/api/auth/oauth/device-token":
            if self.on_poll:
                self.on_poll()
            answer = self.polls.pop(0) if self.polls else httpx.Response(400, json={"error": "authorization_pending"})
            if isinstance(answer, Exception):
                raise answer
            if answer != "ok":
                return answer  # type: ignore[return-value]
        if path == "/api/auth/oauth/token":
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["refresh_token"]:
                self.last_refresh_token = form["refresh_token"][0]
                if isinstance(self.refresh_fails, httpx.Response):
                    return self.refresh_fails
                if self.refresh_fails is not None:
                    raise self.refresh_fails
        if path in ("/api/auth/oauth/token", "/api/auth/oauth/device-token"):
            self.tokens += 1
            n = self.tokens
            body = {"access_token": f"access-{n}", "refresh_token": f"refresh-{n}", "expires_in": self.expires_in, "scope": self.scope, "token_type": "Bearer"}
            if self.scope is None:
                del body["scope"]
            return httpx.Response(200, json=body)
        if path == "/api/auth/oauth/userinfo":
            return httpx.Response(200, json={"sub": "42", "username": "someone"})
        if path == "/api/auth/oauth/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def provider() -> Provider:
    return Provider()


@pytest.fixture
def services(tmp_path, provider):
    s = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(provider))
    s.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID}}})
    yield s
    s.close()


def connect(services, provider) -> None:
    """Run one authorization from start to finish."""
    start, secret = services.auth.start(REDIRECT)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    services.auth.complete(state, "the-code", secret)


# -- PKCE ---------------------------------------------------------------------


def test_pkce_challenge_is_s256_without_padding():
    verifier = make_verifier()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge_for(verifier) == expected
    assert "=" not in challenge_for(verifier)


def test_authorization_url_carries_pkce_and_scope(services):
    start, _secret = services.auth.start(REDIRECT, "/#/settings")
    query = parse_qs(urlsplit(start.authorization_url).query)
    assert urlsplit(start.authorization_url).netloc == "auth.civitai.com"
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"] and query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT] and query["scope"] == ["5"]
    assert "client_secret" not in query


# -- the flow -----------------------------------------------------------------


def test_connect_stores_tokens_and_selects_oauth(services, provider):
    connect(services, provider)
    status = services.auth.status()
    assert (status.oauth_state, status.method, status.effective_method) == ("connected", "oauth", "oauth")
    assert status.account.username == "someone"
    assert services.auth.headers() == {"Authorization": "Bearer access-1"}
    # The exchange sent the verifier, and never a secret.
    form = parse_qs(provider.requests[0].content.decode())
    assert form["code_verifier"][0] and form["grant_type"] == ["authorization_code"]
    assert "client_secret" not in form


def test_tokens_never_appear_in_settings(services, provider):
    connect(services, provider)
    dumped = services.settings.view().model_dump_json()
    assert "access-1" not in dumped and "refresh-1" not in dumped
    assert "access-1" not in services.settings.path.read_text()


@pytest.mark.parametrize("wrong", ["other-state", ""])
def test_callback_with_an_unknown_state_is_refused(services, wrong):
    _start, secret = services.auth.start(REDIRECT)
    with pytest.raises(ConflictError):
        services.auth.complete(wrong, "code", secret)


def test_callback_needs_the_browser_that_started_it(services):
    start, _secret = services.auth.start(REDIRECT)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    with pytest.raises(ConflictError):
        services.auth.complete(state, "code", "a-different-browser")
    with pytest.raises(ConflictError):
        services.auth.complete(state, "code", None)


def test_a_transaction_is_single_use(services, provider):
    start, secret = services.auth.start(REDIRECT)
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    services.auth.complete(state, "code", secret)
    with pytest.raises(ConflictError):
        services.auth.complete(state, "code", secret)


def test_transactions_expire():
    store = TransactionStore(ttl=-1)
    transaction, secret = store.create_browser(CUSTOM, REDIRECT, "/")
    assert store.claim(transaction.state, secret) is None
    assert transaction.status == "expired"


def test_oauth_without_a_client_id_is_a_clear_error(tmp_path, provider):
    s = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        with pytest.raises(ValidationError, match="oauth_client_id"):
            s.auth.start(REDIRECT)
        assert s.auth.status().oauth_configured is False
    finally:
        s.close()


# -- refresh ------------------------------------------------------------------


def test_token_is_refreshed_just_before_it_expires(services, provider):
    provider.expires_in = int(REFRESH_MARGIN_SECONDS) - 10
    connect(services, provider)
    assert services.auth.headers() == {"Authorization": "Bearer access-2"}
    assert provider.last_refresh_token == "refresh-1"
    # The rotated pair is stored whole, so the next refresh uses the new refresh token.
    assert services.auth.store.load().refresh_token == "refresh-2"


def test_concurrent_requests_refresh_once(services, provider):
    provider.expires_in = int(REFRESH_MARGIN_SECONDS) - 10
    connect(services, provider)
    provider.expires_in = 3600
    results: list[dict[str, str]] = []
    threads = [threading.Thread(target=lambda: results.append(services.auth.headers())) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    refreshes = [r for r in provider.requests if r.url.path.endswith("/token") and b"refresh_token" in r.content]
    assert len(refreshes) == 1
    assert {tuple(r.items()) for r in results} == {(("Authorization", "Bearer access-2"),)}


def test_a_refused_refresh_asks_for_reauthorization(services, provider):
    provider.expires_in = 10
    connect(services, provider)
    provider.refresh_fails = httpx.Response(400, json={"error": "invalid_grant"})
    assert services.auth.headers() == {}
    status = services.auth.status()
    assert status.oauth_state == "reauthorization_required" and status.method == "oauth"
    # Nothing silently fell back to another account.
    assert status.effective_method == "oauth" and status.credential_source == "none"


def test_a_network_failure_keeps_the_credentials(services, provider):
    connect(services, provider)
    services.auth.store.save(services.auth.store.load().model_copy(update={"expires_at": datetime.now(tz=timezone.utc) + timedelta(seconds=30)}))
    provider.refresh_fails = httpx.ConnectError("no network")
    assert services.auth.headers() == {"Authorization": "Bearer access-1"}
    assert services.auth.store.load() is not None


def test_retry_once_after_a_401(services, provider):
    connect(services, provider)
    assert services.auth.on_unauthorized() is True
    assert services.auth.headers() == {"Authorization": "Bearer access-2"}
    provider.refresh_fails = httpx.Response(400, json={"error": "invalid_grant"})
    assert services.auth.on_unauthorized() is False


# -- disconnecting ------------------------------------------------------------


def test_disconnect_revokes_and_keeps_the_manual_token(services, provider):
    services.settings.update({"sources": {"civitai": {"token": "manual-token"}}})
    connect(services, provider)
    status = services.auth.disconnect()
    assert provider.revoked == ["refresh-1"]
    assert services.auth.store.load() is None
    assert status.oauth_state == "reauthorization_required"
    # The manual token is untouched, and nothing switched to it by itself.
    assert services.settings.settings.sources["civitai"].token == "manual-token"
    assert status.method == "oauth" and services.auth.headers() == {}


def test_disconnect_reports_a_failed_revocation(services, provider):
    connect(services, provider)
    provider.refresh_fails = None

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/revoke"):
            return httpx.Response(500)
        return provider(request)

    services.http._transport = httpx.MockTransport(failing)
    services.http.close()
    status = services.auth.disconnect()
    assert services.auth.store.load() is None
    assert status.error and "may still list" in status.error


def test_a_refresh_in_flight_cannot_restore_a_disconnected_account(services, provider, monkeypatch):
    provider.expires_in = 10
    connect(services, provider)
    credentials = services.auth.store.load()

    original_refresh = services.auth._credential_client(credentials).refresh

    def refresh_then_disconnect(token: str):
        result = original_refresh(token)
        services.auth._epoch += 1
        services.auth.store.clear()
        return result

    monkeypatch.setattr("hanakura.core.auth.oauth_client.CivitaiOAuthClient.refresh", staticmethod(refresh_then_disconnect))
    with pytest.raises(ReauthorizationRequired):
        services.auth._refresh(credentials, force=True)
    assert services.auth.store.load() is None


# -- the two methods side by side ---------------------------------------------


def test_manual_token_works_without_any_oauth(tmp_path, provider):
    s = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        s.settings.update({"sources": {"civitai": {"token": "manual-token"}}})
        assert s.auth.headers() == {"Authorization": "Bearer manual-token"}
        status = s.auth.status()
        assert (status.method, status.effective_method, status.credential_source) == ("manual", "manual", "settings")
        assert status.oauth_configured is False
    finally:
        s.close()


def test_saving_a_manual_token_selects_manual(services, provider):
    connect(services, provider)
    assert services.auth.status().method == "oauth"
    services.settings.update({"sources": {"civitai": {"token": "manual-token"}}})
    status = services.auth.status()
    assert (status.method, status.effective_method) == ("manual", "manual")
    assert services.auth.headers() == {"Authorization": "Bearer manual-token"}
    # The OAuth credentials are still there, ready to be selected again.
    assert services.auth.store.load() is not None
    assert services.auth.set_method("oauth").effective_method == "oauth"


def test_clearing_the_manual_token_does_not_select_oauth(services, provider):
    connect(services, provider)
    services.settings.update({"sources": {"civitai": {"token": "manual-token"}}})
    services.settings.update({"sources": {"civitai": {"token": None}}})
    status = services.auth.status()
    assert status.method == "manual" and status.credential_source == "none"
    assert services.auth.headers() == {}


def test_selecting_oauth_without_a_connection_is_refused(services):
    with pytest.raises(ConflictError):
        services.auth.set_method("oauth")


def test_an_environment_override_wins_and_is_reported(tmp_path, provider):
    env = {"HANAKURA_SOURCES__CIVITAI__TOKEN": "from-env"}
    s = build_services(data_dir=tmp_path / "d", environ=env, transport=httpx.MockTransport(provider))
    try:
        s.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID}}})
        connect(s, provider)
        status = s.auth.status()
        assert s.auth.headers() == {"Authorization": "Bearer from-env"}
        assert (status.method, status.effective_method, status.credential_source) == ("oauth", "manual", "environment")
        assert status.env_override is True
    finally:
        s.close()


def test_the_adapter_uses_the_effective_credential(services, provider):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "civitai.com":
            calls.append(request)
            return httpx.Response(200, json={"items": [], "metadata": {}})
        return provider(request)

    services.http._transport = httpx.MockTransport(handler)
    services.http.close()
    from hanakura.core.sources.models import SearchQuery

    services.sources.search("civitai", SearchQuery(query="a"))
    assert "Authorization" not in calls[-1].headers
    connect(services, provider)
    services.sources.search("civitai", SearchQuery(query="b"))
    assert calls[-1].headers["Authorization"] == "Bearer access-1"


# -- storage ------------------------------------------------------------------


def test_file_store_is_private(tmp_path):
    store = FileCredentialStore(tmp_path)
    store.save(OAuthCredentials(access_token="a", refresh_token="r"))
    assert store.load().access_token == "a"
    assert oct(store.path.stat().st_mode)[-3:] == "600"
    assert oct(store.directory.stat().st_mode)[-3:] == "700"
    store.clear()
    assert store.load() is None


def test_keyring_is_used_when_it_works(tmp_path, monkeypatch):
    class FakeKeyring:
        def __init__(self) -> None:
            self.values: dict[tuple[str, str], str] = {}

        def get_password(self, service, user):
            return self.values.get((service, user))

        def set_password(self, service, user, value):
            self.values[(service, user)] = value

        def delete_password(self, service, user):
            del self.values[(service, user)]

    fake = FakeKeyring()
    monkeypatch.setattr(store_module, "_system_keyring", lambda: fake)
    store = open_store(tmp_path)
    assert isinstance(store, KeyringCredentialStore)
    store.save(OAuthCredentials(access_token="a"))
    assert store.load().access_token == "a"
    assert not (tmp_path / "credentials").exists()
    store.clear()
    assert store.load() is None


def test_a_broken_keyring_falls_back_to_a_file(tmp_path, monkeypatch):
    class BrokenKeyring:
        def get_password(self, *_args):
            raise RuntimeError("no secret service")

    monkeypatch.setattr(store_module, "_system_keyring", lambda: BrokenKeyring())
    assert isinstance(open_store(tmp_path), FileCredentialStore)
    monkeypatch.setattr(store_module, "_system_keyring", lambda: None)
    assert isinstance(open_store(tmp_path), FileCredentialStore)


def test_keyring_never_searches_its_backends_off_macos(monkeypatch):
    """keyring's search imports its macOS backend, whose ctypes lookup runs ``ld -o /dev/null``; GNU ld deletes that
    file when the link fails, so run as root it deleted /dev/null."""
    pytest.importorskip("keyring")
    import keyring
    import keyring.backend
    import keyring.core

    def searched(*_args, **_kwargs):
        raise AssertionError("keyring searched every backend")

    monkeypatch.setattr(keyring.backend, "get_all_keyring", searched)
    monkeypatch.setattr(keyring, "get_keyring", searched)
    monkeypatch.setattr(store_module.sys, "platform", "linux")
    monkeypatch.delenv("PYTHON_KEYRING_BACKEND", raising=False)
    monkeypatch.setattr(keyring.core, "load_config", lambda: None)
    store_module._system_keyring()  # whatever this machine has, found without the search
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    assert type(store_module._system_keyring()).__module__ == "keyring.backends.null"  # the user's choice wins


def test_credentials_survive_a_restart(tmp_path, provider):
    first = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        first.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID, "use_keyring": False}}})
        connect(first, provider)
    finally:
        first.close()
    second = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        status = second.auth.status()
        assert status.oauth_state == "connected" and status.method == "oauth"
        assert second.auth.headers() == {"Authorization": "Bearer access-1"}
    finally:
        second.close()


def test_the_settings_file_never_holds_a_token(tmp_path, provider):
    s = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        s.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID, "use_keyring": False}}})
        connect(s, provider)
        text = SettingsService(data_dir=tmp_path / "d", environ={}).path.read_text()
        assert "access-1" not in text and "refresh-1" not in text
    finally:
        s.close()


# -- which client ---------------------------------------------------------------

VERIFIED = ClientProfile("test-bundled", "bundled-id", "Bundled Test App", frozenset({"browser"}), "/civitai/callback", True, "test")
UNVERIFIED = ClientProfile("candidate", "candidate-id", "Candidate", frozenset({"browser"}), "/civitai/callback", False, "test")


def test_no_bundled_client_is_offered_until_one_is_verified():
    assert default_profile() is None, "a bundled client may only be enabled once plan.md records its live verification"
    client, reason = resolve_client(CivitaiAuthSettings(), (UNVERIFIED,))
    assert client is None and reason == "no_client"


def test_client_resolution_precedence():
    bundled, _ = resolve_client(CivitaiAuthSettings(), (UNVERIFIED, VERIFIED))
    assert bundled is not None and (bundled.source, bundled.client_id, bundled.name) == ("bundled", "bundled-id", "Bundled Test App")
    # An explicit client id is never replaced by a bundled one.
    custom, _ = resolve_client(CivitaiAuthSettings(oauth_client_id="mine"), (VERIFIED,))
    assert custom is not None and (custom.source, custom.client_id, custom.callback_path) == ("custom", "mine", None)
    assert resolve_client(CivitaiAuthSettings(oauth_enabled=False, oauth_client_id="mine"), (VERIFIED,)) == (None, "disabled")
    assert resolve_client(CivitaiAuthSettings(oauth_base_url="https://auth.example"), (VERIFIED,)) == (None, "issuer_mismatch")
    # Defaults never widen what is asked for.
    assert bundled.scope == 5


def test_unconfigured_status_explains_why(tmp_path, provider):
    s = build_services(data_dir=tmp_path / "d", environ={}, transport=httpx.MockTransport(provider))
    try:
        status = s.auth.status()
        assert (status.oauth_configured, status.unavailable_reason, status.flows, status.client_source) == (False, "no_client", [], None)
        s.settings.update({"auth": {"civitai": {"oauth_enabled": False, "oauth_client_id": CLIENT_ID}}})
        assert s.auth.status().unavailable_reason == "disabled"
        with pytest.raises(ValidationError):
            s.auth.start(REDIRECT)
    finally:
        s.close()


def test_turning_oauth_off_keeps_the_connection(services, provider):
    connect(services, provider)
    services.settings.update({"auth": {"civitai": {"oauth_enabled": False}}})
    status = services.auth.status()
    assert (status.oauth_state, status.method, status.oauth_configured) == ("connected", "oauth", False)
    assert services.auth.headers() == {"Authorization": "Bearer access-1"}


@pytest.mark.parametrize(("value", "expected"), [(5, 5), ("5", 5), (["5"], 5), ([5], 5), (None, None), ("", None), ("five", None), (["1", "4"], None), (True, None), (-1, None)])
def test_granted_scope_is_parsed_in_every_form_civitai_sends(value, expected):
    assert parse_scope(value) == expected


# -- what was granted -------------------------------------------------------------


@pytest.mark.parametrize("granted", ["1", None])
def test_a_connection_without_the_permissions_asked_for_is_refused(services, provider, granted):
    provider.scope = granted
    with pytest.raises(AuthRequiredError) as raised:
        connect(services, provider)
    assert raised.value.detail["reason"] == "insufficient_scope"
    status = services.auth.status()
    assert (status.oauth_state, status.method, status.error_code) == ("not_connected", "manual", "insufficient_scope")
    assert services.auth.store.load() is None
    # The unusable pair was handed back rather than kept.
    assert provider.revoked == ["refresh-1"]


def test_a_list_scope_is_accepted(services, provider):
    provider.scope = ["5"]
    connect(services, provider)
    assert services.auth.status().scope == 5


# -- whose credentials ------------------------------------------------------------


def test_refresh_and_revoke_use_the_client_that_issued_the_pair(services, provider):
    provider.expires_in = 10
    connect(services, provider)
    assert services.auth.store.load().issuer == "https://auth.civitai.com"
    services.settings.update({"auth": {"civitai": {"oauth_client_id": "another-app"}}})
    services.auth.headers()  # refreshes
    refresh = [r for r in provider.requests if b"grant_type=refresh_token" in r.content][-1]
    assert parse_qs(refresh.content.decode())["client_id"] == [CLIENT_ID]
    services.auth.disconnect()
    revoke = [r for r in provider.requests if r.url.path.endswith("/revoke")][-1]
    assert parse_qs(revoke.content.decode())["client_id"] == [CLIENT_ID]


def test_an_old_record_without_an_issuer_still_refreshes(services, provider):
    provider.expires_in = 10
    connect(services, provider)
    old = services.auth.store.load().model_copy(update={"issuer": None})
    services.auth.store.save(old)
    assert services.auth.headers() == {"Authorization": "Bearer access-2"}


def test_a_record_that_names_no_client_needs_a_new_authorization(services, provider):
    provider.expires_in = 10
    connect(services, provider)
    services.auth.store.save(services.auth.store.load().model_copy(update={"client_id": None}))
    # Its refresh could only go to a guessed client, so it is not attempted.
    assert services.auth.headers() == {}
    assert services.auth.status().oauth_state == "reauthorization_required"
    assert not [r for r in provider.requests if b"grant_type=refresh_token" in r.content]


# -- sessions -------------------------------------------------------------------


def _state(start) -> str:
    return parse_qs(urlsplit(start.authorization_url).query)["state"][0]


def test_a_changed_client_cancels_an_authorization_in_flight(services, provider):
    start, secret = services.auth.start(REDIRECT)
    services.settings.update({"auth": {"civitai": {"oauth_client_id": "another-app"}}})
    assert services.auth.session(start.session_id, secret).error_code == "client_changed"
    with pytest.raises(ConflictError):
        services.auth.complete(_state(start), "code", secret)
    # The old code was never exchanged through the new client.
    assert not [r for r in provider.requests if r.url.path.endswith("/token")]


def test_a_cancelled_authorization_cannot_finish(services, provider):
    start, secret = services.auth.start(REDIRECT)
    assert services.auth.cancel_session(start.session_id, secret).status == "cancelled"
    assert services.auth.cancel_session(start.session_id, secret).status == "cancelled"  # idempotent
    with pytest.raises(ConflictError):
        services.auth.complete(_state(start), "code", secret)
    assert services.auth.store.load() is None


def test_a_session_is_only_visible_to_its_browser(services):
    start, secret = services.auth.start(REDIRECT)
    assert services.auth.session(start.session_id, secret).status == "pending"
    for other in (None, "x" * 43):
        with pytest.raises(NotFoundError):
            services.auth.session(start.session_id, other)
        with pytest.raises(NotFoundError):
            services.auth.cancel_session(start.session_id, other)


def test_two_tabs_share_one_binding(services, provider):
    first, secret = services.auth.start(REDIRECT)
    second, same = services.auth.start(REDIRECT, binding_secret=secret)
    assert same == secret
    services.auth.complete(_state(first), "code", secret)
    # The second tab's sign-in still finishes; the first did not take its binding away.
    services.auth.complete(_state(second), "code", secret)
    assert services.auth.store.load().access_token == "access-2"


def test_a_disconnect_during_the_exchange_wins(services, provider, monkeypatch):
    start, secret = services.auth.start(REDIRECT)
    original = CivitaiOAuthClient.exchange

    def exchange_then_disconnect(self, *args):
        result = original(self, *args)
        services.auth.disconnect()
        return result

    monkeypatch.setattr(CivitaiOAuthClient, "exchange", exchange_then_disconnect)
    with pytest.raises(ConflictError):
        services.auth.complete(_state(start), "code", secret)
    assert services.auth.store.load() is None
    assert services.auth.status().method == "manual"
    assert "refresh-1" in provider.revoked


def test_a_failed_authorization_keeps_the_previous_account(services, provider):
    connect(services, provider)
    provider.scope = "1"
    with pytest.raises(AuthRequiredError):
        connect(services, provider)
    assert services.auth.store.load().access_token == "access-1"
    assert services.auth.status().method == "oauth"


# -- device sign-in -------------------------------------------------------------


class FakeClock:
    """Time that only moves when the poller waits, so no test sleeps for real."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def wait(self, event: threading.Event, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now += seconds
        return event.is_set()


@pytest.fixture
def clock(services) -> FakeClock:
    fake = FakeClock()
    services.auth.transactions.clock = fake
    services.auth.device._wait = fake.wait
    return fake


def _device(services, binding: str | None = None):
    start, secret = services.auth.start(flow="device", binding_secret=binding)
    return start, secret, services.auth.wait_session(start.session_id, secret, timeout=5)


def test_device_sign_in_connects(services, provider, clock):
    provider.polls = [httpx.Response(400, json={"error": "authorization_pending"}), "ok"]
    start, _secret, result = _device(services)
    assert (start.flow, start.user_code, start.verification_uri) == ("device", "ABCD-EFGH", "https://auth.civitai.com/login/oauth/device")
    assert start.authorization_url.endswith("?code=ABCD-EFGH")
    assert result.status == "connected"
    status = services.auth.status()
    assert (status.oauth_state, status.method, status.account.username) == ("connected", "oauth", "someone")
    assert clock.waits == [5, 5]
    poll = next(r for r in provider.requests if r.url.path.endswith("/device-token"))
    assert parse_qs(poll.content.decode()) == {"grant_type": ["urn:ietf:params:oauth:grant-type:device_code"], "device_code": ["the-device-code"], "client_id": [CLIENT_ID]}
    # The device code never leaves the server.
    assert "the-device-code" not in start.model_dump_json() + result.model_dump_json()


def test_device_polling_slows_down_when_asked(services, provider, clock):
    provider.polls = [httpx.Response(429, json={"error": "rate_limited"}), httpx.Response(400, json={"error": "slow_down"}), "ok"]
    _start, _secret, result = _device(services)
    assert result.status == "connected"
    assert clock.waits == [5, 10, 15]


@pytest.mark.parametrize(("error", "status"), [("access_denied", "denied"), ("expired_token", "expired"), ("invalid_grant", "failed")])
def test_device_sign_in_ends_on_a_refusal(services, provider, clock, error, status):
    provider.polls = [httpx.Response(400, json={"error": error})]
    _start, _secret, result = _device(services)
    assert result.status == status
    assert services.auth.store.load() is None and services.auth.status().method == "manual"


def test_device_polling_survives_network_failures(services, provider, clock):
    provider.polls = [httpx.ConnectError("down"), httpx.Response(503), "ok"]
    _start, _secret, result = _device(services)
    assert result.status == "connected"
    assert clock.waits == [5, 10, 20]


def test_device_polling_stops_at_the_deadline(services, provider, clock):
    provider.device["expires_in"] = 30
    provider.polls = [httpx.ConnectError("down")] * 100
    _start, _secret, result = _device(services)
    assert result.status == "expired"
    assert sum(clock.waits) <= 30


def test_a_cancelled_device_sign_in_is_never_stored(services, provider, clock):
    start, secret = services.auth.start(flow="device")

    def cancel_first():
        provider.on_poll = None
        services.auth.cancel_session(start.session_id, secret)

    # Civitai approves in the same instant the user cancels.
    provider.on_poll = cancel_first
    provider.polls = ["ok"]
    result = services.auth.wait_session(start.session_id, secret, timeout=5)
    assert result.status == "cancelled"
    deadline = time.monotonic() + 5
    while "refresh-1" not in provider.revoked and time.monotonic() < deadline:
        time.sleep(0.01)
    assert services.auth.store.load() is None and services.auth.status().method == "manual"
    assert "refresh-1" in provider.revoked


@pytest.mark.parametrize(
    "change",
    [
        {"verification_uri": "https://evil.example/device"},
        {"verification_uri": "http://auth.civitai.com/login/oauth/device"},
        {"user_code": None},
        {"device_code": ""},
    ],
)
def test_a_suspicious_device_answer_is_refused(services, provider, change):
    provider.device.update(change)
    with pytest.raises(SourceError):
        services.auth.start(flow="device")
    assert services.auth.transactions.pending == 0


def test_an_untrusted_complete_link_falls_back_to_the_plain_one(services, provider, clock):
    provider.device["verification_uri_complete"] = "https://evil.example/?code=ABCD-EFGH"
    start, _secret = services.auth.start(flow="device")
    assert start.authorization_url == "https://auth.civitai.com/login/oauth/device"


def test_a_client_without_the_device_grant_says_so(services, provider):
    provider.device = {"error": "unauthorized_client", "error_description": "Client not authorized for device flow"}

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/oauth/device":
            return httpx.Response(400, json=provider.device)
        return provider(request)

    services.http._transport = httpx.MockTransport(refuse)
    services.http.close()
    with pytest.raises(AuthRequiredError) as raised:
        services.auth.start(flow="device")
    assert raised.value.detail["reason"] == "client_unavailable"


def test_device_sessions_are_bounded_and_stop_on_close(services, provider, clock):
    clock.wait = lambda event, seconds: event.wait(0.01)  # keep them pending
    services.auth.device._wait = clock.wait
    started = [services.auth.start(flow="device") for _ in range(MAX_DEVICE_SESSIONS)]
    with pytest.raises(ConflictError):
        services.auth.start(flow="device")
    services.auth.close()
    assert all(services.auth.session(s.session_id, secret).status == "cancelled" for s, secret in started)
    assert not services.auth.device._threads


def test_choose_flow(services):
    assert services.auth.choose_flow("auto") == "browser"
    assert services.auth.choose_flow("auto", browser_available=False) == "device"
    with pytest.raises(ValidationError):
        services.auth.choose_flow("browser", browser_available=False)
    services.auth.profiles = (VERIFIED,)
    services.settings.update({"auth": {"civitai": {"oauth_client_id": None}}})
    assert services.auth.choose_flow("auto") == "browser"
    with pytest.raises(ValidationError) as raised:
        services.auth.choose_flow("auto", browser_available=False)
    assert raised.value.detail["reason"] == "callback_unsupported"
    with pytest.raises(ValidationError):
        services.auth.choose_flow("device")
