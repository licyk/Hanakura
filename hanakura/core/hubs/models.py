"""Repository hub records."""

from datetime import datetime

from pydantic import Field

from hanakura.core.record import Record


class HubInfo(Record):
    id: str
    name: str
    enabled: bool
    token_configured: bool
    endpoint: str
    default_revision: str
    sorts: list[str]


class HubQuery(Record):
    query: str = ""
    sort: str | None = None
    limit: int = Field(default=30, ge=1, le=100)
    cursor: str | None = None


class RepoSummary(Record):
    hub: str
    id: str
    author: str | None = None
    name: str
    downloads: int | None = None
    likes: int | None = None
    tags: list[str] = Field(default_factory=list)
    task: str | None = None
    last_modified: datetime | None = None
    gated: bool = False
    private: bool = False
    page_url: str


class HubPage(Record):
    items: list[RepoSummary]
    next_cursor: str | None = None
    total: int | None = None


class RepoFile(Record):
    path: str
    size: int | None = None
    sha256: str | None = None
    lfs: bool = False


class RepoDetail(RepoSummary):
    revision: str
    sha: str | None = None
    description: str | None = None
    license: str | None = None
    files: list[RepoFile] = Field(default_factory=list)
    total_size: int | None = None
