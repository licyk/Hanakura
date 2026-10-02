"""Registry of searchable sources, and the identify-by-hash lookup."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

from hanakura.core.errors import NotFoundError, SourceError, ValidationError

if TYPE_CHECKING:
    from hanakura.core.auth.service import CivitaiAuthService
from hanakura.core.settings import SettingsService
from hanakura.core.settings.models import SourceSettings
from hanakura.core.sources.base import SourceAdapter
from hanakura.core.sources.civitai import CivitaiAdapter
from hanakura.core.sources.github_releases import GitHubReleasesAdapter
from hanakura.core.sources.models import IdentifyResult, ModelDetail, ModelFile, SearchPage, SearchQuery, SourceInfo
from hanakura.core.sources.openmodeldb import OpenModelDBAdapter

logger = logging.getLogger(__name__)

CIVARCHIVE_URL = "https://civarchive.com"
ADAPTER_CLASSES: list[type[SourceAdapter]] = [CivitaiAdapter, OpenModelDBAdapter, GitHubReleasesAdapter]


class SourceRegistry:
    def __init__(
        self,
        settings: SettingsService,
        client: Callable[[], httpx.Client],
        adapters: list[SourceAdapter] | None = None,
        auth: "CivitaiAuthService | None" = None,
    ) -> None:
        self.settings_service = settings
        self._client = client
        self.auth = auth
        if adapters is None:
            # Civitai takes its headers from the authentication service, which knows whether the
            # manual token or an OAuth token is in use, and refreshes the latter when it is due.
            adapters = [
                cls(
                    client,
                    self._settings_getter(cls.id),
                    auth.headers if auth and cls.id == "civitai" else None,
                    auth.on_unauthorized if auth and cls.id == "civitai" else None,
                )
                for cls in ADAPTER_CLASSES
            ]
        self.adapters: dict[str, SourceAdapter] = {a.id: a for a in adapters}

    def _settings_getter(self, source_id: str) -> Callable[[], SourceSettings]:
        return lambda: self.settings_service.settings.sources.get(source_id) or SourceSettings()

    def list_sources(self) -> list[SourceInfo]:
        out = []
        for a in self.adapters.values():
            s = a.settings
            authenticated = bool(s.token) or (a.id == "civitai" and self.auth is not None and bool(self.auth.headers()))
            out.append(SourceInfo(id=a.id, name=a.name, enabled=s.enabled, token_configured=authenticated, capabilities=a.capabilities))
        return out

    def get(self, source_id: str) -> SourceAdapter:
        adapter = self.adapters.get(source_id)
        if adapter is None:
            raise NotFoundError(f"Unknown source {source_id!r}")
        if not adapter.settings.enabled:
            raise ValidationError(f"Source {source_id!r} is disabled in settings")
        return adapter

    def on_unauthorized(self, source_id: str) -> bool:
        """Give the source one chance to renew its credential after a 401. True means retry."""
        if source_id == "civitai" and self.auth is not None:
            return self.auth.on_unauthorized()
        return False

    def search(self, source_id: str, query: SearchQuery) -> SearchPage:
        nsfw_mode = self.settings_service.settings.content.nsfw_mode
        query = query.model_copy(update={"nsfw": nsfw_mode != "hide"})
        page = self.get(source_id).search(query)
        if nsfw_mode == "hide":
            page = page.model_copy(update={"items": [i for i in page.items if i.nsfw_level <= 1]})
        return page

    def get_model(self, source_id: str, model_id: str) -> ModelDetail:
        return self.get(source_id).get_model(model_id)

    def list_files(self, source_id: str, model_id: str, version_id: str | None = None) -> list[ModelFile]:
        return self.get(source_id).list_files(model_id, version_id)

    def find_file(self, source_id: str, model_id: str, version_id: str | None, file_id: str | None, file_name: str | None) -> tuple[ModelDetail, ModelFile]:
        """Find one file of a model; defaults to the primary file of the chosen (or latest) version."""
        adapter = self.get(source_id)
        detail = adapter.get_model(model_id)
        if not detail.versions:
            raise NotFoundError(f"{model_id} has no downloadable versions")
        version = next((v for v in detail.versions if v.id == version_id), None) if version_id else detail.versions[0]
        if version is None:
            raise NotFoundError(f"No version {version_id} of {model_id}")
        files = version.files
        if file_id:
            match = next((f for f in files if f.id == file_id), None)
        elif file_name:
            match = next((f for f in files if f.name == file_name), None)
        else:
            match = next((f for f in files if f.primary), files[0] if files else None)
        if match is None:
            raise NotFoundError(f"No matching file in {model_id} version {version.name}")
        return detail, match

    def identify(self, sha256: str) -> list[IdentifyResult]:
        """Look a file hash up on every source that can, with CivitAI Archive as the fallback."""
        sha256 = sha256.lower()
        results: list[IdentifyResult] = []
        for adapter in self.adapters.values():
            if not adapter.capabilities.identify or not adapter.settings.enabled:
                continue
            try:
                detail = adapter.identify(sha256)
            except SourceError as e:
                logger.warning("Identify on %s failed: %s", adapter.id, e)
                continue
            if detail is not None:
                results.append(IdentifyResult(source=adapter.id, model=detail, version_id=detail.versions[0].id if detail.versions else None))
        if not results:
            archived = self._civarchive(sha256)
            if archived is not None:
                results.append(archived)
        return results

    def _civarchive(self, sha256: str) -> IdentifyResult | None:
        try:
            response = self._client().get(f"{CIVARCHIVE_URL}/api/sha256/{sha256}")
        except httpx.HTTPError as e:
            logger.info("CivitAI Archive lookup failed: %s", e)
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        files = data.get("files") or []
        if not files:
            return None
        f = files[0]
        model_id = str(f.get("model_id") or "")
        name = f.get("filename") or sha256
        detail = ModelDetail(source="civarchive", id=model_id or sha256, name=name, page_url=f"{CIVARCHIVE_URL}/models/{model_id}" if model_id else None)
        return IdentifyResult(source="civarchive", model=detail, version_id=str(f.get("model_version_id") or "") or None, file_name=name)
