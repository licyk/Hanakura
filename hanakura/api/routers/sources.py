"""Searchable sources."""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.core.record import PYDANTIC_V2
from hanakura.core.sources.models import IdentifyResult, ModelDetail, ModelFile, SearchPage, SearchQuery, SourceInfo

router = APIRouter(prefix="/v1/sources", tags=["sources"], responses=ERROR_RESPONSES)
_HASH_CONSTRAINT: dict[str, Any] = {"pattern" if PYDANTIC_V2 else "regex": r"^[0-9a-fA-F]{64}$"}


class IdentifyRequest(BaseModel):
    sha256: str = Field(**_HASH_CONSTRAINT)


@router.get("", operation_id="list_sources")
def list_sources(services: ServicesDep) -> list[SourceInfo]:
    return services.sources.list_sources()


@router.post("/identify", operation_id="identify_model")
def identify(services: ServicesDep, body: IdentifyRequest) -> list[IdentifyResult]:
    return services.sources.identify(body.sha256)


@router.get("/{source}/models", operation_id="search_models")
def search_models(
    services: ServicesDep,
    source: str,
    query: str = "",
    kind: str | None = None,
    base_model: str | None = None,
    sort: str | None = None,
    limit: int = Query(default=24, ge=1, le=100),
    cursor: str | None = None,
) -> SearchPage:
    return services.sources.search(source, SearchQuery(query=query, kind=kind, base_model=base_model, sort=sort, limit=limit, cursor=cursor))


# Declared before the detail route: model ids may contain a slash (GitHub repositories).
@router.get("/{source}/models/{model_id:path}/files", operation_id="list_model_files")
def list_model_files(services: ServicesDep, source: str, model_id: str, version_id: str | None = None) -> list[ModelFile]:
    return services.sources.list_files(source, model_id, version_id)


@router.get("/{source}/models/{model_id:path}", operation_id="get_model")
def get_model(services: ServicesDep, source: str, model_id: str) -> ModelDetail:
    return services.sources.get_model(source, model_id)
