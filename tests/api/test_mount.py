"""Sub-app paths must work with both old and new Starlette mount semantics."""

from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hanakura.api.app import create_app
from hanakura.core.context import build_services
from hanakura.core.events.models import LibraryChangedEvent
from tests.core.test_auth import CLIENT_ID, Provider


@pytest.mark.parametrize("mount,prefix", [("", "/hub"), ("/host", ""), ("/host", "/hub"), ("/hub", "/hub")])
def test_mounted_api_security_and_socket(services, mount, prefix):
    services.settings.update({"server": {"access_token": "secret"}})
    child = create_app(services, bound_host="localhost", api_prefix=prefix, start_downloads=False, serve_ui=False)

    @asynccontextmanager
    async def lifespan(_app):
        async with child.router.lifespan_context(child):
            yield

    parent = FastAPI(lifespan=lifespan)
    parent.mount(mount or "/", child)
    base = mount + prefix
    with TestClient(parent, base_url="http://localhost") as client:
        assert client.get(f"{base}/api/v1/app/health").status_code == 200
        assert client.get(f"{base}/api/v1/settings").status_code == 401
        headers = {"Authorization": "Bearer secret"}
        assert client.get(f"{base}/api/v1/settings", headers=headers).status_code == 200
        assert client.patch(f"{base}/api/v1/settings", json={}, headers={**headers, "Origin": "https://elsewhere.example"}).status_code == 403
        polling = client.get(f"{base}/ws/socket.io/?EIO=4&transport=polling", headers=headers)
        assert polling.status_code == 200 and polling.text.startswith('0{"sid":')
        with client.websocket_connect(f"ws://localhost{base}/ws/socket.io/?EIO=4&transport=websocket", headers={**headers, "Upgrade": "websocket"}) as ws:
            assert ws.receive_text().startswith('0{"sid":')
            ws.send_text("40")
            assert ws.receive_text().startswith("40")
            services.events.publish(LibraryChangedEvent(root_id="models", rel_path="loras"))
            message = ws.receive_text()
            assert message.startswith('42["library_changed",') and '"root_id":"models"' in message
        callback = client.get(f"{base}/api/v1/auth/civitai/callback?error=access_denied", follow_redirects=False)
        assert callback.status_code == 303
        assert callback.headers["location"] == f"{base}/#/settings?civitai=error"


@pytest.mark.parametrize("mount,prefix", [("", "/hub"), ("/webui", "/hub")])
def test_prefixed_oauth_cookie_round_trip(tmp_path, mount, prefix):
    provider = Provider()
    services = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(provider))
    services.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID, "use_keyring": False}}})
    child = create_app(services, bound_host="localhost", api_prefix=prefix, start_downloads=False, serve_ui=False)
    parent = FastAPI()
    parent.mount(mount or "/", child)
    path = f"{mount}{prefix}/api/v1/auth/civitai"
    try:
        with TestClient(parent, base_url="http://localhost") as client:
            start = client.post(f"{path}/start")
            assert start.status_code == 200, start.text
            assert f"Path={path}" in start.headers["set-cookie"]
            params = parse_qs(urlsplit(start.json()["authorization_url"]).query)
            assert params["redirect_uri"] == [f"http://127.0.0.1:7865{path}/callback"]
            callback = client.get(f"{path}/callback", params={"code": "code", "state": params["state"][0]}, follow_redirects=False)
            assert callback.headers["location"] == f"{mount}{prefix}/#/settings?civitai=connected"
            assert f"Path={path}" in callback.headers["set-cookie"]
            assert services.auth.status().oauth_state == "connected"
    finally:
        services.close()


def test_trusted_public_url_for_proxy_and_secure_cookie(tmp_path):
    services = build_services(data_dir=tmp_path / "data", environ={})
    services.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID, "use_keyring": False}}})
    app = create_app(services, public_base_url="https://example.com/webui/hub/", start_downloads=False, serve_ui=False)
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post("/api/v1/auth/civitai/start")
            params = parse_qs(urlsplit(response.json()["authorization_url"]).query)
            assert params["redirect_uri"] == ["https://example.com/webui/hub/api/v1/auth/civitai/callback"]
            assert "Secure" in response.headers["set-cookie"]
            assert "Path=/webui/hub/api/v1/auth/civitai" in response.headers["set-cookie"]
            services.settings.update({"auth": {"civitai": {"redirect_uris": ["https://other.example/api/v1/auth/civitai/callback"]}}})
            assert client.post("/api/v1/auth/civitai/start").status_code == 400
    finally:
        services.close()


@pytest.mark.parametrize("base", ["//example.com", "/hub", "https://user:pass@example.com", "https://example.com?q=x", "https://example.com/#fragment"])
def test_public_base_url_validation(services, base):
    with pytest.raises(ValueError):
        create_app(services, public_base_url=base)


def test_destination_endpoint_uses_core_rules(services, root):
    services.settings.update({"downloads": {"kind_destinations": {"lora": {"root_id": root.id, "rel_dir": "custom"}}}})
    app = create_app(services, start_downloads=False, serve_ui=False)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/library/destination?kind=lora")
        assert response.json() == {"root_id": root.id, "rel_dir": "custom"}
        assert client.get("/api/v1/library/destination?root_id=missing").status_code == 404


def test_mounted_ui_and_oauth_root_path(services, tmp_path, monkeypatch):
    from starlette import _utils

    from hanakura.api import app as app_module

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="./assets/app.js"></script>')
    (dist / "assets" / "app.js").write_text("window.loaded = true;")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: dist)
    child = create_app(services, start_downloads=False)
    parent = FastAPI()
    parent.mount("/hub", child)
    # Newer servers preserve the external prefix in scope.path; older servers strip it.
    request_base = "/webui/hub" if hasattr(_utils, "get_route_path") else "/hub"
    with TestClient(parent, base_url="http://localhost", root_path="/webui") as client:
        assert client.get(f"{request_base}/").text == '<script src="./assets/app.js"></script>'
        assert client.get(f"{request_base}/assets/app.js").text == "window.loaded = true;"
        response = client.get(f"{request_base}/api/v1/auth/civitai/callback?error=access_denied", follow_redirects=False)
        assert response.headers["location"] == "/webui/hub/#/settings?civitai=error"
        assert "Path=/webui/hub/api/v1/auth/civitai" in response.headers["set-cookie"]
