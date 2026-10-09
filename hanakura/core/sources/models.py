"""Records shared by every searchable source."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from hanakura.core.record import Record


class FilterOption(Record):
    value: str
    label: str


class SourceCapabilities(Record):
    search: bool = True
    identify: bool = False
    needs_token: bool = False
    kinds: list[FilterOption] = Field(default_factory=list)
    base_models: list[FilterOption] = Field(default_factory=list)
    sorts: list[FilterOption] = Field(default_factory=list)
    nsfw_filter: bool = False


class SourceInfo(Record):
    id: str
    name: str
    kind: str = "source"
    enabled: bool
    token_configured: bool
    capabilities: SourceCapabilities


class SearchQuery(Record):
    query: str = ""
    kind: str | None = None
    base_model: str | None = None
    sort: str | None = None
    nsfw: bool = False
    limit: int = Field(default=24, ge=1, le=100)
    cursor: str | None = None


class ModelStats(Record):
    downloads: int | None = None
    likes: int | None = None
    rating: float | None = None


class ModelSummary(Record):
    source: str
    id: str
    name: str
    kind: str | None = None
    base_model: str | None = None
    base_model_label: str | None = None
    preview_url: str | None = None
    preview_is_video: bool = False
    creator: str | None = None
    nsfw_level: int = 0
    stats: ModelStats = Field(default_factory=ModelStats)
    tags: list[str] = Field(default_factory=list)
    page_url: str | None = None


class SearchPage(Record):
    items: list[ModelSummary]
    next_cursor: str | None = None


class ModelFile(Record):
    id: str
    name: str
    size: int | None = None
    sha256: str | None = None
    kind: str | None = None
    primary: bool = False
    scan_result: str | None = None
    download_ref: str
    format: str | None = None


class ModelImage(Record):
    url: str
    nsfw_level: int = 0
    width: int | None = None
    height: int | None = None
    is_video: bool = False


class ModelVersion(Record):
    id: str
    name: str
    base_model: str | None = None
    base_model_label: str | None = None
    published_at: datetime | None = None
    trained_words: list[str] = Field(default_factory=list)
    files: list[ModelFile] = Field(default_factory=list)
    images: list[ModelImage] = Field(default_factory=list)


PermissionId = Literal["credit", "sell_images", "rent", "generate_on_civitai", "derivatives", "sell_model", "different_license"]


class ModelPermission(Record):
    """One use the creator allows or forbids; ``credit`` means use without crediting them."""

    id: PermissionId
    allowed: bool


class ModelDetail(ModelSummary):
    description: str | None = None
    versions: list[ModelVersion] = Field(default_factory=list)
    # A named licence (OpenModelDB's SPDX ids); Civitai has none and lists ``permissions`` instead.
    license: str | None = None
    permissions: list[ModelPermission] = Field(default_factory=list)
    trained_words: list[str] = Field(default_factory=list)
    images: list[ModelImage] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class DownloadRequest(Record):
    """What the downloader needs, resolved immediately before a download starts."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    file_name: str | None = None
    size: int | None = None
    sha256: str | None = None


class IdentifyResult(Record):
    source: str
    model: ModelDetail
    version_id: str | None = None
    file_name: str | None = None
