"""The local library: roots, browsing and file operations."""

import logging
import os
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal

from sd_model_hub.core.detection import DetectionService
from sd_model_hub.core.detection.models import DETECTABLE_KINDS, kinds_compatible
from sd_model_hub.core.errors import ConflictError, InvalidPathError, ModelHubError, NotFoundError, ValidationError
from sd_model_hub.core.events import EventBus
from sd_model_hub.core.events.models import ImportProgressEvent, LibraryChangedEvent
from sd_model_hub.core.library import sidecar
from sd_model_hub.core.library.fsops import copy_path, move_path, remove_path, rename_no_overwrite
from sd_model_hub.core.library.layouts import LAYOUTS, default_folder, folder_kind
from sd_model_hub.core.library.models import (
    COMBINED_VIEW_ID,
    CombinedFolder,
    CombinedListing,
    DeleteRequest,
    FolderCreate,
    FolderEntry,
    FolderListing,
    ImportRequest,
    ModelEntry,
    ModelInfo,
    MoveRequest,
    OperationResult,
    PathRef,
    RenameRequest,
    RootCreate,
    RootInfo,
    RootUpdate,
    TrashLocation,
    TreeNode,
)
from sd_model_hub.core.library.previews import ScannedModel, companions_of, find_preview, is_ignored, model_stem, scan_dir
from sd_model_hub.core.library.safety import escapes_root, resolve_in_root, to_rel, unique_path, validate_name
from sd_model_hub.core.settings import ModelRoot, SettingsService
from sd_model_hub.core.settings.models import DownloadDestination

logger = logging.getLogger(__name__)

DetectMode = Literal["full", "cached", "none"]


class UploadWriter:
    """Streams an upload into ``<name>.part`` beside the target, then renames it into place."""

    def __init__(self, service: "LibraryService", root_id: str, target: Path, total: int | None) -> None:
        self._service = service
        self.root_id = root_id
        self.target = target
        self.part = target.with_name(target.name + ".part")
        self.total = total
        self.written = 0
        self._last_event = 0.0
        try:
            # Held open across write() calls and closed in commit() or abort().
            self._file: BinaryIO = open(self.part, "xb")  # noqa: SIM115
        except FileExistsError:
            raise ConflictError(f"An upload of {target.name} is already in progress") from None

    def write(self, chunk: bytes) -> None:
        self._file.write(chunk)
        self.written += len(chunk)
        now = time.monotonic()
        if now - self._last_event >= 0.25:
            self._last_event = now
            self._publish(done=False)

    def _publish(self, done: bool) -> None:
        root_path = self._service.root_path(self.root_id)
        self._service.events.publish(ImportProgressEvent(root_id=self.root_id, rel_path=to_rel(root_path, self.target), bytes_done=self.written, total_bytes=self.total, done=done))

    def commit(self) -> PathRef:
        self._file.close()
        if self.total is not None and self.written != self.total:
            self.abort()
            raise ValidationError(f"Upload incomplete: received {self.written} of {self.total} bytes")
        try:
            rename_no_overwrite(self.part, self.target)
        except BaseException:
            self.abort()
            raise
        self._publish(done=True)
        root_path = self._service.root_path(self.root_id)
        self._service.notify_changed(self.root_id, to_rel(root_path, self.target.parent))
        return PathRef(root_id=self.root_id, path=to_rel(root_path, self.target))

    def abort(self) -> None:
        if not self._file.closed:
            self._file.close()
        try:
            self.part.unlink()
        except FileNotFoundError:
            pass


