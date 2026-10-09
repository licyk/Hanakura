"""Civitai: https://developer.civitai.com/site/reference/"""

import re
from typing import Any

from hanakura.core.detection.models import normalize_base_model, normalize_kind
from hanakura.core.errors import NotFoundError
from hanakura.core.sources.base import SourceAdapter
from hanakura.core.sources.models import (
    DownloadRequest,
    FilterOption,
    ModelDetail,
    ModelFile,
    ModelImage,
    ModelPermission,
    ModelStats,
    ModelSummary,
    ModelVersion,
    PermissionId,
    SearchPage,
    SearchQuery,
    SourceCapabilities,
)

# Our kind -> Civitai model types.
KIND_TO_TYPES: dict[str, list[str]] = {
    "checkpoint": ["Checkpoint"],
    "lora": ["LORA", "LoCon", "DoRA"],
    "embedding": ["TextualInversion"],
    "vae": ["VAE"],
    "controlnet": ["Controlnet"],
    "upscaler": ["Upscaler"],
    "hypernetwork": ["Hypernetwork"],
}
KIND_LABELS = {
    "checkpoint": "Checkpoint",
    "lora": "LoRA",
    "embedding": "Embedding",
    "vae": "VAE",
    "controlnet": "ControlNet",
    "upscaler": "Upscaler",
    "hypernetwork": "Hypernetwork",
}
BASE_MODEL_FILTERS = [
    "SD 1.5",
    "SD 2.1",
    "SDXL 1.0",
    "Pony",
    "Illustrious",
    "NoobAI",
    "SD 3.5",
    "Flux.1 D",
    "Flux.1 S",
    "Flux.2 D",
    "Chroma",
    "Qwen",
    "HiDream",
    "Wan Video 2.2 T2V-A14B",
    "Hunyuan Video",
    "Other",
]
SORTS = ["Highest Rated", "Most Downloaded", "Newest"]
_SIZE_SEGMENT = re.compile(r"/(width=\d+|original=true)/")


def thumbnail(url: str | None, width: int = 450) -> str | None:
    """Ask Civitai's image CDN for a card-sized image instead of the original."""
    if not url:
        return None
    return _SIZE_SEGMENT.sub(f"/width={width}/", url, count=1)


def _image(img: dict[str, Any]) -> ModelImage:
    return ModelImage(
        url=img.get("url", ""),
        nsfw_level=int(img.get("nsfwLevel") or 0),
        width=img.get("width"),
        height=img.get("height"),
        is_video=img.get("type") == "video",
    )


# Older answers name one commercial level, each including the ones before it; newer ones list every use.
_COMMERCIAL_LEVELS = {
    "none": set(),
    "image": {"Image"},
    "rentcivit": {"Image", "RentCivit"},
    "rent": {"Image", "RentCivit", "Rent"},
    "sell": {"Image", "RentCivit", "Rent", "Sell"},
}


def _commercial_uses(value: Any) -> set[str] | None:
    if isinstance(value, list):
        return {str(v) for v in value}
    if isinstance(value, str):
        return _COMMERCIAL_LEVELS.get(value.lower())
    return None


def _permissions(m: dict[str, Any]) -> list[ModelPermission]:
    """The model's permissions in the order Civitai's own page lists them; a field the answer lacks is left out rather than read as forbidden."""
    uses = _commercial_uses(m.get("allowCommercialUse"))
    flags: list[tuple[PermissionId, Any]] = [
        ("credit", m.get("allowNoCredit")),
        ("sell_images", None if uses is None else "Image" in uses),
        ("rent", None if uses is None else "Rent" in uses),
        ("generate_on_civitai", None if uses is None else "RentCivit" in uses),
        ("derivatives", m.get("allowDerivatives")),
        ("sell_model", None if uses is None else "Sell" in uses),
        ("different_license", m.get("allowDifferentLicense")),
    ]
    return [ModelPermission(id=pid, allowed=allowed) for pid, allowed in flags if isinstance(allowed, bool)]


