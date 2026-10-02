"""App version, health and vocabulary."""

from fastapi import APIRouter, Request

from hanakura.api.deps import ServicesDep
from hanakura.core.detection.models import BASE_MODELS, MODEL_KINDS
from hanakura.core.library import LibraryService
from hanakura.core.library.models import TrashLocation
from hanakura.core.record import Record
from hanakura.version import VERSION

router = APIRouter(prefix="/v1/app", tags=["app"])


class AppVersion(Record):
    version: str


class Health(Record):
    status: str
    auth_required: bool


class LabeledValue(Record):
    value: str
    label: str


class AppMeta(Record):
    kinds: list[str]
    base_models: list[LabeledValue]
    layouts: dict[str, dict[str, str]]
    roots_locked: bool
    """True when a host application supplies the model folders; the interface then hides adding,
    editing and removing them."""
    trash: TrashLocation
    api_prefix: str


@router.get("/version", operation_id="get_app_version")
def get_version() -> AppVersion:
    return AppVersion(version=VERSION)


@router.get("/health", operation_id="get_health")
def get_health(services: ServicesDep) -> Health:
    return Health(status="ok", auth_required=bool(services.settings.settings.server.access_token))


@router.get("/meta", operation_id="get_app_meta")
def get_meta(request: Request, services: ServicesDep) -> AppMeta:
    return AppMeta(
        kinds=MODEL_KINDS,
        base_models=[LabeledValue(value=k, label=v) for k, v in BASE_MODELS.items()],
        layouts=LibraryService.layouts(),
        roots_locked=services.library.roots_locked,
        trash=services.library.trash_location(),
        api_prefix=getattr(request.app.state, "api_prefix", "") or "",
    )
