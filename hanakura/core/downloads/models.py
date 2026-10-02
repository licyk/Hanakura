"""Download job models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from hanakura.core.record import Record, computed_field

JobState = Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
Runner = Literal["http", "huggingface", "modelscope"]

FINISHED_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})


class SourceFileRef(Record):
    """Points at one file of a model on a searchable source."""

    source: str
    model_id: str
    version_id: str | None = None
    file_id: str | None = None
    file_name: str | None = None


class HubSelection(Record):
    """A selection of files in a Hugging Face or ModelScope repository."""

    hub: Literal["huggingface", "modelscope"]
    repo_id: str
    revision: str | None = None
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class DownloadJob(Record):
    id: int
    runner: Runner
    title: str
    state: JobState = "queued"
    source: str | None = None
    source_file: SourceFileRef | None = None
    hub: HubSelection | None = None
    url: str | None = None
    root_id: str | None = None
    rel_dir: str = ""
    dest_dir: str
    file_name: str | None = None
    final_path: str | None = None
    overwrite: bool = False
    bytes_done: int = 0
    total_bytes: int | None = None
    expected_sha256: str | None = None
    sha256: str | None = None
    etag: str | None = None
    initial_total: int | None = None
    error: str | None = None
    attempts: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    speed: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def can_pause(self) -> bool:
        """Hub jobs cannot pause: neither library resumes an interrupted download."""
        return self.runner == "http"


class DownloadCreate(Record):
    """Body of ``POST /downloads``. Give exactly one of ``source_file``, ``hub`` or ``url``."""

    source_file: SourceFileRef | None = None
    hub: HubSelection | None = None
    url: str | None = None
    root_id: str | None = None
    rel_dir: str | None = None
    dest_dir: str | None = None
    file_name: str | None = None
    expected_sha256: str | None = None
    overwrite: bool = False
    title: str | None = None
