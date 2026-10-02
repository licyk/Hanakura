"""The local library."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from starlette.requests import ClientDisconnect

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.core.library.models import (
    CombinedListing,
    DeleteRequest,
    FolderCreate,
    FolderListing,
    ImportRequest,
    ModelInfo,
    MoveRequest,
    OperationResult,
    PathRef,
    RenameRequest,
    RootCreate,
    RootInfo,
    RootUpdate,
    TreeNode,
)
from hanakura.core.library.thumbnails import thumbnail
from hanakura.core.record import Record
from hanakura.core.settings.models import DownloadDestination

router = APIRouter(prefix="/v1/library", tags=["library"], responses=ERROR_RESPONSES)


class ScanResult(Record):
    started: bool


@router.get("/destination", operation_id="suggest_download_destination")
def suggest_destination(services: ServicesDep, kind: str | None = None, root_id: str | None = None) -> DownloadDestination:
    return services.library.suggest_destination(kind, root_id)


@router.get("/locate", operation_id="locate_path")
def locate_path(services: ServicesDep, path: str = Query(description="Absolute path on the server")) -> PathRef:
    """Find the root that holds an absolute path, so a client can open it in the library."""
    root_id, rel = services.library.locate(Path(path))
    return PathRef(root_id=root_id, path=rel)


@router.get("/roots", operation_id="list_roots")
def list_roots(services: ServicesDep) -> list[RootInfo]:
    return services.library.list_roots()


@router.post("/roots", operation_id="add_root", status_code=status.HTTP_201_CREATED)
def add_root(services: ServicesDep, body: RootCreate) -> RootInfo:
    return services.library.add_root(body)


@router.patch("/roots/{root_id}", operation_id="update_root")
def update_root(services: ServicesDep, root_id: str, body: RootUpdate) -> RootInfo:
    return services.library.update_root(root_id, body)


@router.delete("/roots/{root_id}", operation_id="remove_root", status_code=status.HTTP_204_NO_CONTENT)
def remove_root(services: ServicesDep, root_id: str) -> None:
    services.library.remove_root(root_id)


@router.get("/combined/entries", operation_id="list_combined_entries")
def list_combined_entries(services: ServicesDep) -> CombinedListing:
    """The top level of every root side by side, as folders; library.combined_view only decides whether the interface offers it."""
    return services.library.list_combined()


@router.get("/roots/{root_id}/entries", operation_id="list_entries")
def list_entries(services: ServicesDep, root_id: str, path: str = "", kind: str | None = None) -> FolderListing:
    # Only cached detections are returned; the rest are filled by a background scan that publishes library_changed.
    return services.library.list_entries(root_id, path, detect="cached", kind=kind)


@router.get("/roots/{root_id}/tree", operation_id="get_tree")
def get_tree(services: ServicesDep, root_id: str) -> TreeNode:
    return services.library.tree(root_id)


@router.get("/roots/{root_id}/model", operation_id="get_model_info")
def get_model_info(services: ServicesDep, root_id: str, path: str, hash: bool = False) -> ModelInfo:
    return services.library.model_info(root_id, path, compute_hash=hash)


@router.get(
    "/roots/{root_id}/preview",
    operation_id="get_preview",
    response_class=FileResponse,
    responses={200: {"content": {"image/webp": {}, "image/*": {}}}},
)
def get_preview(services: ServicesDep, root_id: str, path: str, size: int = Query(default=384, ge=0, le=2048)) -> FileResponse:
    source = services.library.preview_file(root_id, path)
    if size == 0:
        return FileResponse(source, headers={"Cache-Control": "private, max-age=60"})
    cached, media_type = thumbnail(source, services.settings.data_dir / "thumbnails", size)
    return FileResponse(cached, media_type=media_type, headers={"Cache-Control": "private, max-age=60"})


@router.get(
    "/roots/{root_id}/file",
    operation_id="download_file",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
)
def download_file(services: ServicesDep, root_id: str, path: str) -> FileResponse:
    """Send one file as an attachment, so a browser saves it with its own download manager."""
    target = services.library.export_file(root_id, path)
    return FileResponse(target, media_type="application/octet-stream", filename=target.name, headers={"Cache-Control": "private, no-store"})


@router.post("/roots/{root_id}/scan", operation_id="scan_root")
def scan_root(services: ServicesDep, root_id: str, path: str = "") -> ScanResult:
    services.library.get_root(root_id)
    return ScanResult(started=services.library.scan_in_background(root_id, path, recursive=True))


@router.post("/import", operation_id="import_paths")
def import_paths(services: ServicesDep, body: ImportRequest) -> OperationResult:
    return services.library.import_paths(body)


@router.put(
    "/upload",
    operation_id="upload_file",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}, "required": True}},
)
async def upload_file(
    request: Request,
    services: ServicesDep,
    root_id: str,
    name: str = Query(description="File name; may contain '/' to keep a dropped folder's structure"),
    path: str = Query(default="", description="Destination folder inside the root"),
    on_conflict: Literal["error", "rename"] = "error",
) -> PathRef:
    """Stream the raw request body into the destination. Nothing is spooled to a temporary directory."""
    length = request.headers.get("content-length")
    total = int(length) if length and length.isdigit() else None
    writer = await run_in_threadpool(services.library.open_upload, root_id, path, name, total, on_conflict)
    try:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(writer.write, chunk)
    except (ClientDisconnect, Exception):
        await run_in_threadpool(writer.abort)
        raise
    return await run_in_threadpool(writer.commit)


@router.post("/move", operation_id="move_items")
def move_items(services: ServicesDep, body: MoveRequest) -> OperationResult:
    return services.library.move(body)


@router.post("/rename", operation_id="rename_item")
def rename_item(services: ServicesDep, body: RenameRequest) -> OperationResult:
    return services.library.rename(body)


@router.post("/delete", operation_id="delete_items")
def delete_items(services: ServicesDep, body: DeleteRequest) -> OperationResult:
    return services.library.delete(body)


@router.post("/folders", operation_id="create_folder", status_code=status.HTTP_201_CREATED)
def create_folder(services: ServicesDep, body: FolderCreate) -> PathRef:
    return services.library.create_folder(body)
