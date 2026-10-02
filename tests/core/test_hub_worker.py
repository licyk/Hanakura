"""Exercise the hub worker without importing the download libraries or using the network."""

import sys
from types import ModuleType

import pytest

from hanakura.core.hubs.worker import download_modelscope


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({}, {}),
        ({"revision": None, "token": "", "endpoint": None}, {}),
        (
            {"revision": "dev", "token": "test-token", "endpoint": "https://mirror.example"},
            {"revision": "dev", "token": "test-token", "endpoint": "https://mirror.example"},
        ),
    ],
)
def test_modelscope_worker_optional_parameters(monkeypatch, capsys, options, expected):
    calls = []
    module = ModuleType("modelscope.hub.file_download")

    def model_file_download(repo_id, path, **kwargs):
        calls.append((repo_id, path, kwargs))

    module.model_file_download = model_file_download
    monkeypatch.setitem(sys.modules, module.__name__, module)
    download_modelscope({"repo_id": "owner/repo", "files": ["a.safetensors", "b.safetensors"], "local_dir": "/destination", **options})
    assert calls == [
        ("owner/repo", "a.safetensors", {"local_dir": "/destination", **expected}),
        ("owner/repo", "b.safetensors", {"local_dir": "/destination", **expected}),
    ]
    assert "test-token" not in capsys.readouterr().out
