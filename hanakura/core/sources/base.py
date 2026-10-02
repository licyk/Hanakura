"""The source adapter interface and shared HTTP helpers."""

import email.utils
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import httpx

from hanakura.core.errors import AuthRequiredError, NotFoundError, RateLimitedError, SourceError
from hanakura.core.settings.models import SourceSettings
from hanakura.core.sources.models import DownloadRequest, ModelDetail, ModelFile, SearchPage, SearchQuery, SourceCapabilities

USER_AGENT = "hanakura"


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - time.time())


def raise_for_status(response: httpx.Response, what: str) -> None:
    """Translate an upstream error status into a domain error."""
    status = response.status_code
    if status < 400:
        return
    if status == 429:
        raise RateLimitedError(f"{what}: rate limited", retry_after=parse_retry_after(response.headers.get("Retry-After")))
    if status in (401, 403):
        raise AuthRequiredError(f"{what}: this needs a valid token (HTTP {status})")
    if status == 404:
        raise NotFoundError(f"{what}: not found")
    raise SourceError(f"{what}: HTTP {status}", {"status": status})


class TTLCache:
    """A small in-memory cache for search results."""

    def __init__(self, ttl: float = 120.0, max_items: int = 256) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit is None or hit[0] < time.monotonic():
                self._data.pop(key, None)
                return None
            return hit[1]

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic() + self.ttl, value)


class SourceAdapter(ABC):
    id: str = ""
    name: str = ""
    default_base_url: str = ""

    def __init__(
        self,
        client: Callable[[], httpx.Client],
        settings: Callable[[], SourceSettings],
        credentials: Callable[[], dict[str, str]] | None = None,
        on_unauthorized: Callable[[], bool] | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        # Where a source has more than one way to authenticate (Civitai: a manual token or OAuth),
        # the headers come from its authentication service instead of the settings token, and a
        # 401 gives that service one chance to refresh before the request is retried.
        self._credentials = credentials
        self._on_unauthorized = on_unauthorized
        self.cache = TTLCache()

    @property
    def client(self) -> httpx.Client:
        return self._client()

    @property
    def settings(self) -> SourceSettings:
        return self._settings()

    @property
    def base_url(self) -> str:
        return (self.settings.base_url or self.default_base_url).rstrip("/")

    def auth_headers(self) -> dict[str, str]:
        """The token header for this source's own host. Never attach it to another host."""
        if self._credentials is not None:
            return self._credentials()
        token = self.settings.token
        return {"Authorization": f"Bearer {token}"} if token else {}

    @property
    @abstractmethod
    def capabilities(self) -> SourceCapabilities: ...

    @abstractmethod
    def search(self, query: SearchQuery) -> SearchPage: ...

    @abstractmethod
    def get_model(self, model_id: str) -> ModelDetail: ...

    def list_files(self, model_id: str, version_id: str | None = None) -> list[ModelFile]:
        detail = self.get_model(model_id)
        if not detail.versions:
            return []
        version = next((v for v in detail.versions if v.id == version_id), None) if version_id else detail.versions[0]
        if version is None:
            raise NotFoundError(f"No version {version_id} of {model_id}")
        return version.files

    @abstractmethod
    def resolve_download(self, file: ModelFile) -> DownloadRequest:
        """Return the URL and headers for a file, at download time. The adapter adds its own token."""

    def identify(self, sha256: str) -> ModelDetail | None:
        return None

    def _get(self, url: str, what: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.client.get(url, **kwargs)
            if response.status_code == 401 and self._on_unauthorized is not None and self._on_unauthorized():
                # The token was refreshed: try once more with the new one, and only once.
                kwargs["headers"] = {**(kwargs.get("headers") or {}), **self.auth_headers()}
                response = self.client.get(url, **kwargs)
        except httpx.HTTPError as e:
            raise SourceError(f"{what}: {e}") from e
        raise_for_status(response, what)
        return response
