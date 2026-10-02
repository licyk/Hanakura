"""OpenModelDB: an index of upscaling models, published as one JSON file."""

import threading
import time
from typing import Any
from urllib.parse import urlparse

from hanakura.core.errors import NotFoundError
from hanakura.core.sources.base import SourceAdapter
from hanakura.core.sources.models import (
    DownloadRequest,
    FilterOption,
    ModelDetail,
    ModelFile,
    ModelImage,
    ModelSummary,
    ModelVersion,
    SearchPage,
    SearchQuery,
    SourceCapabilities,
)

INDEX_TTL = 6 * 3600
_SKIPPED_HOSTS = ("mega.nz", "drive.google.com", "mega.co.nz")


def _usable_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and not any(parsed.netloc.endswith(h) for h in _SKIPPED_HOSTS)


def _preview(entry: dict[str, Any]) -> str | None:
    for img in entry.get("images") or []:
        if not isinstance(img, dict):
            continue
        url = img.get("SR") or img.get("url") or img.get("thumbnail")
        if url:
            return url
    thumb = entry.get("thumbnail")
    if isinstance(thumb, dict):
        return thumb.get("SR") or thumb.get("url")
    return thumb if isinstance(thumb, str) else None


class OpenModelDBAdapter(SourceAdapter):
    id = "openmodeldb"
    name = "OpenModelDB"
    default_base_url = "https://openmodeldb.info"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._index: dict[str, Any] | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> SourceCapabilities:
        archs = sorted({str(e.get("architecture")) for e in (self._index or {}).values() if e.get("architecture")})
        return SourceCapabilities(
            search=True,
            kinds=[FilterOption(value="upscaler", label="Upscaler")],
            base_models=[FilterOption(value=a, label=a) for a in archs],
            sorts=[FilterOption(value="newest", label="Newest"), FilterOption(value="name", label="Name")],
        )

    def index(self) -> dict[str, Any]:
        with self._lock:
            if self._index is None or time.monotonic() - self._loaded_at > INDEX_TTL:
                data = self._get(f"{self.base_url}/api/v1/models.json", "OpenModelDB index").json()
                self._index = data if isinstance(data, dict) else {}
                self._loaded_at = time.monotonic()
            return self._index

    def _summary(self, model_id: str, e: dict[str, Any]) -> ModelSummary:
        author = e.get("author")
        scale = e.get("scale")
        tags = [str(t) for t in e.get("tags") or []]
        if scale:
            tags.insert(0, f"{scale}x")
        return ModelSummary(
            source=self.id,
            id=model_id,
            name=e.get("name") or model_id,
            kind="upscaler",
            base_model=None,
            base_model_label=e.get("architecture"),
            preview_url=_preview(e),
            creator=", ".join(author) if isinstance(author, list) else author,
            tags=tags,
            page_url=f"{self.base_url}/models/{model_id}",
        )

    def search(self, query: SearchQuery) -> SearchPage:
        if query.kind and query.kind != "upscaler":
            return SearchPage(items=[])
        needle = query.query.lower().strip()
        hits: list[tuple[str, dict[str, Any]]] = []
        for model_id, e in self.index().items():
            if query.base_model and str(e.get("architecture")) != query.base_model:
                continue
            if needle:
                author = e.get("author")
                haystack = " ".join(
                    [
                        model_id,
                        str(e.get("name", "")),
                        " ".join(author) if isinstance(author, list) else str(author or ""),
                        " ".join(map(str, e.get("tags") or [])),
                        str(e.get("architecture", "")),
                    ]
                ).lower()
                if not all(word in haystack for word in needle.split()):
                    continue
            hits.append((model_id, e))
        if query.sort == "name":
            hits.sort(key=lambda h: str(h[1].get("name", h[0])).lower())
        else:
            hits.sort(key=lambda h: str(h[1].get("date", "")), reverse=True)
        start = int(query.cursor or 0)
        page = hits[start : start + query.limit]
        nxt = start + query.limit
        return SearchPage(items=[self._summary(i, e) for i, e in page], next_cursor=str(nxt) if nxt < len(hits) else None)

    def get_model(self, model_id: str) -> ModelDetail:
        e = self.index().get(model_id)
        if e is None:
            raise NotFoundError(f"OpenModelDB has no model {model_id}")
        files: list[ModelFile] = []
        for i, r in enumerate(e.get("resources") or []):
            urls = [u for u in r.get("urls") or [] if _usable_url(u)]
            if not urls:
                continue
            ext = r.get("type") or "pth"
            files.append(
                ModelFile(
                    id=str(i),
                    name=f"{model_id}.{ext}",
                    size=r.get("size"),
                    sha256=(r.get("sha256") or "").lower() or None,
                    kind="upscaler",
                    primary=not files,
                    download_ref=urls[0],
                    format=r.get("platform"),
                )
            )
        images = [ModelImage(url=u) for u in (_preview({"images": [img]}) for img in e.get("images") or []) if u]
        summary = self._summary(model_id, e)
        return ModelDetail(
            **summary.model_dump(),
            description=e.get("description"),
            license=e.get("license"),
            images=images,
            versions=[ModelVersion(id="latest", name=str(e.get("date") or "latest"), base_model_label=e.get("architecture"), files=files, images=images)],
        )

    def resolve_download(self, file: ModelFile) -> DownloadRequest:
        # Files are hosted elsewhere, so no token is ever attached.
        return DownloadRequest(url=file.download_ref, file_name=file.name, size=file.size, sha256=file.sha256)
