"""Directory scanning: models, their companions and their previews."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from hanakura.core.library.safety import split_model_name

IGNORED_SUFFIXES = (".incomplete", ".part", ".tmp")


def is_ignored(name: str) -> bool:
    """Dot entries and unfinished downloads are never shown."""
    return name.startswith(".") or name.endswith(IGNORED_SUFFIXES)


@dataclass
class ScannedModel:
    path: Path
    is_dir: bool
    stem: str
    companions: list[Path] = field(default_factory=list)
    preview: Path | None = None
    is_model: bool = True
    """False for a plain file listed only because ``library.show_all_files`` is on."""


@dataclass
class ScannedDir:
    folders: list[Path]
    models: list[ScannedModel]


def model_stem(path: Path, is_dir: bool) -> str:
    return path.name if is_dir else split_model_name(path.name)[0]


def find_preview(stem: str, candidates: set[str], preview_extensions: list[str]) -> str | None:
    """Follow the WebUI's lookup: for each extension, ``<stem>.<ext>`` then ``<stem>.preview.<ext>``."""
    lowered = {c.lower(): c for c in candidates}
    for ext in preview_extensions:
        for name in (f"{stem}{ext}", f"{stem}.preview{ext}"):
            hit = lowered.get(name.lower())
            if hit is not None:
                return hit
    return None


def scan_dir(directory: Path, model_extensions: list[str], preview_extensions: list[str], include_other_files: bool = False) -> ScannedDir:
    """List one directory: subfolders, and models with their companions and preview.

    With ``include_other_files``, every file no model claimed as a companion is listed too, so a
    folder reads like one in a file manager. A preview or a sidecar stays with its model rather
    than appearing twice.
    """
    model_exts = {e.lower() for e in model_extensions}
    folders: list[Path] = []
    models: list[ScannedModel] = []
    others: list[Path] = []
    with os.scandir(directory) as it:
        for entry in it:
            if is_ignored(entry.name):
                continue
            path = Path(entry.path)
            if entry.is_dir():
                if (path / "model_index.json").is_file():
                    models.append(ScannedModel(path, True, entry.name))
                else:
                    folders.append(path)
            elif entry.is_file():
                if path.suffix.lower() in model_exts:
                    models.append(ScannedModel(path, False, model_stem(path, False)))
                else:
                    others.append(path)
    assign_companions(models, others)
    other_names = {p.name for p in others}
    for model in models:
        names = {c.name for c in model.companions} & other_names
        preview = find_preview(model.stem, names, preview_extensions)
        model.preview = directory / preview if preview else None
    if include_other_files:
        claimed = {c for m in models for c in m.companions}
        # The whole name is the stem of a plain file: it owns no companions and no sidecar.
        models.extend(ScannedModel(p, False, p.name, is_model=False) for p in others if p not in claimed)
    folders.sort(key=lambda p: p.name.lower())
    models.sort(key=lambda m: (not m.is_model, m.path.name.lower()))
    return ScannedDir(folders, models)


def assign_companions(models: list[ScannedModel], others: list[Path]) -> None:
    """Give each non-model file to the model with the longest stem it starts with.

    ``a.png`` belongs to ``a.safetensors``, but ``a.b.png`` belongs to ``a.b.safetensors`` when that
    model exists beside it.
    """
    by_length = sorted(models, key=lambda m: -len(m.stem))
    for other in others:
        for model in by_length:
            if other.name.startswith(model.stem + "."):
                model.companions.append(other)
                break
    for model in models:
        model.companions.sort(key=lambda p: p.name)


def companions_of(model_path: Path, model_extensions: list[str]) -> list[Path]:
    """Return the companion files of one model, looking at its directory."""
    directory = model_path.parent
    is_dir = model_path.is_dir()
    stem = model_stem(model_path, is_dir)
    model_exts = {e.lower() for e in model_extensions}
    models: list[ScannedModel] = [ScannedModel(model_path, is_dir, stem)]
    others: list[Path] = []
    with os.scandir(directory) as it:
        for entry in it:
            if entry.name == model_path.name or not entry.name.startswith(stem + ".") or is_ignored(entry.name):
                continue
            path = Path(entry.path)
            if entry.is_dir():
                if (path / "model_index.json").is_file():
                    models.append(ScannedModel(path, True, entry.name))
            elif path.suffix.lower() in model_exts:
                models.append(ScannedModel(path, False, model_stem(path, False)))
            else:
                others.append(path)
    assign_companions(models, others)
    return models[0].companions
