"""Sidecar files next to a model.

This program writes ``<stem>.hanakura.json``. The name ``<stem>.json`` belongs to the Stable
Diffusion WebUI's metadata editor; it is read for display and only ever created, never modified.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from hanakura.core.detection.models import normalize_base_model, normalize_kind
from hanakura.core.library.models import SidecarHint

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".hanakura.json"
WEBUI_KEYS = ("description", "sd version", "activation text", "preferred weight", "negative text", "notes")
MAX_SIDECAR_BYTES = 8 * 1024 * 1024


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_SIDECAR_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_hanakura(directory: Path, stem: str) -> dict[str, Any] | None:
    return _read_json(directory / f"{stem}{SIDECAR_SUFFIX}")


def read_webui(directory: Path, stem: str) -> dict[str, Any] | None:
    data = _read_json(directory / f"{stem}.json")
    if data is None:
        return None
    return {k: data[k] for k in WEBUI_KEYS if k in data}


def read_description(directory: Path, stem: str) -> str | None:
    for name in (f"{stem}.txt", f"{stem}.description.txt"):
        path = directory / name
        try:
            if path.is_file() and path.stat().st_size <= MAX_SIDECAR_BYTES:
                return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def read_civitai_info(directory: Path, stem: str) -> dict[str, Any] | None:
    data = _read_json(directory / f"{stem}.civitai.info")
    if data is None:
        return None
    model = data.get("model")
    if not isinstance(model, dict):
        model = {}
    return {
        "model_id": data.get("modelId"),
        "version_id": data.get("id"),
        "model_name": model.get("name"),
        "version_name": data.get("name"),
        "type": model.get("type"),
        "base_model": data.get("baseModel"),
        "trained_words": data.get("trainedWords") or [],
    }


def sidecar_hint(directory: Path, stem: str) -> SidecarHint | None:
    """What the sidecars say the model is, strongest source first."""
    hub = read_hanakura(directory, stem)
    if hub:
        kind = hub.get("kind")
        base = hub.get("base_model")
        if kind or base:
            return SidecarHint(source="hanakura", kind=normalize_kind(kind) or kind, base_model=normalize_base_model(base) or base)
    info = read_civitai_info(directory, stem)
    if info and (info.get("type") or info.get("base_model")):
        return SidecarHint(source="civitai.info", kind=normalize_kind(info.get("type")), base_model=normalize_base_model(info.get("base_model")))
    webui = read_webui(directory, stem)
    if webui and webui.get("sd version"):
        base = normalize_base_model(str(webui["sd version"]))
        if base:
            return SidecarHint(source="webui", base_model=base)
    return None


def write_hanakura(model_path: Path, data: dict[str, Any]) -> Path:
    stem = model_path.name if model_path.is_dir() else model_path.name.rsplit(".", 1)[0]
    target = model_path.parent / f"{stem}{SIDECAR_SUFFIX}"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, target)
    return target


def write_webui_if_absent(model_path: Path, description: str | None, sd_version: str | None, activation_text: str | None) -> Path | None:
    """Create a WebUI-compatible ``<stem>.json``. Never touches one that exists."""
    stem = model_path.name.rsplit(".", 1)[0]
    target = model_path.parent / f"{stem}.json"
    data = {"description": description or "", "sd version": sd_version or "Unknown", "activation text": activation_text or "", "preferred weight": 0, "notes": ""}
    try:
        with open(target, "x", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except FileExistsError:
        return None
    return target
