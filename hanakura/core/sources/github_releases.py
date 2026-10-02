"""GitHub Releases: a curated list of repositories that publish model files as release assets."""

import re
from typing import Any

from hanakura.core.errors import NotFoundError
from hanakura.core.sources.base import SourceAdapter
from hanakura.core.sources.models import (
    DownloadRequest,
    FilterOption,
    ModelDetail,
    ModelFile,
    ModelSummary,
    ModelVersion,
    SearchPage,
    SearchQuery,
    SourceCapabilities,
)

CURATED: dict[str, tuple[str, str]] = {
    "xinntao/Real-ESRGAN": ("upscaler", "Real-ESRGAN upscalers"),
    "xinntao/ESRGAN": ("upscaler", "ESRGAN upscalers"),
    "JingyunLiang/SwinIR": ("upscaler", "SwinIR upscalers"),
    "cszn/SCUNet": ("upscaler", "SCUNet denoisers"),
    "TencentARC/GFPGAN": ("face_restore", "GFPGAN face restoration"),
    "sczhou/CodeFormer": ("face_restore", "CodeFormer face restoration"),
    "Mikubill/sd-webui-controlnet": ("controlnet", "ControlNet extension assets"),
}
MODEL_ASSET_EXTENSIONS = (".pth", ".pt", ".safetensors", ".ckpt", ".bin", ".onnx", ".zip")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubReleasesAdapter(SourceAdapter):
    id = "github"
    name = "GitHub Releases"
    default_base_url = "https://api.github.com"

    @property
    def capabilities(self) -> SourceCapabilities:
        kinds = sorted({k for k, _ in CURATED.values()})
        return SourceCapabilities(search=True, kinds=[FilterOption(value=k, label=k.replace("_", " ").title()) for k in kinds])

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", **self.auth_headers()}

    def search(self, query: SearchQuery) -> SearchPage:
        needle = query.query.strip()
        repos: list[str] = []
        if _REPO.match(needle):
            repos.append(needle)
        for repo, (kind, title) in CURATED.items():
            if query.kind and kind != query.kind:
                continue
            if needle and needle.lower() not in f"{repo} {title}".lower():
                continue
            if repo not in repos:
                repos.append(repo)
        items = [
            ModelSummary(
                source=self.id,
                id=repo,
                name=CURATED.get(repo, ("", repo))[1] or repo,
                kind=CURATED.get(repo, (None, ""))[0],
                creator=repo.split("/")[0],
                tags=[repo],
                page_url=f"https://github.com/{repo}",
            )
            for repo in repos[: query.limit]
        ]
        return SearchPage(items=items)

    def get_model(self, model_id: str) -> ModelDetail:
        if not _REPO.match(model_id):
            raise NotFoundError(f"Not a repository id: {model_id}")
        cached = self.cache.get(("model", model_id))
        if cached is not None:
            return cached
        releases: list[dict[str, Any]] = self._get(
            f"{self.base_url}/repos/{model_id}/releases", f"GitHub releases of {model_id}", params={"per_page": 30}, headers=self._headers()
        ).json()
        kind = CURATED.get(model_id, (None, ""))[0]
        versions: list[ModelVersion] = []
        for rel in releases:
            files = [
                ModelFile(
                    id=str(a["id"]),
                    name=a["name"],
                    size=a.get("size"),
                    sha256=(a.get("digest") or "").removeprefix("sha256:").lower() or None,
                    kind=kind,
                    download_ref=a["browser_download_url"],
                )
                for a in rel.get("assets") or []
                if str(a.get("name", "")).lower().endswith(MODEL_ASSET_EXTENSIONS)
            ]
            if files:
                files[0].primary = True
                versions.append(ModelVersion(id=str(rel["id"]), name=rel.get("name") or rel.get("tag_name") or str(rel["id"]), published_at=rel.get("published_at"), files=files))
        detail = ModelDetail(
            source=self.id,
            id=model_id,
            name=CURATED.get(model_id, ("", model_id))[1] or model_id,
            kind=kind,
            creator=model_id.split("/")[0],
            page_url=f"https://github.com/{model_id}",
            description=releases[0].get("body") if releases else None,
            versions=versions,
        )
        self.cache.set(("model", model_id), detail)
        return detail

    def resolve_download(self, file: ModelFile) -> DownloadRequest:
        # Public assets need no token, and the token belongs to api.github.com only.
        return DownloadRequest(url=file.download_ref, file_name=file.name, size=file.size, sha256=file.sha256)
