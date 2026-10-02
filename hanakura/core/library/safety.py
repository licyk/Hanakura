"""Path safety. Every library operation resolves client paths through these functions."""

import re
from pathlib import Path

from hanakura.core.errors import InvalidPathError

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_ILLEGAL_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\/]')
MAX_NAME_LENGTH = 255


def validate_name(name: str) -> str:
    """Return ``name`` if it is a safe single path component, else raise InvalidPathError."""
    if not name or name in (".", ".."):
        raise InvalidPathError(f"Invalid name: {name!r}")
    if _ILLEGAL_CHARS.search(name):
        raise InvalidPathError(f"Name contains a path separator or a forbidden character: {name!r}")
    if name != name.strip() or name.endswith("."):
        raise InvalidPathError(f"Name must not start or end with a space, or end with a dot: {name!r}")
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise InvalidPathError(f"Name is reserved on Windows: {name!r}")
    if len(name.encode("utf-8")) > MAX_NAME_LENGTH:
        raise InvalidPathError("Name is too long")
    return name


def split_rel(rel_path: str) -> list[str]:
    """Split a client-supplied relative path into validated components."""
    if rel_path is None:
        return []
    text = rel_path.replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise InvalidPathError(f"Path must be relative: {rel_path!r}")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    for part in parts:
        validate_name(part)
    return parts


def resolve_in_root(root: Path, rel_path: str, follow_symlinks: bool = False) -> Path:
    """Turn a client-supplied relative path into an absolute path inside ``root``.

    ``rel_path`` never contains ``..``, an absolute path or a reserved name: ``split_rel``
    rejects those, so the result is always under ``root`` by name.

    By default the path is also resolved, and a result outside the root is refused, which
    rejects symlinks that escape. With ``follow_symlinks`` the path is kept as written, so a
    symlinked folder inside the root can be opened even though it points elsewhere. The path
    stays the one relative to the root, which is what the client navigates with.
    """
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*split_rel(rel_path))
    if follow_symlinks:
        return candidate
    resolved = candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise InvalidPathError(f"Path escapes its root: {rel_path!r}. A symbolic link leads outside the root; turn on library.follow_symlinks to open it.")
    return resolved


def escapes_root(root: Path, path: Path) -> bool:
    """Whether ``path`` really lies outside ``root`` once symlinks are resolved."""
    root_resolved = root.resolve()
    resolved = path.resolve()
    return resolved != root_resolved and root_resolved not in resolved.parents


def to_rel(root: Path, path: Path) -> str:
    """Return ``path`` relative to ``root`` in POSIX form.

    The name-based relation is tried first, so a path reached through a symlink inside the root
    keeps the relative path the client navigates with.
    """
    for base, target in ((root, path), (root.resolve(), path.resolve())):
        try:
            rel = target.relative_to(base)
        except ValueError:
            continue
        return "" if rel == Path() else rel.as_posix()
    raise InvalidPathError(f"{path} is not inside {root}")


def unique_path(path: Path) -> Path:
    """Return ``path``, or the first ``name_N.ext`` next to it that does not exist."""
    if not path.exists() and not path.is_symlink():
        return path
    stem, suffix = split_model_name(path.name)
    for i in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise InvalidPathError("Could not find a free name")


def split_model_name(name: str) -> tuple[str, str]:
    """Split ``name`` into stem and extension, keeping the last suffix only."""
    if "." in name.lstrip("."):
        stem, _, ext = name.rpartition(".")
        return stem, "." + ext
    return name, ""
