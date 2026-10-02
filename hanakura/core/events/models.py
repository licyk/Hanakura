"""Event models. Each has an event name and is published on the EventBus."""

from typing import ClassVar

from hanakura.core.downloads.models import DownloadJob
from hanakura.core.record import Record


class EventBase(Record):
    __event_name__: ClassVar[str] = ""

    @classmethod
    def get_events(cls) -> list[type["EventBase"]]:
        """Every concrete event class, for the OpenAPI schema."""
        out: list[type[EventBase]] = []
        stack = list(cls.__subclasses__())
        while stack:
            sub = stack.pop()
            stack.extend(sub.__subclasses__())
            if sub.__event_name__:
                out.append(sub)
        return sorted(out, key=lambda c: c.__event_name__)


class DownloadJobEvent(EventBase):
    job: DownloadJob


class DownloadQueuedEvent(DownloadJobEvent):
    __event_name__ = "download_queued"


class DownloadStartedEvent(DownloadJobEvent):
    __event_name__ = "download_started"


class DownloadCompletedEvent(DownloadJobEvent):
    __event_name__ = "download_completed"


class DownloadFailedEvent(DownloadJobEvent):
    __event_name__ = "download_failed"


class DownloadCancelledEvent(DownloadJobEvent):
    __event_name__ = "download_cancelled"


class DownloadPausedEvent(DownloadJobEvent):
    __event_name__ = "download_paused"


class DownloadRemovedEvent(EventBase):
    __event_name__ = "download_removed"
    job_ids: list[int]


class DownloadProgressEvent(EventBase):
    __event_name__ = "download_progress"
    job_id: int
    bytes_done: int
    total_bytes: int | None
    speed: float


class LibraryChangedEvent(EventBase):
    __event_name__ = "library_changed"
    root_id: str
    rel_path: str = ""


class ImportProgressEvent(EventBase):
    __event_name__ = "import_progress"
    root_id: str
    rel_path: str
    bytes_done: int
    total_bytes: int | None
    done: bool = False
