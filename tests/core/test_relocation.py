"""The data folder and model roots move: roots, downloads and the detection cache follow."""

import shutil
from pathlib import Path

import httpx

from hanakura.core.context import build_services
from hanakura.core.downloads import manager as manager_module
from hanakura.core.downloads.models import DownloadCreate
from hanakura.core.library.models import RootCreate, RootUpdate
from hanakura.core.settings.service import SettingsService
from tests.core.test_downloads import BODY, SHA, DroppingStream, Server, _wait_for, ranged


def test_a_root_inside_the_data_folder_moves_with_it(tmp_path):
    first = tmp_path / "a" / "data"
    inside = first / "models"
    (inside / "loras").mkdir(parents=True)
    outside = tmp_path / "models"
    outside.mkdir()
    s = build_services(data_dir=first, environ={})
    inner = s.library.add_root(RootCreate(name="inner", path=str(inside), layout="comfyui"))
    outer = s.library.add_root(RootCreate(name="outer", path=str(outside), layout="comfyui"))
    stored = {r.id: r.path for r in s.settings.settings.paths.model_roots}
    assert stored == {inner.id: "models", outer.id: str(outside.resolve())}
    assert inner.path == str(inside.resolve())  # handed out absolute
    s.close()
    moved = tmp_path / "b" / "data"
    moved.parent.mkdir()
    shutil.move(str(first), str(moved))
    s = build_services(data_dir=moved, environ={})
    try:
        roots = {r.id: r for r in s.library.list_roots()}
        assert roots[inner.id].exists and Path(roots[inner.id].path) == (moved / "models").resolve()
        assert roots[outer.id].exists and Path(roots[outer.id].path) == outside.resolve()
        assert s.library.locate(moved / "models" / "loras") == (inner.id, "loras")
    finally:
        s.close()


def _slow_then_ranged(server: Server, slow: dict[str, bool]) -> None:
    def handler(request):
        if slow["on"]:
            return httpx.Response(200, headers={"Content-Length": str(len(BODY)), "ETag": '"v1"'}, stream=DroppingStream(BODY, delay=0.05))
        return ranged(request, BODY)

    server.handler = handler


def _paused_job_in_root(tmp_path, monkeypatch):
    server = Server()
    slow = {"on": True}
    _slow_then_ranged(server, slow)
    monkeypatch.setattr(manager_module, "wait_backoff", lambda control, attempt, retry_after: None)
    s = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(server))
    s.downloads.start()
    root_dir = tmp_path / "disk1" / "models"
    (root_dir / "loras").mkdir(parents=True)
    root = s.library.add_root(RootCreate(name="m", path=str(root_dir), layout="comfyui"))
    req = DownloadCreate(url="https://files.example/m.safetensors", root_id=root.id, rel_dir="loras", expected_sha256=SHA)
    job = s.downloads.create(req)
    _wait_for(lambda: s.downloads.get(job.id).bytes_done > 0)
    s.downloads.pause(job.id)
    assert s.downloads.wait(job.id, timeout=10).state == "paused"
    return s, server, slow, root, root_dir, job, req


def test_a_paused_download_resumes_where_its_root_is_now(tmp_path, monkeypatch):
    s, server, slow, root, root_dir, job, req = _paused_job_in_root(tmp_path, monkeypatch)
    try:
        moved = tmp_path / "disk2" / "models"
        moved.parent.mkdir()
        shutil.move(str(root_dir), str(moved))
        s.library.update_root(root.id, RootUpdate(path=str(moved)))
        slow["on"] = False
        again = s.downloads.create(req)  # the same file and folder: the paused job, not a second one
        assert again.id == job.id
        done = s.downloads.wait(job.id, timeout=10)
        assert done.state == "completed", done.error
        assert (moved / "loras" / "m.safetensors").read_bytes() == BODY
        assert "Range" in server.requests[-1].headers  # continued from the .part that moved with the folder
        assert Path(done.dest_dir) == (moved / "loras").resolve()
        assert not root_dir.exists()  # the old place was not made again
    finally:
        s.close()


def test_a_download_whose_root_is_gone_fails_instead_of_recreating_it(tmp_path, monkeypatch):
    s, _, slow, _, root_dir, job, _ = _paused_job_in_root(tmp_path, monkeypatch)
    try:
        shutil.move(str(root_dir), str(tmp_path / "elsewhere"))
        slow["on"] = False
        s.downloads.resume(job.id)
        failed = s.downloads.wait(job.id, timeout=10)
        assert failed.state == "failed" and "missing" in (failed.error or "")
        assert not root_dir.exists()
        s.downloads.remove(job.id)  # nothing to discard where the root was
    finally:
        s.close()


def test_forgetting_a_folder_spares_look_alike_names(services, tmp_path):
    from hanakura.core.detection.models import DetectionResult

    folder = tmp_path / "a_b"
    other = tmp_path / "axb"
    for f in (folder, other):
        f.mkdir()
        (f / "m.safetensors").write_bytes(b"x")
    for f in (folder, other):
        services.detection.store(f / "m.safetensors", DetectionResult(kind="lora"), {})
    services.detection.forget(folder)
    assert services.detection.cached(folder / "m.safetensors") is None
    assert services.detection.cached(other / "m.safetensors") is not None


def test_a_relative_settings_file_is_fixed_at_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = SettingsService(data_dir=tmp_path / "data", settings_path=Path("conf/hanakura.toml"))
    assert settings.path == tmp_path.resolve() / "conf" / "hanakura.toml"
