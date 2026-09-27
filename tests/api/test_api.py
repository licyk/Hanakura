import io
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sd_model_hub.api.app import create_app
from sd_model_hub.core.context import build_services
from tests.conftest import LORA_SDXL, write_safetensors

HOST = {"host": "localhost"}


@pytest.fixture
def services(tmp_path):
    s = build_services(data_dir=tmp_path / "data", environ={})
    yield s
    s.close()


@pytest.fixture
def client(services):
    app = create_app(services, bound_host="127.0.0.1", start_downloads=False, serve_ui=False)
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def root(client, tmp_path):
    d = tmp_path / "models"
    (d / "loras").mkdir(parents=True)
    r = client.post("/api/v1/library/roots", json={"path": str(d), "layout": "comfyui"}, headers={"origin": "http://localhost"})
    assert r.status_code == 201, r.text
    return r.json()["id"], d


def test_health_and_version(client):
    assert client.get("/api/v1/app/health").json() == {"status": "ok", "auth_required": False}
    assert client.get("/api/v1/app/meta").json()["layouts"]["comfyui"]["loras"] == "lora"


def test_error_shape(client):
    r = client.get("/api/v1/library/roots/nope/entries")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found" and "nope" in r.json()["message"]


def test_settings_hide_tokens(client, services):
    r = client.patch("/api/v1/settings", json={"sources": {"civitai": {"token": "SECRET"}}})
    assert r.status_code == 200 and "SECRET" not in r.text
    assert r.json()["sources"]["civitai"]["token_configured"] is True
    assert services.settings.settings.sources["civitai"].token == "SECRET"
    assert client.patch("/api/v1/settings", json={"server": {"port": 0}}).status_code == 400
    assert client.patch("/api/v1/settings", json={"paths": {}}).status_code == 400


def test_client_state(client):
    assert client.get("/api/v1/client-state/theme").json() is None
    client.put("/api/v1/client-state/theme", json={"mode": "dark"})
    assert client.get("/api/v1/client-state/theme").json() == {"mode": "dark"}


def test_library_listing_and_preview(client, root):
    root_id, d = root
    write_safetensors(d / "loras" / "a.safetensors", LORA_SDXL)
    img = io.BytesIO()
    Image.new("RGB", (800, 600), "red").save(img, "PNG")
    (d / "loras" / "a.png").write_bytes(img.getvalue())
    listing = client.get(f"/api/v1/library/roots/{root_id}/entries", params={"path": "loras"}).json()
    assert listing["models"][0]["preview"] == "loras/a.png"
    r = client.get(f"/api/v1/library/roots/{root_id}/preview", params={"path": "loras/a.png", "size": 256})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(r.content)).size[0] == 256
    assert client.get(f"/api/v1/library/roots/{root_id}/preview", params={"path": "loras/a.safetensors"}).status_code == 404
    assert client.get(f"/api/v1/library/roots/{root_id}/entries", params={"path": "../.."}).status_code == 400


def test_locate_finds_the_root_holding_a_path(client, root):
    """A finished download names an absolute folder; the client turns it into a root and a path."""
    root_id, d = root
    r = client.get("/api/v1/library/locate", params={"path": str(d / "loras")})
    assert r.status_code == 200 and r.json() == {"root_id": root_id, "path": "loras"}
    assert client.get("/api/v1/library/locate", params={"path": str(d.parent / "elsewhere")}).status_code == 404


def test_upload_streams_raw_body(client, root):
    root_id, d = root
    body = b"x" * (3 * 1024 * 1024 + 7)
    r = client.put("/api/v1/library/upload", params={"root_id": root_id, "path": "loras", "name": "dir/up.safetensors"}, content=body, headers={"origin": "http://localhost"})
    assert r.status_code == 201, r.text
    assert r.json()["path"] == "loras/dir/up.safetensors"
    assert (d / "loras" / "dir" / "up.safetensors").read_bytes() == body
    again = client.put("/api/v1/library/upload", params={"root_id": root_id, "path": "loras", "name": "dir/up.safetensors"}, content=b"y", headers={"origin": "http://localhost"})
    assert again.status_code == 409
    bad = client.put("/api/v1/library/upload", params={"root_id": root_id, "path": "loras", "name": "../evil"}, content=b"y", headers={"origin": "http://localhost"})
    assert bad.status_code == 400
    assert not list((d / "loras").rglob("*.part"))


