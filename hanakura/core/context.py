"""Build every service once. The API and the command line both start here."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from hanakura.core.auth import CivitaiAuthService, CredentialStore, open_store
from hanakura.core.db import Database
from hanakura.core.detection import DetectionService
from hanakura.core.downloads.manager import DownloadManager
from hanakura.core.events import EventBus, LocalEventBus
from hanakura.core.hubs import HubRegistry
from hanakura.core.library import LibraryService
from hanakura.core.net.http import HttpClientProvider
from hanakura.core.settings import SettingsService
from hanakura.core.sources import SourceRegistry

DB_FILE_NAME = "hanakura.db"


@dataclass
class Services:
    settings: SettingsService
    events: EventBus
    db: Database
    http: HttpClientProvider
    auth: CivitaiAuthService
    sources: SourceRegistry
    hubs: HubRegistry
    downloads: DownloadManager
    library: LibraryService
    detection: DetectionService

    def close(self) -> None:
        self.downloads.shutdown()
        self.http.close()
        self.db.close()


def build_services(
    data_dir: Path | None = None,
    settings_path: Path | None = None,
    environ: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    owned_downloads_only: bool = False,
    credential_store: CredentialStore | None = None,
    settings_overrides: dict[str, Any] | None = None,
    roots_locked: bool = False,
) -> Services:
    """Create all services.

    ``settings_overrides`` and ``roots_locked`` come from a host application embedding this
    package. ``transport`` replaces the network and ``credential_store`` the keyring, in tests.
    """
    settings = SettingsService(data_dir=data_dir, settings_path=settings_path, environ=environ, overrides=settings_overrides)
    events = LocalEventBus()
    db = Database(settings.data_dir / DB_FILE_NAME)
    http = HttpClientProvider(settings, transport=transport)
    detection = DetectionService(db)
    library = LibraryService(settings, detection, events, roots_locked=roots_locked)
    auth = CivitaiAuthService(settings, credential_store or open_store(settings.data_dir, settings.settings.auth.civitai.use_keyring), http.get)
    sources = SourceRegistry(settings, http.get, auth=auth)
    hubs = HubRegistry(settings, http.get)
    downloads = DownloadManager(settings, db, events, sources, hubs, library, detection, http, owned_only=owned_downloads_only)
    return Services(settings=settings, events=events, db=db, http=http, auth=auth, sources=sources, hubs=hubs, downloads=downloads, library=library, detection=detection)
