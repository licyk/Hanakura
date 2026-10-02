"""The download queue."""

from fastapi import APIRouter, status

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.core.downloads.models import DownloadCreate, DownloadJob

router = APIRouter(prefix="/v1/downloads", tags=["downloads"], responses=ERROR_RESPONSES)


@router.get("", operation_id="list_downloads")
def list_downloads(services: ServicesDep) -> list[DownloadJob]:
    return services.downloads.list_jobs()


@router.post("", operation_id="create_download", status_code=status.HTTP_201_CREATED)
def create_download(services: ServicesDep, body: DownloadCreate) -> DownloadJob:
    return services.downloads.create(body)


@router.post("/clear-finished", operation_id="clear_finished_downloads")
def clear_finished(services: ServicesDep) -> list[int]:
    return services.downloads.clear_finished()


@router.get("/{job_id}", operation_id="get_download")
def get_download(services: ServicesDep, job_id: int) -> DownloadJob:
    return services.downloads.get(job_id)


@router.post("/{job_id}/pause", operation_id="pause_download")
def pause_download(services: ServicesDep, job_id: int) -> DownloadJob:
    return services.downloads.pause(job_id)


@router.post("/{job_id}/resume", operation_id="resume_download")
def resume_download(services: ServicesDep, job_id: int) -> DownloadJob:
    return services.downloads.resume(job_id)


@router.post("/{job_id}/cancel", operation_id="cancel_download")
def cancel_download(services: ServicesDep, job_id: int) -> DownloadJob:
    return services.downloads.cancel(job_id)


@router.post("/{job_id}/restart", operation_id="restart_download")
def restart_download(services: ServicesDep, job_id: int) -> DownloadJob:
    return services.downloads.restart(job_id)


@router.delete("/{job_id}", operation_id="delete_download", status_code=status.HTTP_204_NO_CONTENT)
def delete_download(services: ServicesDep, job_id: int) -> None:
    services.downloads.remove(job_id)