def test_rename_move_delete_via_api(client, root):
    root_id, d = root
    write_safetensors(d / "loras" / "m.safetensors", LORA_SDXL)
    h = {"origin": "http://localhost"}
    r = client.post("/api/v1/library/rename", json={"root_id": root_id, "path": "loras/m.safetensors", "new_name": "n"}, headers=h)
    assert r.json()["paths"][0]["path"] == "loras/n.safetensors"
    client.post("/api/v1/library/folders", json={"root_id": root_id, "path": "", "name": "archive"}, headers=h)
    r = client.post("/api/v1/library/move", json={"items": [{"root_id": root_id, "path": "loras/n.safetensors"}], "dest_root_id": root_id, "dest_dir": "archive"}, headers=h)
    assert r.json()["paths"][0]["path"] == "archive/n.safetensors"
    r = client.post("/api/v1/library/delete", json={"items": [{"root_id": root_id, "path": "archive/n.safetensors"}], "permanent": True}, headers=h)
    assert r.status_code == 200 and not (d / "archive" / "n.safetensors").exists()


def test_host_header_checked(client):
    assert client.get("/api/v1/app/version", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/v1/app/version", headers={"host": "127.0.0.1:7865"}).status_code == 200


def test_cross_origin_writes_refused(client):
    r = client.put("/api/v1/client-state/x", json=1, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "bad_origin"
    r = client.put("/api/v1/client-state/x", json=1, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    assert client.put("/api/v1/client-state/x", json=1, headers={"origin": "http://localhost"}).status_code == 200
    # No Origin and no Sec-Fetch-Site: a non-browser client such as curl.
    assert client.put("/api/v1/client-state/x", json=1).status_code == 200


def test_access_token(services, client):
    services.settings.update({"server": {"access_token": "tok"}})
    assert client.get("/api/v1/settings").status_code == 401
    assert client.get("/api/v1/app/health").json()["auth_required"] is True
    assert client.get("/api/v1/settings", headers={"authorization": "Bearer tok"}).status_code == 200
    assert client.get("/api/v1/settings", cookies={"sd_model_hub_token": "tok"}).status_code == 200
    assert client.get("/api/v1/settings", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_combined_entries(client, root, tmp_path):
    root_id, _ = root
    other = tmp_path / "other"
    (other / "loras").mkdir(parents=True)
    r = client.post("/api/v1/library/roots", json={"path": str(other), "name": "other"}, headers={"origin": "http://localhost"})
    listing = client.get("/api/v1/library/combined/entries").json()
    assert sorted((f["label"], f["root_id"]) for f in listing["folders"]) == [("loras (models)", root_id), ("loras (other)", r.json()["id"])]
    assert listing["missing_roots"] == []


def test_download_file_is_an_attachment(client, root):
    root_id, d = root
    data = b"\x00weights" * 1000
    (d / "loras" / "模型 a.safetensors").write_bytes(data)
    r = client.get(f"/api/v1/library/roots/{root_id}/file", params={"path": "loras/模型 a.safetensors"})
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "application/octet-stream"
    # The name survives as UTF-8, and the browser is told to save rather than show it.
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "filename*=utf-8''%E6%A8%A1%E5%9E%8B%20a.safetensors" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "private, no-store"
    partial = client.get(f"/api/v1/library/roots/{root_id}/file", params={"path": "loras/模型 a.safetensors"}, headers={"range": "bytes=1-7"})
    assert partial.status_code == 206 and partial.content == b"weights"
    assert client.get(f"/api/v1/library/roots/{root_id}/file", params={"path": "loras"}).status_code == 400
    assert client.get(f"/api/v1/library/roots/{root_id}/file", params={"path": "../../etc/passwd"}).status_code == 400


def test_download_file_needs_the_access_token(services, client, root):
    root_id, d = root
    (d / "loras" / "m.safetensors").write_bytes(b"x")
    services.settings.update({"server": {"access_token": "tok"}})
    url = f"/api/v1/library/roots/{root_id}/file"
    assert client.get(url, params={"path": "loras/m.safetensors"}).status_code == 401
    # A browser download is a navigation: it carries the cookie, not a bearer header.
    assert client.get(url, params={"path": "loras/m.safetensors"}, cookies={"sd_model_hub_token": "tok"}).status_code == 200


def test_openapi_has_events(client):
    schema = client.get("/openapi.json").json()
    assert "download_progress" in schema["components"]["schemas"]["ServerEvents"]["properties"]
    assert schema["paths"]["/api/v1/hubs/{hub}/repos/{repo_id}/files"]["get"]["operationId"] == "list_repo_files"

    def check_refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/components/schemas/")
                assert value["$ref"].rsplit("/", 1)[1] in schema["components"]["schemas"]
            for item in value.values():
                check_refs(item)
        elif isinstance(value, list):
            for item in value:
                check_refs(item)

    check_refs(schema)
    job_schema = schema["paths"]["/api/v1/downloads/{job_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    job_schema = schema["components"]["schemas"][job_schema["$ref"].rsplit("/", 1)[1]]
    assert job_schema["properties"]["can_pause"]["readOnly"] is True
    assert "can_pause" in job_schema["required"]


@pytest.mark.parametrize("sha256", ["abc", "g" * 64, "a" * 63, "a" * 65])
def test_identify_rejects_invalid_hash(client, services, monkeypatch, sha256):
    def unexpected_call(_hash):
        pytest.fail("An invalid hash must be rejected before calling a source")

    monkeypatch.setattr(services.sources, "identify", unexpected_call)
    assert client.post("/api/v1/sources/identify", json={"sha256": sha256}).status_code == 422


def test_identify_accepts_valid_hash(client, services, monkeypatch):
    monkeypatch.setattr(services.sources, "identify", lambda value: [] if value == "aB" * 32 else pytest.fail("Hash changed"))
    response = client.post("/api/v1/sources/identify", json={"sha256": "aB" * 32})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("runner,can_pause", [("http", True), ("huggingface", False)])
def test_download_response_computed_field(client, services, monkeypatch, runner, can_pause):
    from datetime import datetime, timezone

    from sd_model_hub.core.downloads.models import DownloadJob

    job = DownloadJob(id=1, runner=runner, title="model", dest_dir="/models", created_at=datetime.now(timezone.utc))
    monkeypatch.setattr(services.downloads, "get", lambda job_id: job)
    response = client.get("/api/v1/downloads/1")
    assert response.status_code == 200, response.text
    assert response.json()["can_pause"] is can_pause


CIVITAI_AUTH = "/api/v1/auth/civitai"


@pytest.fixture
def oauth_client(tmp_path):
    """A client whose network is a stand-in Civitai authorization service."""
    from tests.core.test_auth import CLIENT_ID, Provider

    provider = Provider()
    services = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(provider))
    services.settings.update({"auth": {"civitai": {"oauth_client_id": CLIENT_ID, "use_keyring": False}}})
    app = create_app(services, bound_host="127.0.0.1", bound_port=7865, start_downloads=False, serve_ui=False)
    with TestClient(app, base_url="http://localhost") as c:
        yield c, services, provider
    services.close()


def test_oauth_round_trip_through_the_api(oauth_client):
    client, _services, provider = oauth_client
    start = client.post(f"{CIVITAI_AUTH}/start", json={"return_to": "/#/settings"}, headers={"origin": "http://localhost"})
    assert start.status_code == 200
    url = start.json()["authorization_url"]
    assert url.startswith("https://auth.civitai.com/api/auth/oauth/authorize?")
    assert "code_challenge_method=S256" in url
    # The browser binding is an HttpOnly cookie, scoped to the auth routes.
    cookie = next(c for c in start.headers.get_list("set-cookie") if c.startswith("sd_model_hub_oauth="))
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower() and "Path=/api/v1/auth/civitai" in cookie
    assert "access_token" not in start.text

    state = parse_qs(urlsplit(url).query)["state"][0]
    callback = client.get(f"{CIVITAI_AUTH}/callback", params={"code": "the-code", "state": state}, follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/#/settings?civitai=connected"
    assert callback.headers["cache-control"] == "no-store" and callback.headers["referrer-policy"] == "no-referrer"
    assert "access-1" not in callback.text

    status = client.get(f"{CIVITAI_AUTH}/status").json()
    assert status["oauth_state"] == "connected" and status["account"]["username"] == "someone"
    # Status describes the connection; it never carries a credential value.
    assert not any(secret in json.dumps(status) for secret in ("access-1", "refresh-1"))

    # The callback used the address the server is bound to.
    exchange = next(r for r in provider.requests if r.url.path.endswith("/token"))
    assert parse_qs(exchange.content.decode())["redirect_uri"] == ["http://127.0.0.1:7865/api/v1/auth/civitai/callback"]


def test_callback_without_the_cookie_is_refused(oauth_client):
    client, services, provider = oauth_client
    start = client.post(f"{CIVITAI_AUTH}/start", headers={"origin": "http://localhost"})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    client.cookies.clear()
    callback = client.get(f"{CIVITAI_AUTH}/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert callback.status_code == 303 and callback.headers["location"].endswith("civitai=error")
    assert services.auth.store.load() is None
    # The code was never exchanged.
    assert not [r for r in provider.requests if r.url.path.endswith("/token")]


def test_refused_authorization_returns_to_settings(oauth_client):
    client, services, _provider = oauth_client
    start = client.post(f"{CIVITAI_AUTH}/start", headers={"origin": "http://localhost"})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    callback = client.get(f"{CIVITAI_AUTH}/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    assert callback.status_code == 303 and callback.headers["location"].endswith("civitai=error")
    # The transaction is dropped, so nothing is left pending.
    assert services.auth.status().oauth_state == "not_connected"


def test_only_the_callback_is_exempt_from_the_access_token(oauth_client):
    client, services, _provider = oauth_client
    services.settings.update({"server": {"access_token": "tok"}})
    # The callback has to work: the browser arrives from Civitai with no header.
    assert client.get(f"{CIVITAI_AUTH}/callback", params={"error": "access_denied"}, follow_redirects=False).status_code == 303
    # Everything else keeps normal access control.
    assert client.get(f"{CIVITAI_AUTH}/status").status_code == 401
    assert client.post(f"{CIVITAI_AUTH}/start", headers={"origin": "http://localhost"}).status_code == 401
    assert client.post(f"{CIVITAI_AUTH}/disconnect", headers={"origin": "http://localhost"}).status_code == 401
    assert client.post(f"{CIVITAI_AUTH}/callback", headers={"origin": "http://localhost"}).status_code in (401, 405)
    assert client.get(f"{CIVITAI_AUTH}/status", headers={"authorization": "Bearer tok"}).status_code == 200


def test_callback_still_checks_the_host_header(oauth_client):
    client, _services, _provider = oauth_client
    assert client.get(f"{CIVITAI_AUTH}/callback", params={"error": "x"}, headers={"host": "evil.example"}, follow_redirects=False).status_code == 400


def test_manual_token_and_oauth_are_separate_over_the_api(oauth_client):
    client, services, _provider = oauth_client
    h = {"origin": "http://localhost"}
    client.patch("/api/v1/settings", json={"sources": {"civitai": {"token": "manual"}}}, headers=h)
    start = client.post(f"{CIVITAI_AUTH}/start", headers=h)
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    client.get(f"{CIVITAI_AUTH}/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert client.get(f"{CIVITAI_AUTH}/status").json()["method"] == "oauth"

    disconnected = client.post(f"{CIVITAI_AUTH}/disconnect", headers=h).json()
    assert disconnected["manual_token_configured"] is True
    assert services.settings.settings.sources["civitai"].token == "manual"
    # Nothing switched by itself; the user asks for the manual token explicitly.
    assert disconnected["method"] == "oauth"
    chosen = client.post(f"{CIVITAI_AUTH}/method", json={"method": "manual"}, headers=h).json()
    assert chosen["method"] == "manual" and chosen["effective_method"] == "manual"


def test_unconfigured_oauth_explains_itself(client):
    r = client.post(f"{CIVITAI_AUTH}/start", headers={"origin": "http://localhost"})
    assert r.status_code == 400 and "oauth_client_id" in r.json()["message"]
    assert client.get(f"{CIVITAI_AUTH}/status").json()["oauth_configured"] is False


def test_socketio_endpoint_answers(client):
    r = client.get("/ws/socket.io/", params={"EIO": "4", "transport": "polling"})
    assert r.status_code == 200 and r.text.startswith("0{")


def test_repo_ids_with_slash_route(services, client, monkeypatch):
    from sd_model_hub.core.hubs.models import RepoDetail

    seen = {}

    def fake_get_repo(hub, repo_id, revision=None):
        seen["args"] = (hub, repo_id, revision)
        return RepoDetail(hub=hub, id=repo_id, name="r", page_url="u", revision="main")

    monkeypatch.setattr(services.hubs, "get_repo", fake_get_repo)
    assert client.get("/api/v1/hubs/huggingface/repos/owner/name").status_code == 200
    assert seen["args"] == ("huggingface", "owner/name", None)


def test_static_fallback(tmp_path, services, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ui</html>")
    (dist / "assets" / "app-abc.js").write_text("js")
    monkeypatch.setattr("sd_model_hub.api.app.web_dist_dir", lambda: dist)
    app = create_app(services, bound_host="127.0.0.1", start_downloads=False)
    with TestClient(app, base_url="http://localhost") as c:
        page = c.get("/library/deep/link", headers={"accept": "text/html"})
        assert page.status_code == 200 and "ui" in page.text and page.headers["cache-control"] == "no-cache"
        assert c.get("/assets/missing.js", headers={"accept": "*/*"}).status_code == 404
        asset = c.get("/assets/app-abc.js")
        assert "immutable" in asset.headers["cache-control"]
        assert c.get("/api/v1/app/version").status_code == 200