class CivitaiAdapter(SourceAdapter):
    id = "civitai"
    name = "Civitai"
    default_base_url = "https://civitai.com"

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            search=True,
            identify=True,
            needs_token=False,
            kinds=[FilterOption(value=k, label=v) for k, v in KIND_LABELS.items()],
            base_models=[FilterOption(value=b, label=b) for b in BASE_MODEL_FILTERS],
            sorts=[FilterOption(value=s, label=s) for s in SORTS],
            nsfw_filter=True,
        )

    @property
    def api(self) -> str:
        return f"{self.base_url}/api/v1"

    def search(self, query: SearchQuery) -> SearchPage:
        params: list[tuple[str, str | int]] = [("limit", query.limit), ("nsfw", "true" if query.nsfw else "false")]
        if query.query:
            params.append(("query", query.query))
        for t in KIND_TO_TYPES.get(query.kind or "", []):
            params.append(("types", t))
        if query.base_model:
            params.append(("baseModels", query.base_model))
        if query.sort:
            params.append(("sort", query.sort))
        if query.cursor:
            params.append(("cursor", query.cursor))
        key = tuple(params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        data = self._get(f"{self.api}/models", "Civitai search", params=params, headers=self.auth_headers()).json()
        items = [self._summary(m) for m in data.get("items", [])]
        next_cursor = (data.get("metadata") or {}).get("nextCursor")
        page = SearchPage(items=items, next_cursor=str(next_cursor) if next_cursor else None)
        self.cache.set(key, page)
        return page

    def _summary(self, m: dict[str, Any]) -> ModelSummary:
        versions = m.get("modelVersions") or []
        first = versions[0] if versions else {}
        images = first.get("images") or []
        preview = next((i for i in images if i.get("type") != "video"), images[0] if images else None)
        stats = m.get("stats") or {}
        base_label = first.get("baseModel")
        return ModelSummary(
            source=self.id,
            id=str(m["id"]),
            name=m.get("name") or str(m["id"]),
            kind=normalize_kind(m.get("type")) or (m.get("type") or "").lower() or None,
            base_model=normalize_base_model(base_label),
            base_model_label=base_label,
            preview_url=thumbnail(preview.get("url")) if preview else None,
            preview_is_video=bool(preview and preview.get("type") == "video"),
            creator=(m.get("creator") or {}).get("username"),
            nsfw_level=int((preview or {}).get("nsfwLevel") or (4 if m.get("nsfw") else 0)),
            stats=ModelStats(downloads=stats.get("downloadCount"), likes=stats.get("thumbsUpCount"), rating=stats.get("rating")),
            tags=list(m.get("tags") or []),
            page_url=f"{self.base_url}/models/{m['id']}",
        )

    def _file(self, f: dict[str, Any]) -> ModelFile:
        hashes = f.get("hashes") or {}
        size_kb = f.get("sizeKB")
        meta = f.get("metadata") or {}
        return ModelFile(
            id=str(f.get("id")),
            name=f.get("name") or "",
            size=int(size_kb * 1024) if size_kb else None,
            sha256=(hashes.get("SHA256") or "").lower() or None,
            kind=f.get("type"),
            primary=bool(f.get("primary")),
            scan_result=f.get("pickleScanResult") or f.get("virusScanResult"),
            download_ref=f.get("downloadUrl") or "",
            format=meta.get("format"),
        )

    def _detail(self, m: dict[str, Any]) -> ModelDetail:
        summary = self._summary(m)
        versions = []
        for v in m.get("modelVersions") or []:
            versions.append(
                ModelVersion(
                    id=str(v["id"]),
                    name=v.get("name") or str(v["id"]),
                    base_model=normalize_base_model(v.get("baseModel")),
                    base_model_label=v.get("baseModel"),
                    published_at=v.get("publishedAt"),
                    trained_words=list(v.get("trainedWords") or []),
                    files=[self._file(f) for f in v.get("files") or []],
                    images=[_image(i) for i in v.get("images") or []],
                )
            )
        return ModelDetail(
            **summary.model_dump(),
            description=m.get("description"),
            versions=versions,
            permissions=_permissions(m),
            trained_words=versions[0].trained_words if versions else [],
            images=versions[0].images if versions else [],
            raw=None,
        )

    def get_model(self, model_id: str) -> ModelDetail:
        cached = self.cache.get(("model", model_id))
        if cached is not None:
            return cached
        data = self._get(f"{self.api}/models/{model_id}", f"Civitai model {model_id}", headers=self.auth_headers()).json()
        detail = self._detail(data)
        self.cache.set(("model", model_id), detail)
        return detail

    def resolve_download(self, file: ModelFile) -> DownloadRequest:
        if not file.download_ref:
            raise NotFoundError(f"No download URL for {file.name}")
        # The token goes in a header, never in the URL. httpx drops it when the redirect leaves civitai.com.
        return DownloadRequest(url=file.download_ref, headers=self.auth_headers(), file_name=file.name or None, size=file.size, sha256=file.sha256)

    def identify(self, sha256: str) -> ModelDetail | None:
        try:
            version = self._get(f"{self.api}/model-versions/by-hash/{sha256}", "Civitai hash lookup", headers=self.auth_headers()).json()
        except NotFoundError:
            return None
        model_id = version.get("modelId")
        if model_id is None:
            return None
        try:
            detail = self.get_model(str(model_id))
        except NotFoundError:
            return None
        # Put the matching version first.
        vid = str(version.get("id"))
        detail.versions.sort(key=lambda v: v.id != vid)
        return detail
