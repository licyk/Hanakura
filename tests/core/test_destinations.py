"""Host-provided roots and download defaults share one resolution path."""

import os
import subprocess
import sys

import pytest

from hanakura import HanakuraServer, ModelRoot
from hanakura.core.downloads.models import DownloadCreate
from hanakura.core.errors import InvalidPathError, NotFoundError
from hanakura.core.library.models import RootCreate, RootUpdate
from tests.conftest import LORA_SD1, write_safetensors


def test_root_hint_is_inherited_but_does_not_override_detection(services, root_dir):
    root = services.library.add_root(RootCreate(path=str(root_dir), kind="checkpoint"))
    write_safetensors(root_dir / "loras" / "a.safetensors", LORA_SD1)
    listing = services.library.list_entries(root.id, "loras")
    entry = listing.models[0]
    assert listing.folder_kind == entry.folder_kind == "checkpoint"
    assert entry.detection.kind == "lora" and entry.mismatch
    assert services.library.tree(root.id).children[0].folder_kind == "checkpoint"
    services.library.update_root(root.id, RootUpdate(name="renamed"))
    assert services.library.get_root(root.id).kind == "checkpoint"
    services.library.update_root(root.id, RootUpdate(kind=None))
    assert services.library.get_root(root.id).kind is None


def test_layout_mapping_takes_precedence_over_root_hint(services, root_dir):
    root = services.library.add_root(RootCreate(path=str(root_dir), layout="comfyui", kind="checkpoint"))
    write_safetensors(root_dir / "loras" / "a.safetensors", LORA_SD1)
    entry = services.library.list_entries(root.id, "loras").models[0]
    assert entry.folder_kind == "lora" and not entry.mismatch


def test_kind_destination_and_explicit_overrides(services, root, tmp_path):
    other = tmp_path / "external-loras"
    other.mkdir()
    loras = services.library.add_root(RootCreate(path=str(other), kind="lora"))
    services.settings.update(
        {
            "downloads": {
                "default_root": root.id,
                "kind_destinations": {"lora": {"root_id": loras.id, "rel_dir": "styles"}},
            }
        }
    )
    suggested = services.library.suggest_destination("lora")
    assert (suggested.root_id, suggested.rel_dir) == (loras.id, "styles")
    assert not (other / "styles").exists()
    resolved = services.downloads._resolve_dest(DownloadCreate(url="https://example.com/lora.safetensors"), "lora")
    assert resolved == (loras.id, "styles", other / "styles")
    assert services.library.suggest_destination("lora", root.id).rel_dir == "loras"
    explicit = services.downloads._resolve_dest(DownloadCreate(url="https://example.com/a", root_id=loras.id, rel_dir=""), "lora")
    assert explicit == (loras.id, "", other)
    absolute = services.downloads._resolve_dest(DownloadCreate(url="https://example.com/a", dest_dir=str(tmp_path / "outside")), "lora")
    assert absolute == (None, "", tmp_path / "outside")


def test_destination_fallbacks_and_empty_mapping(services, root, tmp_path):
    other = tmp_path / "lora-only"
    other.mkdir()
    loras = services.library.add_root(RootCreate(path=str(other), kind="lora"))
    assert services.library.suggest_destination("lora").root_id == loras.id
    assert services.library.suggest_destination("checkpoint").root_id == root.id
    services.settings.update({"downloads": {"default_root": root.id}})
    assert services.library.suggest_destination("lora").root_id == root.id
    services.settings.update(
        {
            "downloads": {
                "kind_folders": {"lora": "legacy"},
                "kind_destinations": {"lora": {"root_id": loras.id, "rel_dir": ""}},
            }
        }
    )
    assert services.library.suggest_destination("lora").rel_dir == ""
    assert services.library.suggest_destination("lora", root.id).rel_dir == "legacy"
    services.settings.update({"downloads": {"kind_destinations": {"lora": None}}})
    assert services.library.suggest_destination("lora").root_id == root.id
    services.settings.reload()
    assert services.library.suggest_destination("lora").root_id == root.id


@pytest.mark.parametrize("rel_dir", ["../escape", "/absolute", "C:/absolute"])
def test_configured_destination_is_validated(services, root, rel_dir):
    services.settings.update({"downloads": {"kind_destinations": {"lora": {"root_id": root.id, "rel_dir": rel_dir}}}})
    with pytest.raises(InvalidPathError):
        services.library.suggest_destination("lora")
    assert services.library.suggest_destination("lora", root.id, rel_dir="manual").rel_dir == "manual"


def test_missing_destination_root_is_not_silently_replaced(services, root):
    services.settings.update({"downloads": {"kind_destinations": {"lora": {"root_id": "missing"}}}})
    with pytest.raises(NotFoundError):
        services.library.suggest_destination("lora")
    assert services.library.suggest_destination("lora", root.id).root_id == root.id


def test_destination_follows_a_linked_folder_and_refuses_it_when_links_are_off(services, root, root_dir, tmp_path):
    """A linked folder is a destination like any other: browsing it and downloading into it agree."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (root_dir / "escape").symlink_to(outside, target_is_directory=True)
    services.settings.update({"downloads": {"kind_destinations": {"lora": {"root_id": root.id, "rel_dir": "escape"}}}})
    assert services.library.suggest_destination("lora").rel_dir == "escape"

    services.settings.update({"library": {"follow_symlinks": False}})
    with pytest.raises(InvalidPathError):
        services.library.suggest_destination("lora")


def test_seeded_host_root_keeps_id_and_hint(tmp_path, root_dir):
    hub = HanakuraServer(data_dir=tmp_path / "hub", model_roots=[ModelRoot(root_dir, id="loras", kind="lora")])
    services = hub._build()
    try:
        root = services.library.list_roots()[0]
        assert (root.id, root.kind) == ("loras", "lora")
    finally:
        services.close()


def test_host_root_id_survives_python_hash_seed(root_dir):
    code = "from hanakura import ModelRoot; import sys; print(ModelRoot(sys.argv[1]).to_settings()['id'])"
    ids = [subprocess.check_output([sys.executable, "-c", code, str(root_dir)], env={**os.environ, "PYTHONHASHSEED": seed}, text=True).strip() for seed in ("1", "2")]
    assert ids[0] == ids[1] == ModelRoot(root_dir).to_settings()["id"]


def test_explicit_empty_locked_roots_override_saved_roots(tmp_path, root_dir):
    data = tmp_path / "hub"
    hub = HanakuraServer(data_dir=data, model_roots=[root_dir])
    hub._build().close()
    empty = HanakuraServer(data_dir=data, model_roots=[], lock_model_roots=True)
    services = empty._build()
    try:
        assert services.library.list_roots() == []
    finally:
        services.close()