class LibraryService:
    def __init__(self, settings: SettingsService, detection: DetectionService, events: EventBus, roots_locked: bool = False) -> None:
        """``roots_locked`` is for a host application that supplies the model folders itself:
        they cannot then be added, changed or removed, and the interface hides those actions."""
        self.settings = settings
        self.detection = detection
        self.events = events
        self.roots_locked = roots_locked
        self._scan_lock = threading.Lock()
        self._scanning: set[tuple[str, str]] = set()

    # -- roots --------------------------------------------------------------

    def _roots(self) -> list[ModelRoot]:
        return list(self.settings.settings.paths.model_roots)

    def _root(self, root_id: str) -> ModelRoot:
        for root in self._roots():
            if root.id == root_id:
                return root
        raise NotFoundError(f"No model root with id {root_id!r}")

    def root_path(self, root_id: str) -> Path:
        return Path(self._root(root_id).path).expanduser().resolve()

    @staticmethod
    def _info(root: ModelRoot) -> RootInfo:
        return RootInfo(id=root.id, name=root.name, path=root.path, layout=root.layout, exists=Path(root.path).expanduser().is_dir(), kind=root.kind)

    def list_roots(self) -> list[RootInfo]:
        return [self._info(r) for r in self._roots()]

    def get_root(self, root_id: str) -> RootInfo:
        return self._info(self._root(root_id))

    def _check_roots_unlocked(self) -> None:
        if self.roots_locked:
            raise ConflictError("The model folders are fixed by the application that started SD Model Hub and cannot be changed here.")

    def add_root(self, req: RootCreate, *, root_id: str | None = None) -> RootInfo:
        self._check_roots_unlocked()
        if root_id == COMBINED_VIEW_ID:
            raise ValidationError(f"{COMBINED_VIEW_ID!r} is reserved for the combined view and cannot be a root id")
        path = Path(req.path).expanduser()
        if not path.is_absolute():
            raise InvalidPathError("A root path must be absolute")
        path = path.resolve()
        if not path.is_dir():
            raise NotFoundError(f"Not a directory: {path}")
        for existing in self._roots():
            if root_id is not None and existing.id == root_id:
                raise ConflictError(f"Already a root with id {root_id!r}")
            if Path(existing.path).expanduser().resolve() == path:
                raise ConflictError(f"Already a root: {path}", {"root_id": existing.id})
        root = ModelRoot(id=root_id or uuid.uuid4().hex[:8], name=req.name or path.name or str(path), path=str(path), layout=req.layout, kind=req.kind)

        def add(data: dict[str, Any]) -> None:
            data["paths"]["model_roots"].append(root.model_dump())

        self.settings.mutate(add)
        return self._info(root)

    def update_root(self, root_id: str, req: RootUpdate) -> RootInfo:
        self._check_roots_unlocked()
        self._root(root_id)
        changes = req.model_dump(exclude_none=True)
        if "kind" in req.model_dump(exclude_unset=True):
            changes["kind"] = req.kind
        if "path" in changes:
            path = Path(changes["path"]).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise InvalidPathError(f"Not an absolute directory: {path}")
            changes["path"] = str(path.resolve())

        def update(data: dict[str, Any]) -> None:
            for r in data["paths"]["model_roots"]:
                if r["id"] == root_id:
                    r.update(changes)

        self.settings.mutate(update)
        return self.get_root(root_id)

    def remove_root(self, root_id: str) -> None:
        """Forget a root. Files on disk are untouched."""
        self._check_roots_unlocked()
        self._root(root_id)

        def remove(data: dict[str, Any]) -> None:
            data["paths"]["model_roots"] = [r for r in data["paths"]["model_roots"] if r["id"] != root_id]

        self.settings.mutate(remove)

    def locate(self, path: Path) -> tuple[str, str]:
        """Find the root that contains an absolute path. Returns ``(root_id, rel_path)``.

        The path as written is tried first, so a path that runs through a symlinked folder inside
        a root is found there rather than where it really lives.
        """
        given = Path(os.path.abspath(path.expanduser()))
        candidates = [given, given.resolve()] if self.follow_symlinks else [given.resolve()]
        for target in candidates:
            best: tuple[str, Path] | None = None
            for root in self._roots():
                root_path = Path(root.path).expanduser()
                root_path = root_path if target is given else root_path.resolve()
                if (target == root_path or root_path in target.parents) and (best is None or len(str(root_path)) > len(str(best[1]))):
                    best = (root.id, root_path)
            if best is not None:
                return best[0], to_rel(best[1], target)
        for root in self._roots():
            root_path = Path(root.path).expanduser()
            if root_path in given.parents:
                raise InvalidPathError(f"{given} is reached through a symbolic link that leaves its root. Turn on library.follow_symlinks to open it.")
        raise NotFoundError(f"{given} is not inside any model root")

    def default_dest(self, root_id: str, kind: str | None) -> str:
        """The relative folder where a model of ``kind`` goes in this root."""
        root = self._root(root_id)
        destination = self.settings.settings.downloads.kind_destinations.get(kind or "")
        if destination is not None and destination.root_id == root_id:
            return destination.rel_dir
        configured = self.settings.settings.downloads.kind_folders.get(kind or "")
        if configured:
            return configured
        return default_folder(root.layout, self.root_path(root_id), kind or "") if kind else ""

    def suggest_destination(self, kind: str | None = None, root_id: str | None = None, *, rel_dir: str | None = None) -> DownloadDestination:
        """Resolve the same default for API, CLI and UI without creating directories.

        An explicit root wins, followed by the kind mapping, the default root, a root whose
        hint matches the kind, then the first root. Invalid configured roots fail visibly.
        """
        downloads = self.settings.settings.downloads
        configured = downloads.kind_destinations.get(kind or "")
        if root_id is None:
            root_id = configured.root_id if configured is not None else downloads.default_root
        if root_id is None:
            roots = self.list_roots()
            if not roots:
                raise ValidationError("No destination: add a model root, or give a destination folder")
            root_id = next((r.id for r in roots if kind and r.kind == kind), roots[0].id)
        root_path = self.root_path(root_id)
        rel = self.default_dest(root_id, kind) if rel_dir is None else rel_dir
        target = resolve_in_root(root_path, rel, follow_symlinks=self.follow_symlinks)
        return DownloadDestination(root_id=root_id, rel_dir=to_rel(root_path, target))

    @staticmethod
    def _folder_kind(root: ModelRoot, rel_path: str) -> str | None:
        return folder_kind(root.layout, rel_path) or root.kind

    def notify_changed(self, root_id: str, rel_path: str) -> None:
        self.events.publish(LibraryChangedEvent(root_id=root_id, rel_path=rel_path))

    # -- browsing -----------------------------------------------------------

    @property
    def follow_symlinks(self) -> bool:
        """Whether a link leaving a root may be browsed, downloaded into and operated on."""
        return self.settings.settings.library.follow_symlinks

    def _resolve(self, root_id: str, rel_path: str, must_exist: bool = True) -> tuple[ModelRoot, Path, Path]:
        root = self._root(root_id)
        root_path = self.root_path(root_id)
        if not root_path.is_dir():
            raise NotFoundError(f"Root folder is missing: {root_path}")
        target = resolve_in_root(root_path, rel_path, follow_symlinks=self.follow_symlinks)
        if must_exist and not target.exists():
            raise NotFoundError(f"Not found: {rel_path}")
        return root, root_path, target

    def _entry(self, root: ModelRoot, root_path: Path, scanned: ScannedModel, detect: DetectMode) -> tuple[ModelEntry, bool]:
        """Build one model entry. The flag says whether detection is still pending."""
        path = scanned.path
        st = path.stat()
        size = st.st_size if not scanned.is_dir else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        rel = to_rel(root_path, path)
        fkind = self._folder_kind(root, to_rel(root_path, path.parent))
        detection = None
        pending = False
        if not scanned.is_model:
            detect = "none"
        if detect == "full":
            detection = self.detection.detect(path)[0]
        elif detect == "cached":
            hit = self.detection.cached(path)
            if hit is not None:
                detection = hit[0]
            else:
                pending = True
        hint = sidecar.sidecar_hint(path.parent, scanned.stem) if scanned.is_model else None
        mismatch = False
        if detection is not None and detection.kind != "unknown":
            for other in (hint.kind if hint else None, fkind):
                if other in DETECTABLE_KINDS and not kinds_compatible(detection.kind, other):
                    mismatch = True
            if hint and hint.base_model and detection.base_model and hint.base_model != detection.base_model:
                mismatch = True
        entry = ModelEntry(
            name=path.name,
            stem=scanned.stem,
            path=rel,
            is_dir=scanned.is_dir,
            is_model=scanned.is_model,
            size=size,
            mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            preview=to_rel(root_path, scanned.preview) if scanned.preview else None,
            folder_kind=fkind,
            detection=detection,
            sidecar=hint,
            mismatch=mismatch,
            companions=[p.name for p in scanned.companions],
        )
        return entry, pending

    def list_entries(self, root_id: str, rel_path: str = "", detect: DetectMode = "full", kind: str | None = None) -> FolderListing:
        root, root_path, target = self._resolve(root_id, rel_path)
        if not target.is_dir():
            raise InvalidPathError(f"Not a folder: {rel_path}")
        lib = self.settings.settings.library
        scanned = scan_dir(target, lib.model_extensions, lib.preview_extensions, include_other_files=lib.show_all_files)
        models: list[ModelEntry] = []
        pending = 0
        for s in scanned.models:
            if not self._link_allowed(root_path, s.path):
                continue
            try:
                entry, is_pending = self._entry(root, root_path, s, detect)
            except OSError:
                continue
            pending += is_pending
            if kind and (not entry.is_model or not self._kind_matches(entry, kind)):
                continue
            models.append(entry)
        folders = [
            FolderEntry(name=p.name, path=to_rel(root_path, p), folder_kind=self._folder_kind(root, to_rel(root_path, p)))
            for p in scanned.folders
            if self._link_allowed(root_path, p)
        ]
        rel = to_rel(root_path, target)
        if pending and detect == "cached":
            self.scan_in_background(root_id, rel)
        return FolderListing(root_id=root_id, path=rel, folder_kind=self._folder_kind(root, rel), folders=folders, models=models, pending_detection=pending)

    def _link_allowed(self, root_path: Path, path: Path) -> bool:
        """Hide a folder or a model that a link leads outside the root, while links are not followed.

        Neither could be opened anyway, so listing one would only produce an error on the way in.
        The links themselves are followed by default, so the check usually costs nothing.
        """
        if self.follow_symlinks or not path.is_symlink():
            return True
        return not escapes_root(root_path, path)

    @staticmethod
    def _kind_matches(entry: ModelEntry, kind: str) -> bool:
        detected = entry.detection.kind if entry.detection else None
        if detected and detected != "unknown":
            return detected == kind
        return (entry.sidecar.kind if entry.sidecar else None) == kind or entry.folder_kind == kind or (kind == "unknown" and not entry.folder_kind)

    def list_combined(self) -> CombinedListing:
        """Every root's top level side by side, as folders only, for the interface's "All folders".

        A root with files at its top level stays one folder, named after its own directory, so its
        files are not scattered among everyone else's; a root that holds only folders lends them.
        Roots without a kind hint come first, as in the root list. A root inside another root is
        left out, since the outer one already reaches it, and a directory reached twice through a
        link is listed once. Folders sharing a name are told apart by the name of their root.
        """
        ordered = [r for r in self._roots() if not r.kind] + [r for r in self._roots() if r.kind]
        present: list[tuple[ModelRoot, Path]] = []
        missing: list[str] = []
        for r in ordered:
            path = Path(r.path).expanduser().resolve()
            if path.is_dir():
                present.append((r, path))
            else:
                missing.append(r.id)
        shown = [(r, path) for i, (r, path) in enumerate(present) if path not in (p for _, p in present[:i]) and not any(self._reaches(p, path) for _, p in present)]

        # Two roots may share a name; the second becomes "name 2" wherever it has to be named.
        names_seen: Counter[str] = Counter()
        root_names: dict[str, str] = {}
        for r, _ in shown:
            names_seen[r.name] += 1
            root_names[r.id] = r.name if names_seen[r.name] == 1 else f"{r.name} {names_seen[r.name]}"

        lib = self.settings.settings.library
        # (name, rel path, folder kind, root id, real path, is the root itself)
        entries: list[tuple[str, str, str | None, str, Path, bool]] = []
        for r, path in shown:
            try:
                scanned = scan_dir(path, lib.model_extensions, lib.preview_extensions, include_other_files=lib.show_all_files)
            except OSError:
                missing.append(r.id)
                continue
            # "Files" are what the root's own listing would show at its top: models, a diffusers
            # folder, and with show_all_files any other file.
            if any(self._link_allowed(path, m.path) for m in scanned.models):
                entries.append((path.name or str(path), "", self._folder_kind(r, ""), r.id, path, True))
                continue
            for folder in scanned.folders:
                if self._link_allowed(path, folder):
                    rel = to_rel(path, folder)
                    entries.append((folder.name, rel, self._folder_kind(r, rel), r.id, folder, False))

        # What is reached twice is kept where it really is: a root first, then the folders that
        # are not links, and a link only when nothing else leads there.
        claimed = {key for _, path in shown if (key := self._dir_id(path)) is not None}
        kept: list[tuple[str, str, str | None, str, bool]] = []
        for name, rel, fkind, root_id, path, is_root in sorted(entries, key=lambda e: (not e[5], e[4].is_symlink())):
            if not is_root:
                key = self._dir_id(path)
                if key is not None:
                    if key in claimed:
                        continue
                    claimed.add(key)
            kept.append((name, rel, fkind, root_id, is_root))

        # Case-insensitive, as a Windows user would read two names.
        counts = Counter(name.casefold() for name, *_ in kept)
        folders = [
            CombinedFolder(
                name=name,
                path=rel,
                folder_kind=fkind,
                root_id=root_id,
                root_name=root_names[root_id],
                label=name if counts[name.casefold()] == 1 else f"{name} ({root_names[root_id]})",
                is_root=is_root,
            )
            for name, rel, fkind, root_id, is_root in kept
        ]
        return CombinedListing(folders=sorted(folders, key=lambda f: f.label.casefold()), missing_roots=missing)

    @staticmethod
    def _reaches(outer: Path, inner: Path) -> bool:
        """Whether browsing ``outer`` leads to ``inner``: it lies below, and not inside a hidden folder."""
        if outer == inner or outer not in inner.parents:
            return False
        return not any(is_ignored(part) for part in inner.relative_to(outer).parts)

    @staticmethod
    def _dir_id(path: Path) -> tuple[int, int] | None:
        """Identity of the real file or directory, so a symlink loop is walked only once."""
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    def walk_models(self, root_id: str, rel_path: str = "", detect: DetectMode = "full", kind: str | None = None) -> Iterator[ModelEntry]:
        """Every model below a folder, depth first. A folder reached twice is walked once."""
        _, root_path, _ = self._resolve(root_id, rel_path)
        stack = [rel_path]
        seen: set[tuple[int, int]] = set()
        while stack:
            current = stack.pop()
            key = self._dir_id(resolve_in_root(root_path, current, follow_symlinks=self.follow_symlinks))
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            listing = self.list_entries(root_id, current, detect=detect, kind=kind)
            yield from (m for m in listing.models if m.is_model)
            stack.extend(reversed([f.path for f in listing.folders]))

    def tree(self, root_id: str, max_depth: int = 16) -> TreeNode:
        root, root_path, _ = self._resolve(root_id, "")
        seen: set[tuple[int, int]] = set()

        def build(path: Path, depth: int) -> TreeNode:
            rel = to_rel(root_path, path)
            node = TreeNode(name=path.name if rel else root.name, path=rel, folder_kind=self._folder_kind(root, rel))
            key = self._dir_id(path)
            if depth >= max_depth or (key is not None and key in seen):
                return node
            if key is not None:
                seen.add(key)
            try:
                with os.scandir(path) as it:
                    subdirs = sorted((Path(e.path) for e in it if e.is_dir() and not is_ignored(e.name)), key=lambda p: p.name.lower())
            except OSError:
                return node
            for sub in subdirs:
                if (sub / "model_index.json").is_file() or not self._link_allowed(root_path, sub):
                    continue
                node.children.append(build(sub, depth + 1))
            return node

        return build(root_path, 0)

    def model_info(self, root_id: str, rel_path: str, compute_hash: bool = False) -> ModelInfo:
        root, root_path, target = self._resolve(root_id, rel_path)
        is_dir = target.is_dir()
        if is_dir and not (target / "model_index.json").is_file():
            raise InvalidPathError(f"Not a model: {rel_path}")
        lib = self.settings.settings.library
        is_model = self._is_model(target)
        stem = model_stem(target, is_dir) if is_model else target.name
        companions = companions_of(target, lib.model_extensions) if is_model else []
        scanned = ScannedModel(target, is_dir, stem, companions=companions, is_model=is_model)
        preview = find_preview(stem, {c.name for c in scanned.companions}, lib.preview_extensions) if is_model else None
        scanned.preview = target.parent / preview if preview else None
        entry, _ = self._entry(root, root_path, scanned, "full")
        metadata: dict[str, Any] = {}
        if is_model:
            _, metadata = self.detection.detect(target)
        sha = None
        if compute_hash and not is_dir:
            sha = self.detection.sha256(target)
        elif not is_dir:
            hit = self.detection.cached(target)
            sha = hit[2] if hit else None
        return ModelInfo(
            root_id=root_id,
            entry=entry,
            sha256=sha,
            header_metadata=metadata,
            sdmodelhub=sidecar.read_sdmodelhub(target.parent, stem) if is_model else None,
            webui=sidecar.read_webui(target.parent, stem) if is_model else None,
            description=sidecar.read_description(target.parent, stem) if is_model else None,
            civitai_info=sidecar.read_civitai_info(target.parent, stem) if is_model else None,
        )

    def preview_file(self, root_id: str, rel_path: str) -> Path:
        """Resolve a preview image path; it must be an image file inside the root."""
        _, _, target = self._resolve(root_id, rel_path)
        if not target.is_file() or target.suffix.lower() not in self.settings.settings.library.preview_extensions:
            raise NotFoundError(f"Not a preview image: {rel_path}")
        return target

    def export_file(self, root_id: str, rel_path: str) -> Path:
        """The file a browser download serves: a regular file inside the root, never one still being written."""
        _, root_path, target = self._resolve(root_id, rel_path)
        if target == root_path or not target.is_file():
            raise InvalidPathError(f"Not a file: {rel_path}")
        if is_ignored(target.name):
            raise NotFoundError(f"Not found: {rel_path}")
        return target

    # -- detection scans ----------------------------------------------------

    def scan(self, root_id: str, rel_path: str = "", recursive: bool = True) -> int:
        """Detect every model below a folder, filling the cache. Returns the number of models."""
        count = 0
        if recursive:
            for _ in self.walk_models(root_id, rel_path, detect="full"):
                count += 1
        else:
            count = len(self.list_entries(root_id, rel_path, detect="full").models)
        self.notify_changed(root_id, rel_path)
        return count

    def scan_in_background(self, root_id: str, rel_path: str = "", recursive: bool = False) -> bool:
        key = (root_id, rel_path)
        with self._scan_lock:
            if key in self._scanning:
                return False
            self._scanning.add(key)

        def run() -> None:
            try:
                self.scan(root_id, rel_path, recursive=recursive)
            except ModelHubError as e:
                logger.warning("Scan of %s:%s failed: %s", root_id, rel_path, e)
            except Exception:
                logger.exception("Scan of %s:%s failed", root_id, rel_path)
            finally:
                with self._scan_lock:
                    self._scanning.discard(key)

        threading.Thread(target=run, name=f"scan-{root_id}", daemon=True).start()
        return True

    # -- operations ---------------------------------------------------------

    def _is_model(self, path: Path) -> bool:
        if path.is_dir():
            return (path / "model_index.json").is_file()
        return path.suffix.lower() in {e.lower() for e in self.settings.settings.library.model_extensions}

    def _group(self, path: Path) -> list[Path]:
        """A path plus its companions when it is a model."""
        if self._is_model(path):
            return [path, *companions_of(path, self.settings.settings.library.model_extensions)]
        return [path]

    @staticmethod
    def _renamed(member: Path, old_stem: str, new_stem: str, dest_dir: Path) -> Path:
        name = member.name
        return dest_dir / (new_stem + name[len(old_stem) :] if name.startswith(old_stem) else name)

    def _plan_group(self, src: Path, dest_dir: Path, on_conflict: str, new_stem: str | None = None) -> list[tuple[Path, Path]]:
        """Pair each file of a model group with its target, applying a suffix on conflict if asked."""
        group = self._group(src)
        old_stem = model_stem(src, src.is_dir()) if self._is_model(src) else src.name
        stem = new_stem or old_stem
        for attempt in range(10_000):
            candidate = stem if attempt == 0 else f"{stem}_{attempt}"
            pairs = [(m, self._renamed(m, old_stem, candidate, dest_dir)) for m in group]
            clashes = [d for s, d in pairs if (d.exists() or d.is_symlink()) and d != s]
            if not clashes:
                return pairs
            if on_conflict != "rename":
                raise ConflictError(f"Target exists: {clashes[0].name}", {"targets": [str(c) for c in clashes]})
        raise ConflictError("Could not find a free name")

    def import_paths(self, req: ImportRequest) -> OperationResult:
        _, root_path, dest_dir = self._resolve(req.root_id, req.rel_dir, must_exist=False)
        dest_dir.mkdir(parents=True, exist_ok=True)
        result = OperationResult()
        for raw in req.sources:
            src = Path(raw).expanduser()
            if not src.is_absolute():
                raise InvalidPathError(f"Source must be an absolute path: {raw}")
            if not src.exists():
                raise NotFoundError(f"Not found: {raw}")
            src = src.resolve()
            if src == dest_dir or src in dest_dir.parents:
                raise InvalidPathError("Cannot import a folder into itself")
            for s, d in self._plan_group(src, dest_dir, req.on_conflict):
                if req.move:
                    move_path(s, d)
                    self.detection.forget(s)
                else:
                    copy_path(s, d)
                if s == src:
                    result.paths.append(PathRef(root_id=req.root_id, path=to_rel(root_path, d)))
        self.notify_changed(req.root_id, to_rel(root_path, dest_dir))
        return result

    def open_upload(self, root_id: str, rel_dir: str, name: str, total: int | None = None, on_conflict: str = "error") -> UploadWriter:
        """Start a streamed upload. The name may contain ``/`` to keep a dropped folder's structure."""
        parts = [p for p in name.replace("\\", "/").split("/") if p]
        if not parts:
            raise InvalidPathError("Empty file name")
        for p in parts:
            validate_name(p)
        _, root_path, dest_dir = self._resolve(root_id, "/".join([rel_dir, *parts[:-1]]) if rel_dir else "/".join(parts[:-1]), must_exist=False)
        target = dest_dir / parts[-1]
        if target.exists():
            if on_conflict != "rename":
                raise ConflictError(f"Target exists: {parts[-1]}", {"target": to_rel(root_path, target)})
            target = unique_path(target)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return UploadWriter(self, root_id, target, total)

    def move(self, req: MoveRequest) -> OperationResult:
        _, dest_root, dest_dir = self._resolve(req.dest_root_id, req.dest_dir, must_exist=False)
        dest_dir.mkdir(parents=True, exist_ok=True)
        result = OperationResult()
        changed: set[tuple[str, str]] = {(req.dest_root_id, to_rel(dest_root, dest_dir))}
        for item in req.items:
            _, src_root, src = self._resolve(item.root_id, item.path)
            if src == src_root:
                raise InvalidPathError("Cannot move a root")
            if src.is_dir() and (dest_dir == src or src in dest_dir.parents):
                raise InvalidPathError("Cannot move a folder into itself")
            if src.parent == dest_dir:
                continue
            for s, d in self._plan_group(src, dest_dir, req.on_conflict):
                move_path(s, d)
                self.detection.forget(s)
                if s == src:
                    result.paths.append(PathRef(root_id=req.dest_root_id, path=to_rel(dest_root, d)))
            changed.add((item.root_id, to_rel(src_root, src.parent)))
        for root_id, rel in changed:
            self.notify_changed(root_id, rel)
        return result

    def rename(self, req: RenameRequest) -> OperationResult:
        _, root_path, src = self._resolve(req.root_id, req.path)
        if src == root_path:
            raise InvalidPathError("Cannot rename a root")
        new_name = validate_name(req.new_name.strip())
        if self._is_model(src) and not src.is_dir():
            ext = src.suffix
            new_stem = new_name[: -len(ext)] if new_name.lower().endswith(ext.lower()) else new_name
            validate_name(new_stem)
            pairs = self._plan_group(src, src.parent, "error", new_stem=new_stem)
        elif self._is_model(src):
            pairs = self._plan_group(src, src.parent, "error", new_stem=new_name)
        else:
            target = src.parent / new_name
            if target.exists():
                raise ConflictError(f"Target exists: {new_name}")
            pairs = [(src, target)]
        new_path = src
        for s, d in pairs:
            if s == d:
                continue
            rename_no_overwrite(s, d)
            self.detection.forget(s)
            if s == src:
                new_path = d
        self.notify_changed(req.root_id, to_rel(root_path, src.parent))
        return OperationResult(paths=[PathRef(root_id=req.root_id, path=to_rel(root_path, new_path))])

    def delete(self, req: DeleteRequest) -> OperationResult:
        to_trash = self.settings.settings.library.delete_to_trash and not req.permanent
        result = OperationResult()
        targets: list[tuple[str, Path, Path]] = []
        for item in req.items:
            _, root_path, src = self._resolve(item.root_id, item.path)
            if src == root_path:
                raise InvalidPathError("Cannot delete a root")
            targets.append((item.root_id, root_path, src))
        for root_id, root_path, src in targets:
            if not src.exists():
                continue
            for member in self._group(src):
                if to_trash:
                    result.trashed_to.append(self._trash(member))
                else:
                    remove_path(member)
                self.detection.forget(member)
            result.paths.append(PathRef(root_id=root_id, path=to_rel(root_path, src)))
            self.notify_changed(root_id, to_rel(root_path, src.parent))
        return result

    def trash_location(self) -> TrashLocation:
        """Where `delete` sends files when it goes to the trash, as `_trash` and send2trash decide it."""
        fallback = str(self.settings.data_dir / "trash")
        if sys.platform == "win32":
            return TrashLocation(system=None, fallback=fallback)
        if sys.platform == "darwin":
            return TrashLocation(system=str(Path.home() / ".Trash"), fallback=fallback)
        # send2trash's FreeDesktop trash for the home filesystem; other disks use a folder at their top.
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return TrashLocation(system=str(Path(xdg) / "Trash"), fallback=fallback)

    def _trash(self, path: Path) -> str:
        try:
            from send2trash import send2trash

            send2trash(str(path))
            return "system"
        except Exception as e:  # noqa: BLE001 - any trash failure falls back to our own folder
            logger.info("System trash failed for %s (%s); using the data directory", path, e)
        fallback = self.settings.data_dir / "trash" / time.strftime("%Y%m%d-%H%M%S")
        fallback.mkdir(parents=True, exist_ok=True)
        move_path(path, unique_path(fallback / path.name))
        return str(fallback)

    def create_folder(self, req: FolderCreate) -> PathRef:
        _, root_path, parent = self._resolve(req.root_id, req.path)
        name = validate_name(req.name.strip())
        target = parent / name
        if target.exists():
            raise ConflictError(f"Already exists: {name}")
        target.mkdir()
        self.notify_changed(req.root_id, to_rel(root_path, parent))
        return PathRef(root_id=req.root_id, path=to_rel(root_path, target))

    @staticmethod
    def layouts() -> dict[str, dict[str, str]]:
        """Folder-to-kind maps of every layout preset."""
        return {name: dict(mapping) for name, mapping in LAYOUTS.items()}
