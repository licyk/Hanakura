"""Run a hub download in a child process, with progress from polling and cancel by terminating."""

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hanakura.core.downloads.job import JobControl, JobStopped
from hanakura.core.errors import HanakuraError
from hanakura.core.hubs import worker as worker_module
from hanakura.core.hubs.base import HubAdapter
from hanakura.core.hubs.models import RepoFile

POLL_INTERVAL = 0.5
TERMINATE_GRACE = 5.0


def _incomplete_files(local_dir: Path, files: list[RepoFile]) -> list[Path]:
    """Leftovers of both libraries: HF under ``.cache/huggingface/download``, ModelScope beside the target."""
    out: list[Path] = []
    hf_cache = local_dir / ".cache" / "huggingface" / "download"
    if hf_cache.is_dir():
        out.extend(hf_cache.rglob("*.incomplete"))
    for f in files:
        p = local_dir / f"{f.path}.incomplete"
        if p.exists():
            out.append(p)
    return out


def cleanup_incomplete(local_dir: Path, files: list[RepoFile]) -> None:
    for p in _incomplete_files(local_dir, files):
        try:
            p.unlink()
        except OSError:
            pass


def measure(local_dir: Path, files: list[RepoFile], done_paths: set[str]) -> int:
    total = 0
    for f in files:
        target = local_dir / f.path
        if f.path in done_paths and target.exists():
            total += target.stat().st_size
    for p in _incomplete_files(local_dir, files):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def verify(local_dir: Path, files: list[RepoFile]) -> list[str]:
    """Return problems: missing files or wrong sizes. A normal return from a library proves nothing."""
    problems = []
    for f in files:
        target = local_dir / f.path
        if not target.is_file():
            problems.append(f"missing {f.path}")
        elif f.size is not None and target.stat().st_size != f.size:
            problems.append(f"{f.path}: {target.stat().st_size} bytes, expected {f.size}")
    return problems


def run_hub_download(
    adapter: HubAdapter,
    repo_id: str,
    revision: str | None,
    files: list[RepoFile],
    local_dir: Path,
    overwrite: bool,
    control: JobControl,
    on_progress: Callable[[int, int | None], None],
    worker_path: str | None = None,
) -> None:
    """Download ``files`` into ``local_dir`` through the worker. ``worker_path`` replaces the worker in tests."""
    local_dir.mkdir(parents=True, exist_ok=True)
    total = sum(f.size or 0 for f in files) or None
    config: dict[str, Any] = {
        "hub": adapter.id,
        "repo_id": repo_id,
        "revision": revision,
        "files": [f.path for f in files],
        "local_dir": str(local_dir),
        "overwrite": overwrite,
        **adapter.worker_config(),
    }
    env = {**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1", "PYTHONUNBUFFERED": "1"}
    control.check()
    proc = subprocess.Popen(
        [sys.executable, worker_path or worker_module.__file__],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(local_dir),
    )
    control.process = proc
    done_paths: set[str] = set()
    errors: list[str] = []
    stderr_tail: list[str] = []

    def read_stdout() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line.startswith(worker_module.PREFIX):
                continue
            try:
                event = json.loads(line[len(worker_module.PREFIX) :])
            except ValueError:
                continue
            if event.get("event") == "file_done":
                done_paths.add(event.get("path", ""))
            elif event.get("event") == "error":
                errors.append(str(event.get("message")))

    def read_stderr() -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip())
            del stderr_tail[:-20]

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for t in readers:
        t.start()
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(config) + "\n").encode("utf-8"))
    proc.stdin.close()

    try:
        while proc.poll() is None:
            if control.stop_reason is not None:
                _terminate(proc)
                cleanup_incomplete(local_dir, files)
                raise JobStopped(control.stop_reason)
            done = measure(local_dir, files, done_paths)
            on_progress(min(done, total) if total else done, total)
            control.event.wait(POLL_INTERVAL)
    finally:
        control.process = None
    for t in readers:
        t.join(timeout=2)

    if proc.returncode != 0 or errors:
        cleanup_incomplete(local_dir, files)
        message = errors[-1] if errors else (stderr_tail[-1] if stderr_tail else f"worker exited with status {proc.returncode}")
        raise HanakuraError(message)
    problems = verify(local_dir, files)
    if problems:
        cleanup_incomplete(local_dir, files)
        raise HanakuraError("Download incomplete: " + "; ".join(problems[:5]))
    on_progress(total or 0, total)


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
