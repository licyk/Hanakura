"""ModelScope metadata over its REST API. The list API and the file API use different prefixes."""

from datetime import datetime, timezone
from typing import Any

from hanakura.core.errors import SourceError
from hanakura.core.hubs.base import HubAdapter
from hanakura.core.hubs.models import HubPage, HubQuery, RepoDetail, RepoFile, RepoSummary


class ModelScopeAdapter(HubAdapter):
    id = "modelscope"
    name = "ModelScope"
    default_endpoint = "https://modelscope.cn"
    default_revision = "master"
    sorts = ("downloads", "likes", "last_modified")

    def _summary(self, m: dict[str, Any]) -> RepoSummary:
        repo_id = m["id"]
        return RepoSummary(
            hub=self.id,
            id=repo_id,
            author=repo_id.split("/")[0],
            name=m.get("display_name") or repo_id.split("/")[-1],
            downloads=m.get("downloads"),
            likes=m.get("likes"),
            tags=list(m.get("tags") or []),
            task=(m.get("tasks") or [None])[0],
            last_modified=m.get("last_modified"),
            gated=bool(m.get("gated")),
            private=bool(m.get("private")),
            page_url=f"{self.endpoint}/models/{repo_id}",
        )

    def search(self, query: HubQuery) -> HubPage:
        page_number = int(query.cursor or 1)
        params: dict[str, Any] = {"search": query.query, "page_size": query.limit, "page_number": page_number}
        if query.sort:
            params["sort"] = query.sort
        key = tuple(sorted(params.items()))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        body = self._get(f"{self.endpoint}/openapi/v1/models", "ModelScope search", params=params).json()
        if not body.get("success", True):
            raise SourceError(f"ModelScope search failed: {body.get('message')}")
        data = body.get("data") or {}
        items = [self._summary(m) for m in data.get("models") or []]
        total = data.get("total_count")
        more = total is not None and page_number * query.limit < total
        page = HubPage(items=items, next_cursor=str(page_number + 1) if more else None, total=total)
        self.cache.set(key, page)
        return page

    def get_repo(self, repo_id: str, revision: str | None = None) -> RepoDetail:
        rev = revision or self.default_revision
        key = ("repo", repo_id, rev)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        info = (self._get(f"{self.endpoint}/api/v1/models/{repo_id}", f"ModelScope repo {repo_id}").json() or {}).get("Data") or {}
        listing = self._get(f"{self.endpoint}/api/v1/models/{repo_id}/repo/files", f"ModelScope files of {repo_id}", params={"Revision": rev, "Recursive": "true"}).json()
        files = [
            RepoFile(path=f["Path"], size=f.get("Size"), sha256=(f.get("Sha256") or None), lfs=bool(f.get("IsLFS")))
            for f in ((listing.get("Data") or {}).get("Files") or [])
            if f.get("Type") != "tree"
        ]
        updated = info.get("LastUpdatedTime")
        detail = RepoDetail(
            hub=self.id,
            id=repo_id,
            author=repo_id.split("/")[0],
            name=info.get("ChineseName") or info.get("Name") or repo_id.split("/")[-1],
            downloads=info.get("Downloads"),
            likes=info.get("Stars"),
            tags=[str(t) for t in info.get("Tags") or []] if isinstance(info.get("Tags"), list) else [],
            last_modified=datetime.fromtimestamp(updated, tz=timezone.utc) if isinstance(updated, (int, float)) and updated > 0 else None,
            page_url=f"{self.endpoint}/models/{repo_id}",
            revision=rev,
            description=info.get("ReadMeContent") or info.get("Description"),
            license=info.get("License"),
            files=files,
            total_size=sum(f.size or 0 for f in files) or None,
        )
        self.cache.set(key, detail)
        return detail
