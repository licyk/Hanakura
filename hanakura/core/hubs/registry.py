"""Registry of repository hubs."""

from collections.abc import Callable

import httpx

from hanakura.core.errors import NotFoundError, ValidationError
from hanakura.core.hubs.base import HubAdapter
from hanakura.core.hubs.huggingface import HuggingFaceAdapter
from hanakura.core.hubs.models import HubInfo, HubPage, HubQuery, RepoDetail, RepoFile
from hanakura.core.hubs.modelscope import ModelScopeAdapter
from hanakura.core.settings import SettingsService
from hanakura.core.settings.models import SourceSettings

HUB_CLASSES: list[type[HubAdapter]] = [HuggingFaceAdapter, ModelScopeAdapter]


def parse_repo_ref(text: str) -> tuple[str | None, str, str | None]:
    """Accept ``owner/name`` or a hub URL. Returns ``(hub or None, repo_id, revision or None)``."""
    text = text.strip().rstrip("/")
    hub = None
    revision = None
    for prefix, name in (
        ("https://huggingface.co/", "huggingface"),
        ("https://hf-mirror.com/", "huggingface"),
        ("https://modelscope.cn/models/", "modelscope"),
        ("https://www.modelscope.cn/models/", "modelscope"),
    ):
        if text.startswith(prefix):
            hub = name
            text = text[len(prefix) :]
            break
    parts = text.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValidationError(f"Not a repository id: {text!r}")
    if len(parts) >= 4 and parts[2] in ("tree", "blob", "resolve", "files"):
        revision = parts[3]
    return hub, f"{parts[0]}/{parts[1]}", revision


class HubRegistry:
    def __init__(self, settings: SettingsService, client: Callable[[], httpx.Client], adapters: list[HubAdapter] | None = None) -> None:
        self.settings_service = settings
        if adapters is None:
            adapters = [cls(client, self._settings_getter(cls.id)) for cls in HUB_CLASSES]
        self.adapters: dict[str, HubAdapter] = {a.id: a for a in adapters}

    def _settings_getter(self, hub_id: str) -> Callable[[], SourceSettings]:
        return lambda: self.settings_service.settings.sources.get(hub_id) or SourceSettings()

    def list_hubs(self) -> list[HubInfo]:
        return [
            HubInfo(
                id=a.id,
                name=a.name,
                enabled=a.settings.enabled,
                token_configured=bool(a.settings.token),
                endpoint=a.endpoint,
                default_revision=a.default_revision,
                sorts=list(a.sorts),
            )
            for a in self.adapters.values()
        ]

    def get(self, hub_id: str) -> HubAdapter:
        adapter = self.adapters.get(hub_id)
        if adapter is None:
            raise NotFoundError(f"Unknown hub {hub_id!r}")
        if not adapter.settings.enabled:
            raise ValidationError(f"Hub {hub_id!r} is disabled in settings")
        return adapter

    def search(self, hub_id: str, query: HubQuery) -> HubPage:
        return self.get(hub_id).search(query)

    def get_repo(self, hub_id: str, repo_id: str, revision: str | None = None) -> RepoDetail:
        return self.get(hub_id).get_repo(repo_id, revision)

    def list_files(self, hub_id: str, repo_id: str, revision: str | None = None) -> list[RepoFile]:
        return self.get(hub_id).list_files(repo_id, revision)
