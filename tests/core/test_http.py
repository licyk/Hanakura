"""Shared HTTP client compatibility and network settings."""

import httpx
import pytest

from hanakura.core.net.http import HttpClientProvider
from hanakura.core.settings import SettingsService
from hanakura.version import VERSION


@pytest.mark.parametrize("proxy", [None, "", "http://127.0.0.1:8080"])
def test_client_accepts_proxy_settings(tmp_path, proxy):
    settings = SettingsService(data_dir=tmp_path, environ={})
    settings.update({"network": {"proxy": proxy}})
    provider = HttpClientProvider(settings)
    try:
        client = provider.get()
        assert provider.get() is client
        assert client.follow_redirects
        assert client.timeout.read == settings.settings.network.timeout
    finally:
        provider.close()


@pytest.mark.parametrize("api", ["legacy", "modern", "transition"])
@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:8080"])
def test_client_supports_proxy_keyword_changes(tmp_path, monkeypatch, api, proxy):
    original_client = httpx.Client
    calls = []
    unused = object()

    def legacy(*, proxies, **kwargs):
        calls.append(proxies)
        return original_client(**kwargs)

    def modern(*, proxy, **kwargs):
        calls.append(proxy)
        return original_client(**kwargs)

    def transition(*, proxy, proxies=unused, **kwargs):
        assert proxies is unused
        return modern(proxy=proxy, **kwargs)

    monkeypatch.setattr(httpx, "Client", {"legacy": legacy, "modern": modern, "transition": transition}[api])
    settings = SettingsService(data_dir=tmp_path, environ={})
    settings.update({"network": {"proxy": proxy}})
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    provider = HttpClientProvider(settings, transport=transport)
    first = None
    try:
        first = provider.get()
        assert provider.get() is first
        settings.update({"network": {"proxy": "http://127.0.0.1:9090"}})
        assert provider.get() is not first
        assert calls == [proxy, "http://127.0.0.1:9090"]
    finally:
        provider.close()
        if first is not None:
            first.close()


def test_client_preserves_transport_and_redirects(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/end"})
        return httpx.Response(200, text="ok")

    provider = HttpClientProvider(SettingsService(data_dir=tmp_path, environ={}), transport=httpx.MockTransport(handler))
    try:
        assert provider.get().get("https://example.test/start").text == "ok"
        assert [request.url.path for request in seen] == ["/start", "/end"]
        assert all(request.headers["User-Agent"] == f"hanakura/{VERSION}" for request in seen)
    finally:
        provider.close()
