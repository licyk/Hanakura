"""The repository hub interface.

Metadata is fetched over plain HTTP with the shared httpx client, so the parent process never
imports the heavy hub libraries. Downloads run through ``huggingface_hub`` or ``modelscope`` in a
child process (see ``worker.py``), because cancelling from a progress hook does not stop either
library: on Hugging Face's default path the transfer ran to completion anyway, and ModelScope
treated the exception as a network failure, retried, and then returned normally.
"""

import fnmatch
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

from hanakura.core.errors import SourceError
from hanakura.core.hubs.models import HubPage, HubQuery, RepoDetail, RepoFile
from hanakura.core.settings.models import SourceSettings
from hanakura.core.sources.base import TTLCache, raise_for_status


def select_files(files: list[RepoFile], include: list[str], exclude: list[str]) -> list[RepoFile]:
    """Apply ``allow_patterns`` / ``ignore_patterns`` style filters, as the libraries do."""
    out = []
    for f in files:
        if include and not any(fnmatch.fnmatch(f.path, p) for p in include):
            continue
        if exclude and any(fnmatch.fnmatch(f.path, p) for p in exclude):
            continue
        out.append(f)
    return out


class HubAdapter(ABC):
    id: str = ""
    name: str = ""
    default_endpoint: str = ""
    default_revision: str = "main"
    sorts: ClassVar[tuple[str, ...]] = ()

    def __init__(self, client: Callable[[], httpx.Client], settings: Callable[[], SourceSettings]) -> None:
        self._client = client
        self._settings = settings
        self.cache = TTLCache()

    @property
    def client(self) -> httpx.Client:
        return self._client()

    @property
    def settings(self) -> SourceSettings:
        return self._settings()

    @property
    def endpoint(self) -> str:
        return (self.settings.endpoint or self.settings.base_url or self.default_endpoint).rstrip("/")

    def auth_headers(self) -> dict[str, str]:
        token = self.settings.token
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _get(self, url: str, what: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.get(url, headers=self.auth_headers(), **kwargs)
        except httpx.HTTPError as e:
            raise SourceError(f"{what}: {e}") from e
        raise_for_status(response, what)
        return response

    @abstractmethod
    def search(self, query: HubQuery) -> HubPage: ...

    @abstractmethod
    def get_repo(self, repo_id: str, revision: str | None = None) -> RepoDetail: ...

    def list_files(self, repo_id: str, revision: str | None = None) -> list[RepoFile]:
        return self.get_repo(repo_id, revision).files

    def worker_config(self) -> dict[str, Any]:
        """Settings passed to the download worker."""
        return {"endpoint": self.endpoint, "token": self.settings.token}
