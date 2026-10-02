"""Embedding Hanakura in another application: HanakuraServer and the route prefix."""

import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hanakura import HanakuraServer, ModelRoot
from hanakura.api.app import create_app, normalize_prefix
from hanakura.core.context import build_services
from hanakura.core.errors import ConflictError, ValidationError
from hanakura.core.library.models import RootCreate, RootUpdate
from tests.conftest import LORA_SDXL, write_safetensors


def get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def models(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    write_safetensors(folder / "loras" / "one.safetensors", LORA_SDXL)
    return folder


# -- the server object ---------------------------------------------------------


def test_start_returns_a_url_and_serves(tmp_path, models):
    hub = HanakuraServer(data_dir=tmp_path / "data", model_roots=[ModelRoot(models, layout="comfyui", name="Models")], port=0)
    url = hub.start()
    try:
        assert url.startswith("http://127.0.0.1:") and hub.running
        assert hub.port == int(url.rsplit(":", 1)[1])
        status, body = get(f"{url}/api/v1/app/health")
        assert status == 200 and '"status":"ok"' in body.replace(" ", "")
        status, body = get(f"{url}/api/v1/library/roots")
        assert status == 200 and str(models.resolve()) in body
    finally:
        hub.stop()
    assert not hub.running


def test_stop_releases_the_port_and_is_repeatable(tmp_path):
    hub = HanakuraServer(data_dir=tmp_path / "data", port=0)
    url = hub.start()
    port = hub.port
    hub.stop()
    hub.stop()  # safe to call twice
    with pytest.raises(RuntimeError):
        _ = hub.url
    # The port is free again.
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
    assert url


def test_two_servers_pick_different_free_ports(tmp_path):
    first = HanakuraServer(data_dir=tmp_path / "a", port=0)
    second = HanakuraServer(data_dir=tmp_path / "b", port=0)
    try:
        first.start()
        second.start()
        assert first.port != second.port
        assert get(f"{first.url}/api/v1/app/health")[0] == 200
        assert get(f"{second.url}/api/v1/app/health")[0] == 200
    finally:
        first.stop()
        second.stop()


def test_a_taken_port_moves_up_unless_strict(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]

        moved = HanakuraServer(data_dir=tmp_path / "a", port=port)
        try:
            moved.start()
            assert moved.port != port
        finally:
            moved.stop()

        strict = HanakuraServer(data_dir=tmp_path / "b", port=port, strict_port=True)
        with pytest.raises(Exception, match="strict|unavailable"):
            strict.start()
        strict.stop()


def test_context_manager(tmp_path):
    with HanakuraServer(data_dir=tmp_path / "data", port=0) as hub:
        assert get(f"{hub.url}/api/v1/app/version")[0] == 200
    assert not hub.running


def test_the_settings_file_can_live_anywhere(tmp_path, models):
    """The host application chooses where the settings file is, apart from the data folder."""
    config = tmp_path / "host-config" / "hanakura.toml"
    config.parent.mkdir(parents=True)
    hub = HanakuraServer(data_dir=tmp_path / "data", model_roots=[models], port=0, settings_path=config)
    try:
        hub.start()
        assert hub.services is not None
        assert hub.services.settings.path == config
        assert config.exists(), "the seeded folder was written to the chosen config file"
        assert "model_roots" in config.read_text()
        # The database and caches still live in the data folder.
        assert (tmp_path / "data" / "hanakura.db").exists()
        assert not (tmp_path / "data" / "settings.toml").exists()
    finally:
        hub.stop()


def test_an_existing_settings_file_is_read(tmp_path):
    config = tmp_path / "prepared.toml"
    config.write_text("[downloads]\nsave_preview = false\n[network]\nmax_retries = 7\n")
    hub = HanakuraServer(data_dir=tmp_path / "data", settings_path=config, port=0)
    try:
        hub.start()
        settings = hub.services.settings.settings
        assert settings.downloads.save_preview is False and settings.network.max_retries == 7
    finally:
        hub.stop()


def test_pinned_settings_cannot_be_changed(tmp_path):
    hub = HanakuraServer(data_dir=tmp_path / "data", port=0, settings={"downloads": {"verify_hash": False}, "content": {"nsfw_mode": "hide"}})
    try:
        hub.start()
        services = hub.services
        assert services is not None and services.settings.settings.downloads.verify_hash is False
        services.settings.update({"downloads": {"verify_hash": True}})
        # The host application's value wins and survives the write.
        assert services.settings.settings.downloads.verify_hash is False
        assert services.settings.settings.content.nsfw_mode == "hide"
    finally:
        hub.stop()


@pytest.mark.parametrize("value", [True, False])
def test_combined_view_can_be_pinned(tmp_path, value):
    hub = HanakuraServer(data_dir=tmp_path / "data", port=0, combined_view=value, settings={"library": {"show_all_files": True}})
    services = hub._build()
    try:
        services.settings.update({"library": {"combined_view": not value}})
        assert services.settings.settings.library.combined_view is value
        # Pinning it keeps the host's other library settings.
        assert services.settings.settings.library.show_all_files is True
        assert "library.combined_view" in services.settings.view().pinned
    finally:
        services.close()


def test_combined_view_is_left_to_the_user_by_default(tmp_path):
    services = HanakuraServer(data_dir=tmp_path / "data", port=0)._build()
    try:
        assert services.settings.settings.library.combined_view is False
        services.settings.update({"library": {"combined_view": True}})
        assert services.settings.settings.library.combined_view is True
    finally:
        services.close()


def test_the_combined_view_id_cannot_be_a_host_root(tmp_path, models):
    with pytest.raises(ValidationError):
        HanakuraServer(data_dir=tmp_path / "data", model_roots=[ModelRoot(models, id="*")], lock_model_roots=True)


# -- model folders -------------------------------------------------------------


def test_roots_are_seeded_with_their_layout(tmp_path, models):
    hub = HanakuraServer(data_dir=tmp_path / "data", model_roots=[ModelRoot(models, layout="comfyui", name="Mine")], port=0)
    try:
        hub.start()
        roots = hub.services.library.list_roots()
        assert [(r.name, r.layout) for r in roots] == [("Mine", "comfyui")]
        # Not locked: the user may still add their own.
        other = tmp_path / "more"
        other.mkdir()
        hub.services.library.add_root(RootCreate(path=str(other), layout="custom"))
        assert len(hub.services.library.list_roots()) == 2
    finally:
        hub.stop()


def test_locked_roots_cannot_be_changed(tmp_path, models):
    hub = HanakuraServer(data_dir=tmp_path / "data", model_roots=[ModelRoot(models, layout="sd-webui")], lock_model_roots=True, port=0)
    try:
        url = hub.start()
        library = hub.services.library
        assert [r.layout for r in library.list_roots()] == ["sd-webui"]
        root_id = library.list_roots()[0].id
        for call in (
            lambda: library.add_root(RootCreate(path=str(tmp_path), layout="custom")),
            lambda: library.update_root(root_id, RootUpdate(name="other")),
            lambda: library.remove_root(root_id),
        ):
            with pytest.raises(ConflictError, match="fixed by the application"):
                call()
        # The interface is told, so it hides those actions.
        assert '"roots_locked":true' in get(f"{url}/api/v1/app/meta")[1].replace(" ", "")
        # Browsing still works.
        assert get(f"{url}/api/v1/library/roots/{root_id}/entries?path=loras")[0] == 200
    finally:
        hub.stop()


def test_locked_roots_are_refused_over_the_api(tmp_path, models):
    services = build_services(data_dir=tmp_path / "data", environ={}, roots_locked=True, settings_overrides={"paths": {"model_roots": [ModelRoot(models).to_settings()]}})
    app = create_app(services, bound_host="127.0.0.1", start_downloads=False, serve_ui=False)
    try:
        with TestClient(app, base_url="http://localhost") as client:
            headers = {"origin": "http://localhost"}
            assert client.post("/api/v1/library/roots", json={"path": str(tmp_path), "layout": "custom"}, headers=headers).status_code == 409
            root_id = client.get("/api/v1/library/roots").json()[0]["id"]
            assert client.patch(f"/api/v1/library/roots/{root_id}", json={"name": "x"}, headers=headers).status_code == 409
            assert client.delete(f"/api/v1/library/roots/{root_id}", headers=headers).status_code == 409
    finally:
        services.close()


# -- the route prefix ----------------------------------------------------------


@pytest.mark.parametrize(("given", "expected"), [(None, ""), ("", ""), ("/hub", "/hub"), ("hub", "/hub"), ("/hub/", "/hub"), ("a/b", "/a/b")])
def test_prefix_is_normalized(given, expected):
    assert normalize_prefix(given) == expected


def test_everything_moves_under_the_prefix(tmp_path, models):
    services = build_services(data_dir=tmp_path / "data", environ={})
    app = create_app(services, bound_host="127.0.0.1", start_downloads=False, serve_ui=False, api_prefix="/hanakura")
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/hanakura/api/v1/app/health").status_code == 200
            assert client.get("/hanakura/openapi.json").status_code == 200
            socket_reply = client.get("/hanakura/ws/socket.io/", params={"EIO": "4", "transport": "polling"})
            assert socket_reply.status_code == 200 and socket_reply.text.startswith("0{")
            # Nothing is left at the unprefixed paths, so a host application can use them.
            assert client.get("/api/v1/app/health").status_code == 404
            assert client.get("/ws/socket.io/", params={"EIO": "4", "transport": "polling"}).status_code == 404
    finally:
        services.close()


def test_the_prefix_keeps_access_control(tmp_path):
    services = build_services(data_dir=tmp_path / "data", environ={})
    services.settings.update({"server": {"access_token": "tok"}})
    app = create_app(services, bound_host="127.0.0.1", start_downloads=False, serve_ui=False, api_prefix="/hub")
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/hub/api/v1/settings").status_code == 401
            assert client.get("/hub/api/v1/app/health").status_code == 200  # still public
            assert client.get("/hub/api/v1/settings", headers={"authorization": "Bearer tok"}).status_code == 200
            # The OAuth callback stays the one exemption, under the prefix.
            assert client.get("/hub/api/v1/auth/civitai/callback", params={"error": "denied"}, follow_redirects=False).status_code == 303
            assert client.get("/hub/api/v1/app/meta", headers={"authorization": "Bearer tok"}).json()["api_prefix"] == "/hub"
    finally:
        services.close()


def test_prefix_over_a_real_server(tmp_path, models):
    hub = HanakuraServer(data_dir=tmp_path / "data", model_roots=[models], port=0, api_prefix="/tools/hanakura")
    try:
        url = hub.start()
        assert url.endswith("/tools/hanakura")
        assert get(f"{url}/api/v1/app/health")[0] == 200
        base = url[: -len("/tools/hanakura")]
        assert get(f"{base}/api/v1/app/health")[0] == 404
    finally:
        hub.stop()
