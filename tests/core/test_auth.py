"""Civitai authentication: OAuth with PKCE, and the manual token that must keep working."""

import base64
import hashlib
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from hanakura.core.auth.oauth_client import REFRESH_MARGIN_SECONDS, ReauthorizationRequired, challenge_for, make_verifier
from hanakura.core.auth.store import FileCredentialStore, KeyringCredentialStore, OAuthCredentials, open_store
from hanakura.core.auth.transactions import TransactionStore
from hanakura.core.context import build_services
from hanakura.core.errors import ConflictError, ValidationError
from hanakura.core.settings import SettingsService

CLIENT_ID = "hanakura-test"
REDIRECT = "http://127.0.0.1:7865/api/v1/auth/civitai/callback"


class Provider:
    """A stand-in for auth.civitai.com that records what it was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.tokens = 0
        self.revoked: list[str] = []
        self.refresh_fails: Exception | httpx.Response | None = None
        self.expires_in = 3600
        self.last_refresh_token: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth/oauth/token":
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["refresh_token"]:
                self.last_refresh_token = form["refresh_token"][0]
                if isinstance(self.refresh_fails, httpx.Response):
                    return self.refresh_fails
                if self.refresh_fails is not None:
                    raise self.refresh_fails
            self.tokens += 1
            n = self.tokens
            return httpx.Response(
                200,
                json={"access_token": f"access-{n}", "refresh_token": f"refresh-{n}", "expires_in": self.expires_in, "scope": "5", "token_type": "Bearer"},
            )
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
    transaction, secret = store.create(REDIRECT, "/", 5, CLIENT_ID)
    assert store.claim(transaction.state, secret) is None


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

    original_refresh = services.auth._oauth_client().refresh

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

        def get_keyring(self):
            return self

        def get_password(self, service, user):
            return self.values.get((service, user))

        def set_password(self, service, user, value):
            self.values[(service, user)] = value

        def delete_password(self, service, user):
            del self.values[(service, user)]

    fake = FakeKeyring()
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake)
    store = open_store(tmp_path)
    assert isinstance(store, KeyringCredentialStore)
    store.save(OAuthCredentials(access_token="a"))
    assert store.load().access_token == "a"
    assert not (tmp_path / "credentials").exists()
    store.clear()
    assert store.load() is None


def test_a_broken_keyring_falls_back_to_a_file(tmp_path, monkeypatch):
    class BrokenKeyring:
        def get_keyring(self):
            return self

        def get_password(self, *_args):
            raise RuntimeError("no secret service")

    monkeypatch.setitem(__import__("sys").modules, "keyring", BrokenKeyring())
    assert isinstance(open_store(tmp_path), FileCredentialStore)


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
