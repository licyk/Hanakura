"""``server.json`` in the data directory, so other programs can find the running server."""

import json
import os
from pathlib import Path
from typing import Any

RUNTIME_FILE_NAME = "server.json"


def write_runtime_file(data_dir: Path, host: str, port: int, url: str) -> Path:
    path = data_dir / RUNTIME_FILE_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"host": host, "port": port, "url": url, "pid": os.getpid()}), encoding="utf-8")
    os.replace(tmp, path)
    return path


def remove_runtime_file(data_dir: Path) -> None:
    path = data_dir / RUNTIME_FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if data.get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_runtime_file(data_dir: Path) -> dict[str, Any] | None:
    """Return the runtime file's contents, or None if it is missing or stale."""
    try:
        data = json.loads((data_dir / RUNTIME_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None
    return data
