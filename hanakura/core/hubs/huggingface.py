"""Hugging Face metadata over its REST API."""

from typing import Any

from hanakura.core.errors import SourceError
from hanakura.core.hubs.base import HubAdapter
from hanakura.core.hubs.models import HubPage, HubQuery, RepoDetail, RepoFile, RepoSummary

MAX_README_BYTES = 256 * 1024


class HuggingFaceAdapter(HubAdapter):
    id = "huggingface"
    name = "Hugging Face"
    default_endpoint = "https://huggingface.co"
    default_revision = "main"
    sorts = ("downloads", "likes", "lastModified", "trendingScore")

    def _summary(self, m: dict[str, Any]) -> RepoSummary:
        repo_id = m.get("id") or m.get("modelId")
        if not isinstance(repo_id, str) or not repo_id:
            raise SourceError("Hugging Face returned a repository without a valid id")
        return RepoSummary(
            hub=self.id,
            id=repo_id,
            author=m.get("author") or repo_id.split("/")[0],
            name=repo_id.split("/")[-1],
            downloads=m.get("downloads"),
            likes=m.get("likes"),
            tags=list(m.get("tags") or []),
            task=m.get("pipeline_tag"),
            last_modified=m.get("lastModified") or m.get("createdAt"),
            gated=bool(m.get("gated")),
            private=bool(m.get("private")),
            page_url=f"{self.endpoint}/{repo_id}",
        )

    def search(self, query: HubQuery) -> HubPage:
        if query.cursor:
            url, params = query.cursor, None
            if not url.startswith(self.endpoint + "/"):
                # The cursor is the next-page URL; never follow one to another host.
                url, params = f"{self.endpoint}/api/models", {"search": query.query, "limit": query.limit}
        else:
            url = f"{self.endpoint}/api/models"
            params = {"search": query.query, "limit": query.limit, "sort": query.sort or "downloads", "direction": -1}
        key = (url, tuple(sorted((params or {}).items())))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        response = self._get(url, "Hugging Face search", params=params)
        next_url = response.links.get("next", {}).get("url")
        page = HubPage(items=[self._summary(m) for m in response.json()], next_cursor=next_url)
        self.cache.set(key, page)
        return page

    def get_repo(self, repo_id: str, revision: str | None = None) -> RepoDetail:
        rev = revision or self.default_revision
        key = ("repo", repo_id, rev)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        url = f"{self.endpoint}/api/models/{repo_id}" if not revision else f"{self.endpoint}/api/models/{repo_id}/revision/{revision}"
        m = self._get(url, f"Hugging Face repo {repo_id}", params={"blobs": "true"}).json()
        files = []
        for s in m.get("siblings") or []:
            lfs = s.get("lfs") or {}
            files.append(RepoFile(path=s["rfilename"], size=s.get("size") if s.get("size") is not None else lfs.get("size"), sha256=lfs.get("sha256"), lfs=bool(lfs)))
        card = m.get("cardData") or {}
        detail = RepoDetail(
            **self._summary(m).model_dump(),
            revision=rev,
            sha=m.get("sha"),
            description=self._readme(repo_id, rev),
            license=card.get("license") if isinstance(card, dict) else None,
            files=files,
            total_size=sum(f.size or 0 for f in files) or None,
        )
        self.cache.set(key, detail)
        return detail

    def _readme(self, repo_id: str, revision: str) -> str | None:
        try:
            response = self.client.get(f"{self.endpoint}/{repo_id}/raw/{revision}/README.md", headers=self.auth_headers())
        except Exception:  # noqa: BLE001 - the README is optional
            return None
        if response.status_code != 200:
            return None
        return response.content[:MAX_README_BYTES].decode("utf-8", errors="replace")
