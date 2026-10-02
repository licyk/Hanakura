"""Child process that downloads repository files with a hub library.

The parent writes one JSON object to standard input and reads JSON lines, prefixed with
``@@MH``, from standard output. Cancelling means terminating this process: raising from a
library's progress hook stops neither library: Hugging Face carried on to the end of the file,
and ModelScope retried and then returned as though nothing had happened.
"""

import json
import os
import sys
import traceback
from typing import Any, TypedDict

# Run as a script, this file's folder is sys.path[0], where hubs/modelscope.py would shadow the
# real modelscope package. Drop it before any library import.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != _HERE]

PREFIX = "@@MH "


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(PREFIX + json.dumps(event) + "\n")
    sys.stdout.flush()


def download_huggingface(cfg: dict[str, Any]) -> None:
    from huggingface_hub import hf_hub_download

    for path in cfg["files"]:
        hf_hub_download(
            cfg["repo_id"],
            path,
            revision=cfg.get("revision"),
            local_dir=cfg["local_dir"],
            endpoint=cfg.get("endpoint") or None,
            token=cfg.get("token") or False,
            force_download=bool(cfg.get("overwrite")),
        )
        emit({"event": "file_done", "path": path})


class _ModelScopeOptions(TypedDict, total=False):
    revision: str
    token: str
    endpoint: str


def download_modelscope(cfg: dict[str, Any]) -> None:
    from modelscope.hub.file_download import model_file_download

    # Omitted options retain the library's defaults, whose annotations do not accept None.
    options: _ModelScopeOptions = {}
    if (revision := cfg.get("revision")) is not None:
        options["revision"] = revision
    for key in ("token", "endpoint"):
        if value := cfg.get(key):
            options[key] = value
    for path in cfg["files"]:
        model_file_download(
            cfg["repo_id"],
            path,
            local_dir=cfg["local_dir"],
            **options,
        )
        emit({"event": "file_done", "path": path})


def main() -> int:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        cfg = json.loads(sys.stdin.readline())
    except ValueError as e:
        emit({"event": "error", "message": f"bad worker config: {e}"})
        return 2
    emit({"event": "start", "pid": os.getpid()})
    try:
        if cfg["hub"] == "huggingface":
            download_huggingface(cfg)
        elif cfg["hub"] == "modelscope":
            download_modelscope(cfg)
        else:
            raise ValueError(f"unknown hub {cfg['hub']}")
    except BaseException as e:  # noqa: BLE001 - report everything to the parent
        traceback.print_exc(file=sys.stderr)
        emit({"event": "error", "message": f"{type(e).__name__}: {e}"})
        return 1
    emit({"event": "done"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
