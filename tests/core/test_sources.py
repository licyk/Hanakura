import httpx
import pytest

from hanakura.core.context import build_services
from hanakura.core.errors import AuthRequiredError, RateLimitedError, SourceError
from hanakura.core.hubs.registry import parse_repo_ref
from hanakura.core.sources.models import SearchQuery
from tests.core.test_downloads import CIVITAI_MODEL


@pytest.fixture
def make(tmp_path):
    made = []

    def factory(handler):
        s = build_services(data_dir=tmp_path / f"d{len(made)}", environ={}, transport=httpx.MockTransport(handler))
        made.append(s)
        return s

    yield factory
    for s in made:
        s.close()


def test_civitai_search_params_and_parsing(make):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [CIVITAI_MODEL], "metadata": {"nextCursor": "abc"}})

    s = make(handler)
    page = s.sources.search("civitai", SearchQuery(query="detail", kind="lora", base_model="SDXL 1.0", limit=5))
    params = seen[0].url.params
    assert params.get_list("types") == ["LORA", "LoCon", "DoRA"]
    assert params["baseModels"] == "SDXL 1.0" and params["query"] == "detail" and params["nsfw"] == "true"
    item = page.items[0]
    assert (item.id, item.kind, item.base_model, item.creator) == ("7", "lora", "sdxl", "someone")
    assert item.preview_url == "https://image.civitai.com/x/abc/width=450/1.jpeg"
    assert page.next_cursor == "abc"
    # A second identical search is served from the cache.
    s.sources.search("civitai", SearchQuery(query="detail", kind="lora", base_model="SDXL 1.0", limit=5))
    assert len(seen) == 1


def test_nsfw_hide_mode(make):
    nsfw = {**CIVITAI_MODEL, "id": 8, "modelVersions": [{**CIVITAI_MODEL["modelVersions"][0], "images": [{"url": "https://i/x.jpg", "nsfwLevel": 16}]}]}
    s = make(lambda r: httpx.Response(200, json={"items": [CIVITAI_MODEL, nsfw], "metadata": {}}))
    s.settings.update({"content": {"nsfw_mode": "hide"}})
    page = s.sources.search("civitai", SearchQuery())
    assert [i.id for i in page.items] == ["7"]


def test_upstream_errors_are_domain_errors(make):
    s = make(lambda r: httpx.Response(429, headers={"Retry-After": "12"}))
    with pytest.raises(RateLimitedError) as e:
        s.sources.search("civitai", SearchQuery(query="a"))
    assert e.value.retry_after == 12
    s2 = make(lambda r: httpx.Response(401))
    with pytest.raises(AuthRequiredError):
        s2.sources.get_model("civitai", "1")


def test_civitai_detail_and_identify(make):
    def handler(request):
        path = request.url.path
        if path == "/api/v1/model-versions/by-hash/" + "a" * 64:
            return httpx.Response(200, json={"id": 70, "modelId": 7})
        if path == "/api/v1/models/7":
            return httpx.Response(200, json=CIVITAI_MODEL)
        return httpx.Response(404)

    s = make(handler)
    detail = s.sources.get_model("civitai", "7")
    f = detail.versions[0].files[0]
    assert f.primary and f.sha256 and f.sha256 == f.sha256.lower() and f.size == 1024 * 1024
    results = s.sources.identify("A" * 64)
    assert results[0].source == "civitai" and results[0].model.name == "Detail Tweaker"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (
            {"allowNoCredit": True, "allowCommercialUse": ["Image", "RentCivit"], "allowDerivatives": True, "allowDifferentLicense": False},
            [
                ("credit", True),
                ("sell_images", True),
                ("rent", False),
                ("generate_on_civitai", True),
                ("derivatives", True),
                ("sell_model", False),
                ("different_license", False),
            ],
        ),
        # The older single level includes every use below it.
        ({"allowCommercialUse": "Rent"}, [("sell_images", True), ("rent", True), ("generate_on_civitai", True), ("sell_model", False)]),
        (
            {"allowCommercialUse": ["None"], "allowNoCredit": False},
            [("credit", False), ("sell_images", False), ("rent", False), ("generate_on_civitai", False), ("sell_model", False)],
        ),
        # Missing fields are unknown, not forbidden.
        ({}, []),
    ],
)
def test_civitai_permissions(make, fields, expected):
    def handler(request):
        return httpx.Response(200, json={**CIVITAI_MODEL, **fields})

    detail = make(handler).sources.get_model("civitai", "7")
    assert [(p.id, p.allowed) for p in detail.permissions] == expected
    assert detail.license is None


