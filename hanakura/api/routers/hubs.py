"""Hugging Face and ModelScope."""

from fastapi import APIRouter, Query

from hanakura.api.deps import ServicesDep
from hanakura.api.errors import ERROR_RESPONSES
from hanakura.core.hubs.models import HubInfo, HubPage, HubQuery, RepoDetail, RepoFile

router = APIRouter(prefix="/v1/hubs", tags=["hubs"], responses=ERROR_RESPONSES)


@router.get("", operation_id="list_hubs")
def list_hubs(services: ServicesDep) -> list[HubInfo]:
    return services.hubs.list_hubs()


@router.get("/{hub}/repos", operation_id="search_repos")
def search_repos(
    services: ServicesDep,
    hub: str,
    query: str = "",
    sort: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = None,
) -> HubPage:
    return services.hubs.search(hub, HubQuery(query=query, sort=sort, limit=limit, cursor=cursor))


# Repository ids contain a slash, so they are path parameters of type path.
@router.get("/{hub}/repos/{repo_id:path}/files", operation_id="list_repo_files")
def list_repo_files(services: ServicesDep, hub: str, repo_id: str, revision: str | None = None) -> list[RepoFile]:
    return services.hubs.list_files(hub, repo_id, revision)


@router.get("/{hub}/repos/{repo_id:path}", operation_id="get_repo")
def get_repo(services: ServicesDep, hub: str, repo_id: str, revision: str | None = None) -> RepoDetail:
    return services.hubs.get_repo(hub, repo_id, revision)
