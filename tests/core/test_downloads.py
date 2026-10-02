import hashlib
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from hanakura.core.context import build_services
from hanakura.core.downloads import manager as manager_module
from hanakura.core.downloads.models import DownloadCreate, DownloadJob, SourceFileRef
from hanakura.core.errors import ConflictError, ValidationError

BODY = bytes(range(256)) * 4096  # 1 MiB
SHA = hashlib.sha256(BODY).hexdigest()


class Server:
    """A fake upstream. Each test sets ``handler``; every request is recorded."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler = lambda request: httpx.Response(404)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


class DroppingStream(httpx.SyncByteStream):
    """Yields ``data`` in chunks, then fails with a network error after ``fail_after`` bytes."""

    def __init__(self, data: bytes, fail_after: int | None = None, delay: float = 0.0) -> None:
        self.data = data
        self.fail_after = fail_after
        self.delay = delay

    def __iter__(self) -> Iterator[bytes]:
        sent = 0
        for i in range(0, len(self.data), 65536):
            if self.fail_after is not None and sent >= self.fail_after:
                raise httpx.ReadError("connection dropped")
            if self.delay:
                time.sleep(self.delay)
            chunk = self.data[i : i + 65536]
            sent += len(chunk)
            yield chunk


def ranged(request: httpx.Request, data: bytes, etag: str | None = '"v1"', **headers: str) -> httpx.Response:
    rng = request.headers.get("Range")
    extra = {"ETag": etag} if etag else {}
    if rng and (request.headers.get("If-Range") in (None, etag)):
        start = int(rng.split("=")[1].rstrip("-"))
        return httpx.Response(
            206, headers={"Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}", "Content-Length": str(len(data) - start), **extra, **headers}, content=data[start:]
        )
    return httpx.Response(200, headers={"Content-Length": str(len(data)), **extra, **headers}, content=data)


@pytest.fixture
def server() -> Server:
    return Server()


@pytest.fixture
def hub(tmp_path, server, monkeypatch):
    monkeypatch.setattr(manager_module, "wait_backoff", lambda control, attempt, retry_after: None)
    s = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(server))
    s.settings.update({"network": {"max_retries": 3}})
    s.downloads.start()
    yield s
    s.close()


def run(services, req: DownloadCreate, timeout: float = 10) -> DownloadJob:
    job = services.downloads.create(req)
    return services.downloads.wait(job.id, timeout=timeout)


def test_url_download_with_content_disposition_and_hash(hub, server, tmp_path):
    server.handler = lambda r: httpx.Response(200, headers={"Content-Disposition": 'attachment; filename="nice name.safetensors"'}, content=BODY)
    job = run(hub, DownloadCreate(url="https://files.example/dl?id=1", dest_dir=str(tmp_path / "out"), expected_sha256=SHA))
    assert job.state == "completed", job.error
    final = tmp_path / "out" / "nice name.safetensors"
    assert final.read_bytes() == BODY and job.sha256 == SHA
    sidecar = json.loads((tmp_path / "out" / "nice name.hanakura.json").read_text())
    assert sidecar["url"] == "https://files.example/dl?id=1"
    assert not list((tmp_path / "out").glob("*.part"))


def test_hash_mismatch_fails_and_removes_part(hub, server, tmp_path):
    server.handler = lambda r: httpx.Response(200, content=BODY)
    job = run(hub, DownloadCreate(url="https://files.example/model.bin", dest_dir=str(tmp_path), expected_sha256="0" * 64))
    assert job.state == "failed" and "SHA256 mismatch" in job.error
    assert not (tmp_path / "model.bin").exists() and not (tmp_path / "model.bin.part").exists()


def test_resume_after_connection_drop_uses_range(hub, server, tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, headers={"Content-Length": str(len(BODY)), "ETag": '"v1"'}, stream=DroppingStream(BODY, fail_after=300_000))
        return ranged(request, BODY)

    server.handler = handler
    job = run(hub, DownloadCreate(url="https://files.example/m.safetensors", dest_dir=str(tmp_path), expected_sha256=SHA))
    assert job.state == "completed", job.error
    assert (tmp_path / "m.safetensors").read_bytes() == BODY
    second = server.requests[1]
    assert second.headers["Range"].startswith("bytes=") and second.headers["If-Range"] == '"v1"'


def test_resume_without_validator_restarts_when_size_changed(hub, server, tmp_path):
    """Civitai sends no ETag: resume only when the total size still matches."""
    other = BODY + b"extra"
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, headers={"Content-Length": str(len(BODY))}, stream=DroppingStream(BODY, fail_after=300_000))
        return ranged(request, other, etag=None)

    server.handler = handler
    job = run(hub, DownloadCreate(url="https://files.example/c.bin", dest_dir=str(tmp_path)))
    assert job.state == "completed", job.error
    assert (tmp_path / "c.bin").read_bytes() == other
    assert "Range" not in server.requests[-1].headers


def test_429_retry_after_is_retried(hub, server, tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"ok")

    server.handler = handler
    job = run(hub, DownloadCreate(url="https://files.example/r.txt", dest_dir=str(tmp_path)))
    assert job.state == "completed" and job.attempts == 1


def test_gives_up_after_max_retries(hub, server, tmp_path):
    server.handler = lambda r: httpx.Response(503)
    job = run(hub, DownloadCreate(url="https://files.example/x.bin", dest_dir=str(tmp_path)))
    assert job.state == "failed" and "gave up" in job.error


def test_cancel_mid_stream_removes_part(hub, server, tmp_path):
    server.handler = lambda r: httpx.Response(200, headers={"Content-Length": str(len(BODY))}, stream=DroppingStream(BODY, delay=0.05))
    job = hub.downloads.create(DownloadCreate(url="https://files.example/slow.bin", dest_dir=str(tmp_path)))
    _wait_for(lambda: hub.downloads.get(job.id).bytes_done > 0)
    hub.downloads.cancel(job.id)
    done = hub.downloads.wait(job.id, timeout=10)
    assert done.state == "cancelled"
    assert not (tmp_path / "slow.bin.part").exists() and not (tmp_path / "slow.bin").exists()


def test_pause_and_resume(hub, server, tmp_path):
    slow = {"on": True}

    def handler(request):
        if slow["on"]:
            return httpx.Response(200, headers={"Content-Length": str(len(BODY)), "ETag": '"v1"'}, stream=DroppingStream(BODY, delay=0.05))
        return ranged(request, BODY)

    server.handler = handler
    job = hub.downloads.create(DownloadCreate(url="https://files.example/p.bin", dest_dir=str(tmp_path), expected_sha256=SHA))
    _wait_for(lambda: hub.downloads.get(job.id).bytes_done > 0)
    hub.downloads.pause(job.id)
    paused = hub.downloads.wait(job.id, timeout=10)
    assert paused.state == "paused" and (tmp_path / "p.bin.part").exists()
    slow["on"] = False
    hub.downloads.resume(job.id)
    done = hub.downloads.wait(job.id, timeout=10)
    assert done.state == "completed" and (tmp_path / "p.bin").read_bytes() == BODY
    assert "Range" in server.requests[-1].headers


def test_existing_target_is_a_conflict(hub, tmp_path):
    (tmp_path / "exists.bin").write_bytes(b"x")
    with pytest.raises(ConflictError):
        hub.downloads.create(DownloadCreate(url="https://files.example/exists.bin", dest_dir=str(tmp_path), file_name="exists.bin"))


def test_request_validation(hub, tmp_path):
    with pytest.raises(ValidationError):
        hub.downloads.create(DownloadCreate(dest_dir=str(tmp_path)))
    with pytest.raises(ValidationError):
        hub.downloads.create(DownloadCreate(url="file:///etc/passwd", dest_dir=str(tmp_path)))


def test_hub_jobs_cannot_pause(hub, tmp_path):
    job = DownloadJob(id=999, runner="huggingface", title="t", dest_dir=str(tmp_path), created_at=manager_module._now())
    hub.downloads._save(job)
    assert job.can_pause is False
    with pytest.raises(ConflictError):
        hub.downloads.pause(999)


def test_running_jobs_become_paused_on_restart(tmp_path, server):
    s = build_services(data_dir=tmp_path / "data", environ={}, transport=httpx.MockTransport(server))
    s.downloads._save(DownloadJob(id=1, runner="http", title="t", url="https://x/y", dest_dir=str(tmp_path), state="running", created_at=manager_module._now()))
    s.downloads._save(DownloadJob(id=2, runner="modelscope", title="t", dest_dir=str(tmp_path), state="running", created_at=manager_module._now()))
    s.downloads.start()
    try:
        assert s.downloads.get(1).state == "paused"
        assert s.downloads.get(2).state == "failed"
    finally:
        s.close()


CIVITAI_MODEL = {
    "id": 7,
    "name": "Detail Tweaker",
    "type": "LORA",
    "creator": {"username": "someone"},
    "stats": {"downloadCount": 5},
    "tags": ["detail"],
    "modelVersions": [
        {
            "id": 70,
            "name": "v1",
            "baseModel": "SDXL 1.0",
            "trainedWords": ["detailed"],
            "images": [{"url": "https://image.civitai.com/x/abc/width=1024/1.jpeg", "type": "image", "nsfwLevel": 1}],
            "files": [
                {
                    "id": 700,
                    "name": "detail.safetensors",
                    "sizeKB": len(BODY) / 1024,
                    "type": "Model",
                    "primary": True,
                    "downloadUrl": "https://civitai.com/api/download/models/70",
                    "hashes": {"SHA256": SHA.upper()},
                }
            ],
        }
    ],
}


def test_civitai_download_token_stays_on_civitai(hub, server, tmp_path):
    hub.settings.update({"sources": {"civitai": {"token": "SECRET"}}, "downloads": {"write_webui_metadata": True}})

    def handler(request: httpx.Request):
        url = str(request.url)
        if url == "https://civitai.com/api/v1/models/7":
            return httpx.Response(200, json=CIVITAI_MODEL)
        if url == "https://civitai.com/api/download/models/70":
            return httpx.Response(307, headers={"Location": "https://storage.example/signed/abc"})
        if url.startswith("https://storage.example/"):
            return httpx.Response(200, headers={"Content-Disposition": 'attachment; filename="detail.safetensors"'}, content=BODY)
        if url.startswith("https://image.civitai.com/"):
            return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"jpeg")
        return httpx.Response(404)

    server.handler = handler
    job = run(hub, DownloadCreate(source_file=SourceFileRef(source="civitai", model_id="7"), dest_dir=str(tmp_path)))
    assert job.state == "completed", job.error
    by_host = {r.url.host: r for r in server.requests}
    assert by_host["civitai.com"].headers.get("Authorization") == "Bearer SECRET"
    assert "Authorization" not in by_host["storage.example"].headers
    assert "Authorization" not in by_host["image.civitai.com"].headers
    assert all("SECRET" not in str(r.url) for r in server.requests)
    meta = json.loads((tmp_path / "detail.hanakura.json").read_text())
    assert meta["model_id"] == "7" and meta["base_model"] == "sdxl" and meta["trained_words"] == ["detailed"]
    assert (tmp_path / "detail.preview.jpg").read_bytes() == b"jpeg"
    webui = json.loads((tmp_path / "detail.json").read_text())
    assert webui["activation text"] == "detailed" and webui["sd version"] == "SDXL"


def _wait_for(cond, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


def test_hub_runner_reports_worker_failure_and_cancel(tmp_path):
    """The child process is replaced by a fake worker; cancel must terminate it."""
    from hanakura.core.downloads.hub_runner import run_hub_download
    from hanakura.core.downloads.job import JobControl, JobStopped
    from hanakura.core.errors import HanakuraError
    from hanakura.core.hubs.huggingface import HuggingFaceAdapter
    from hanakura.core.hubs.models import RepoFile
    from hanakura.core.settings.models import SourceSettings

    adapter = HuggingFaceAdapter(lambda: httpx.Client(), lambda: SourceSettings())
    files = [RepoFile(path="a.safetensors", size=10)]
    failing = tmp_path / "fail.py"
    failing.write_text('import sys, json; sys.stdin.readline(); print("@@MH " + json.dumps({"event": "error", "message": "boom"})); sys.exit(1)\n')
    with pytest.raises(HanakuraError, match="boom"):
        run_hub_download(adapter, "o/r", None, files, tmp_path / "dest", False, JobControl(), lambda d, t: None, worker_path=str(failing))

    sleepy = tmp_path / "sleep.py"
    sleepy.write_text("import sys, time, pathlib; sys.stdin.readline(); pathlib.Path('a.safetensors.incomplete').write_bytes(b'12345'); time.sleep(30)\n")
    control = JobControl()
    progress: list[int] = []
    threading.Timer(0.8, lambda: control.request("cancelled")).start()
    started = time.monotonic()
    with pytest.raises(JobStopped):
        run_hub_download(adapter, "o/r", None, files, tmp_path / "dest2", False, control, lambda d, t: progress.append(d), worker_path=str(sleepy))
    assert time.monotonic() - started < 10
    assert not (tmp_path / "dest2" / "a.safetensors.incomplete").exists()

    fake_ok = tmp_path / "ok.py"
    fake_ok.write_text("import sys, pathlib; sys.stdin.readline(); pathlib.Path('a.safetensors').write_bytes(b'short')\n")
    with pytest.raises(HanakuraError, match="expected 10"):
        run_hub_download(adapter, "o/r", None, files, tmp_path / "dest3", False, JobControl(), lambda d, t: None, worker_path=str(fake_ok))


def test_file_name_parsing():
    from hanakura.core.downloads.http_downloader import file_name_from_headers, sanitize_file_name

    r = httpx.Response(200, headers={"Content-Disposition": "attachment; filename*=UTF-8''%E6%A8%A1%E5%9E%8B.safetensors"})
    assert file_name_from_headers(r) == "模型.safetensors"
    assert sanitize_file_name("../../etc/passwd") == "passwd"
    assert sanitize_file_name("CON") == "download.bin"
    assert Path(sanitize_file_name('a<b>:c"d.bin')).name == "a_b__c_d.bin"


def test_job_events_carry_a_snapshot_of_the_state_they_announce(hub, server, tmp_path):
    """A subscriber may serialize an event long after it was published; the payload must not move."""
    from hanakura.core.events.models import DownloadJobEvent

    server.handler = lambda r: httpx.Response(200, headers={"Content-Length": str(len(BODY))}, stream=DroppingStream(BODY, delay=0.01))
    seen: list[DownloadJobEvent] = []
    hub.events.subscribe(lambda e: seen.append(e) if isinstance(e, DownloadJobEvent) else None)

    job = run(hub, DownloadCreate(url="https://files.example/s.safetensors", dest_dir=str(tmp_path / "out")))
    assert job.state == "completed", job.error

    announced = {e.__event_name__: e.job for e in seen}
    assert set(announced) == {"download_queued", "download_started", "download_completed"}
    assert announced["download_queued"].state == "queued"
    assert announced["download_started"].state == "running"
    assert announced["download_started"].bytes_done == 0
    assert announced["download_completed"].state == "completed"