def test_openmodeldb_local_search(make):
    index = {
        "4x-ultrasharp": {
            "name": "UltraSharp",
            "author": "Kim",
            "architecture": "esrgan",
            "scale": 4,
            "tags": ["photo"],
            "date": "2021-01-01",
            "resources": [{"platform": "pytorch", "type": "pth", "size": 10, "sha256": "ab", "urls": ["https://mega.nz/x", "https://objects.example/u.pth"]}],
        },
        "2x-other": {"name": "Other", "author": ["A", "B"], "architecture": "span", "scale": 2, "tags": [], "date": "2023-01-01", "resources": []},
    }
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=index)

    s = make(handler)
    page = s.sources.search("openmodeldb", SearchQuery(query="sharp"))
    assert [i.id for i in page.items] == ["4x-ultrasharp"] and page.items[0].tags[0] == "4x"
    assert [i.id for i in s.sources.search("openmodeldb", SearchQuery(base_model="span")).items] == ["2x-other"]
    files = s.sources.list_files("openmodeldb", "4x-ultrasharp")
    assert [f.download_ref for f in files] == ["https://objects.example/u.pth"]
    assert len(calls) == 1


def test_github_releases_repo_query(make):
    def handler(request):
        assert request.url.path == "/repos/owner/repo/releases"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "tag_name": "v1",
                    "assets": [
                        {"id": 9, "name": "m.pth", "size": 3, "browser_download_url": "https://github.com/o/r/m.pth"},
                        {"id": 10, "name": "src.tar.gz", "size": 1, "browser_download_url": "x"},
                    ],
                }
            ],
        )

    s = make(handler)
    assert s.sources.search("github", SearchQuery(query="owner/repo")).items[0].id == "owner/repo"
    detail = s.sources.get_model("github", "owner/repo")
    assert [f.name for f in detail.versions[0].files] == ["m.pth"]


def test_huggingface_search_cursor_and_repo(make):
    def handler(request):
        if request.url.path == "/api/models":
            return httpx.Response(
                200, json=[{"id": "o/r", "downloads": 1, "likes": 2, "tags": ["diffusers"]}], headers={"Link": '<https://huggingface.co/api/models?cursor=xyz>; rel="next"'}
            )
        if request.url.path == "/api/models/o/r":
            return httpx.Response(
                200,
                json={
                    "id": "o/r",
                    "sha": "abc",
                    "siblings": [{"rfilename": "a.safetensors", "size": 5, "lfs": {"sha256": "ff", "size": 5}}, {"rfilename": "README.md", "size": 1}],
                },
            )
        if request.url.path == "/o/r/raw/main/README.md":
            return httpx.Response(200, text="# hi")
        return httpx.Response(404)

    s = make(handler)
    from hanakura.core.hubs.models import HubQuery

    page = s.hubs.search("huggingface", HubQuery(query="x"))
    assert page.items[0].id == "o/r" and page.next_cursor == "https://huggingface.co/api/models?cursor=xyz"
    repo = s.hubs.get_repo("huggingface", "o/r")
    assert repo.files[0].sha256 == "ff" and repo.description == "# hi" and repo.total_size == 6


@pytest.mark.parametrize("record", [{}, {"id": None}, {"id": ""}, {"id": 123}])
def test_huggingface_rejects_missing_or_invalid_repo_id(make, record):
    from hanakura.core.hubs.models import HubQuery

    s = make(lambda request: httpx.Response(200, json=[record]))
    with pytest.raises(SourceError, match="without a valid id"):
        s.hubs.search("huggingface", HubQuery())


def test_huggingface_accepts_model_id_alias(make):
    from hanakura.core.hubs.models import HubQuery

    s = make(lambda request: httpx.Response(200, json=[{"modelId": "owner/repo"}]))
    repo = s.hubs.search("huggingface", HubQuery()).items[0]
    assert (repo.id, repo.author, repo.name) == ("owner/repo", "owner", "repo")


def test_modelscope_parsing(make):
    def handler(request):
        if request.url.path == "/openapi/v1/models":
            return httpx.Response(
                200, json={"success": True, "data": {"models": [{"id": "a/b", "display_name": "B", "downloads": 3}], "total_count": 40, "page_number": 1, "page_size": 30}}
            )
        if request.url.path == "/api/v1/models/a/b":
            return httpx.Response(200, json={"Code": 200, "Data": {"Downloads": 3, "Description": "desc"}})
        if request.url.path == "/api/v1/models/a/b/repo/files":
            assert request.url.params["Revision"] == "master"
            return httpx.Response(
                200, json={"Data": {"Files": [{"Path": "unet", "Type": "tree"}, {"Path": "unet/x.safetensors", "Size": 7, "Sha256": "aa", "IsLFS": True, "Type": "blob"}]}}
            )
        return httpx.Response(404)

    s = make(handler)
    from hanakura.core.hubs.models import HubQuery

    page = s.hubs.search("modelscope", HubQuery(query="b"))
    assert page.items[0].name == "B" and page.next_cursor == "2"
    repo = s.hubs.get_repo("modelscope", "a/b")
    assert [f.path for f in repo.files] == ["unet/x.safetensors"] and repo.revision == "master"


def test_parse_repo_ref():
    assert parse_repo_ref("stabilityai/sdxl-turbo") == (None, "stabilityai/sdxl-turbo", None)
    assert parse_repo_ref("https://huggingface.co/a/b/tree/dev") == ("huggingface", "a/b", "dev")
    assert parse_repo_ref("https://modelscope.cn/models/a/b") == ("modelscope", "a/b", None)
