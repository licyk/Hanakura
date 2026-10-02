"""Library records returned by the service."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from hanakura.core.detection.models import DetectionResult
from hanakura.core.record import Record
from hanakura.core.settings.models import LayoutName


class RootInfo(Record):
    id: str
    name: str
    path: str
    layout: LayoutName
    exists: bool
    kind: str | None = None


class RootCreate(Record):
    name: str | None = None
    path: str
    layout: LayoutName = "custom"
    kind: str | None = None


class RootUpdate(Record):
    name: str | None = None
    path: str | None = None
    layout: LayoutName | None = None
    kind: str | None = None


class FolderEntry(Record):
    name: str
    path: str
    folder_kind: str | None = None


class SidecarHint(Record):
    """What a sidecar file says the model is."""

    source: str
    kind: str | None = None
    base_model: str | None = None


class ModelEntry(Record):
    name: str
    stem: str
    path: str
    is_dir: bool = False
    is_model: bool = True
    """False for a plain file listed because ``library.show_all_files`` is on; it is never detected."""
    size: int
    mtime: datetime
    preview: str | None = None
    folder_kind: str | None = None
    detection: DetectionResult | None = None
    sidecar: SidecarHint | None = None
    mismatch: bool = False
    companions: list[str] = Field(default_factory=list)


class FolderListing(Record):
    root_id: str
    path: str
    folder_kind: str | None
    folders: list[FolderEntry]
    models: list[ModelEntry]
    pending_detection: int = 0


COMBINED_VIEW_ID = "*"
"""Stands for "every root" in the interface's root selector, so no root may use it as its id."""


class CombinedFolder(FolderEntry):
    """One entry of the combined view: a first-level folder of a root, or a whole root."""

    root_id: str
    root_name: str
    label: str
    """The name, or ``name (root name)`` when another entry of the combined view has the same name."""
    is_root: bool
    """The root itself, named after its directory, because it has files at its top level. Its ``path`` is ``""``."""


class CombinedListing(Record):
    """The top level of every root side by side, as folders only; no file is ever loose here."""

    folders: list[CombinedFolder]
    missing_roots: list[str] = Field(default_factory=list)
    """Roots whose folder does not exist or cannot be read, left out rather than failing the whole listing."""


class TreeNode(Record):
    name: str
    path: str
    folder_kind: str | None = None
    children: list["TreeNode"] = Field(default_factory=list)


class ModelInfo(Record):
    root_id: str
    entry: ModelEntry
    sha256: str | None = None
    header_metadata: dict[str, Any] = Field(default_factory=dict)
    hanakura: dict[str, Any] | None = None
    webui: dict[str, Any] | None = None
    description: str | None = None
    civitai_info: dict[str, Any] | None = None


class PathRef(Record):
    root_id: str
    path: str


class ImportRequest(Record):
    """Copy or move files already on the server's machine into a root."""

    sources: list[str]
    root_id: str
    rel_dir: str = ""
    move: bool = False
    on_conflict: Literal["error", "rename"] = "error"


class MoveRequest(Record):
    items: list[PathRef]
    dest_root_id: str
    dest_dir: str = ""
    on_conflict: Literal["error", "rename"] = "error"


class RenameRequest(Record):
    root_id: str
    path: str
    new_name: str


class DeleteRequest(Record):
    items: list[PathRef]
    permanent: bool = False


class FolderCreate(Record):
    root_id: str
    path: str = ""
    name: str


class TrashLocation(Record):
    """Where a delete to the trash puts files, so a server's owner knows what to empty."""

    system: str | None
    """The user's system trash on this filesystem; None on Windows, where it is the Recycle Bin."""
    fallback: str
    """The folder in the data directory used when the system trash cannot take a file."""


class OperationResult(Record):
    """Paths affected by an operation, relative to their roots."""

    paths: list[PathRef] = Field(default_factory=list)
    trashed_to: list[str] = Field(default_factory=list)
