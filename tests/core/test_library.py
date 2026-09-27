import json
import os
from pathlib import Path

import pytest

from sd_model_hub.core.errors import ConflictError, InvalidPathError, NotFoundError, ValidationError
from sd_model_hub.core.events.models import LibraryChangedEvent
from sd_model_hub.core.library.layouts import default_folder, folder_kind
from sd_model_hub.core.library.models import COMBINED_VIEW_ID, DeleteRequest, FolderCreate, ImportRequest, MoveRequest, PathRef, RenameRequest, RootCreate
from sd_model_hub.core.library.safety import resolve_in_root, validate_name
from tests.conftest import LORA_SD1, LORA_SDXL, write_safetensors

# -- path safety -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "CON", "nul.txt", "COM1.safetensors", "bad\x00", "x:y", "trailing.", " lead"])
def test_invalid_names(name):
    with pytest.raises(InvalidPathError):
        validate_name(name)


def test_resolve_rejects_traversal_and_absolute(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for bad in ("../x", "a/../../x", "/etc/passwd", "C:/Windows"):
        with pytest.raises(InvalidPathError):
            resolve_in_root(root, bad)
    assert resolve_in_root(root, "a/b") == root.resolve() / "a" / "b"


def test_resolve_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "link")
    with pytest.raises(InvalidPathError):
        resolve_in_root(root, "link/file")
    # With follow_symlinks the path is kept as written, so the client keeps navigating by it.
    assert resolve_in_root(root, "link/file", follow_symlinks=True) == root.resolve() / "link" / "file"
    # Traversal and absolute paths are still refused in either mode.
    for bad in ("../x", "/etc/passwd"):
        with pytest.raises(InvalidPathError):
            resolve_in_root(root, bad, follow_symlinks=True)


# -- layouts -----------------------------------------------------------------------


def test_layout_folder_kinds():
    assert folder_kind("comfyui", "loras/style/sub") == "lora"
    assert folder_kind("comfyui", "unet") == "diffusion_model"
    assert folder_kind("comfyui", "models/clip") == "text_encoder"
    assert folder_kind("sd-webui", "models/Lora") == "lora"
    assert folder_kind("sd-webui", "embeddings") == "embedding"
    assert folder_kind("custom", "loras") is None


def test_default_folder(tmp_path):
    (tmp_path / "models" / "Lora").mkdir(parents=True)
    assert default_folder("sd-webui", tmp_path, "lora") == "models/Lora"
    assert default_folder("sd-webui", tmp_path, "embedding") == "embeddings"
    assert default_folder("comfyui", tmp_path / "models", "lora") == "loras"


# -- roots and browsing --------------------------------------------------------------


def test_roots_crud(services, root_dir, root):
    assert [r.id for r in services.library.list_roots()] == [root.id]
    with pytest.raises(ConflictError):
        services.library.add_root(RootCreate(path=str(root_dir)))
    with pytest.raises(NotFoundError):
        services.library.add_root(RootCreate(path=str(root_dir / "missing")))
    services.library.remove_root(root.id)
    assert services.library.list_roots() == []
    assert root_dir.exists()


def test_listing_groups_companions_and_previews(services, root_dir, root):
    lora = root_dir / "loras" / "style"
    write_safetensors(lora / "a.safetensors", LORA_SDXL)
    write_safetensors(lora / "a.b.safetensors", LORA_SD1)
    (lora / "a.preview.png").write_bytes(b"png")
    (lora / "a.b.png").write_bytes(b"png")
    (lora / "a.civitai.info").write_text(json.dumps({"baseModel": "SD 1.5", "model": {"type": "LORA"}}))
    (lora / "a.safetensors.part").write_bytes(b"x")
    (lora / ".hidden").mkdir()
    (lora / "diffusers-model").mkdir()
    (lora / "diffusers-model" / "model_index.json").write_text("{}")
    listing = services.library.list_entries(root.id, "loras/style")
    by_name = {m.name: m for m in listing.models}
    assert set(by_name) == {"a.safetensors", "a.b.safetensors", "diffusers-model"}
    assert by_name["a.safetensors"].preview == "loras/style/a.preview.png"
    assert by_name["a.b.safetensors"].preview == "loras/style/a.b.png"
    assert "a.b.png" not in by_name["a.safetensors"].companions
    assert by_name["a.safetensors"].detection.base_model == "sdxl"
    assert by_name["a.safetensors"].folder_kind == "lora"
    # The civitai.info says SD 1.5 while the file is SDXL: the entry is flagged.
    assert by_name["a.safetensors"].mismatch is True
    assert by_name["a.b.safetensors"].mismatch is False
    assert listing.folders == []


def test_show_all_files_lists_plain_files_only_when_on(services, root_dir, root):
    """Off, a folder shows models; on, it reads like a file manager without doubling companions."""
    lora = root_dir / "loras" / "style"
    write_safetensors(lora / "a.safetensors", LORA_SDXL)
    (lora / "a.png").write_bytes(b"png")
    (lora / "notes.txt").write_text("hello")
    (lora / "README").write_text("no suffix")
    (lora / "unfinished.safetensors.part").write_bytes(b"x")

    assert [m.name for m in services.library.list_entries(root.id, "loras/style").models] == ["a.safetensors"]

    services.settings.update({"library": {"show_all_files": True}})
    listing = services.library.list_entries(root.id, "loras/style")
    # Models first, then the files no model claimed. The preview stays with its model.
    assert [m.name for m in listing.models] == ["a.safetensors", "notes.txt", "README"]
    plain = listing.models[1]
    assert plain.is_model is False and plain.detection is None and plain.sidecar is None and plain.mismatch is False
    assert listing.pending_detection == 0
    # A kind filter is about models, and a plain file is never one of them.
    assert [m.name for m in services.library.list_entries(root.id, "loras/style", kind="lora").models] == ["a.safetensors"]
    assert [m.name for m in services.library.walk_models(root.id, "loras")] == ["a.safetensors"]
    # A plain file can still be described, renamed and deleted like anything else in the root.
    info = services.library.model_info(root.id, "loras/style/notes.txt")
    assert info.entry.is_model is False and info.entry.companions == [] and info.description is None
    services.library.rename(RenameRequest(root_id=root.id, path="loras/style/notes.txt", new_name="notes2.txt"))
    assert (lora / "notes2.txt").exists() and (lora / "a.safetensors").exists()


def test_listing_cached_mode_schedules_scan(services, root_dir, root):
    write_safetensors(root_dir / "loras" / "x.safetensors", LORA_SD1)
    events = []
    services.events.subscribe(events.append)
    listing = services.library.list_entries(root.id, "loras", detect="cached")
    assert listing.pending_detection == 1 and listing.models[0].detection is None
    for _ in range(100):
        if any(isinstance(e, LibraryChangedEvent) for e in events):
            break
        import time

        time.sleep(0.02)
    assert services.library.list_entries(root.id, "loras", detect="cached").pending_detection == 0


def _link_outside(tmp_path: Path, root_dir: Path) -> Path:
    """A folder of models outside the root, linked to from inside it, as a WebUI install does."""
    outside = tmp_path / "elsewhere"
    write_safetensors(outside / "linked.safetensors", LORA_SDXL)
    os.symlink(outside, root_dir / "loras" / "linked")
    return outside


def _tree_folders(services, root_id: str, name: str) -> list[str]:
    """The names below one top-level folder of the tree, selected by name rather than by position."""
    node = next(c for c in services.library.tree(root_id).children if c.name == name)
    return [c.name for c in node.children]


def test_symlinked_folder_shown_by_default(services, root_dir, root, tmp_path):
    """Links are followed unless they are turned off: a linked folder is not silently missing."""
    _link_outside(tmp_path, root_dir)
    listing = services.library.list_entries(root.id, "loras")
    assert sorted(f.name for f in listing.folders) == ["linked", "style"]
    assert [m.path for m in services.library.list_entries(root.id, "loras/linked").models] == ["loras/linked/linked.safetensors"]
    assert "linked" in _tree_folders(services, root.id, "loras")


def test_symlinked_model_file_shown_by_default(services, root_dir, root, tmp_path):
    outside = tmp_path / "elsewhere"
    write_safetensors(outside / "linked.safetensors", LORA_SDXL)
    os.symlink(outside / "linked.safetensors", root_dir / "loras" / "linked.safetensors")

    listing = services.library.list_entries(root.id, "loras")
    assert [m.name for m in listing.models] == ["linked.safetensors"]
    assert services.library.model_info(root.id, "loras/linked.safetensors").entry.size > 0


def test_symlinks_turned_off_hide_what_leaves_the_root(services, root_dir, root, tmp_path):
    """Off, a link out of the root is hidden rather than listed and then refused on the way in."""
    outside = _link_outside(tmp_path, root_dir)
    os.symlink(outside / "linked.safetensors", root_dir / "loras" / "file-link.safetensors")
    services.settings.update({"library": {"follow_symlinks": False}})

    listing = services.library.list_entries(root.id, "loras")
    assert [f.name for f in listing.folders] == ["style"]
    assert [m.name for m in listing.models] == []
    with pytest.raises(InvalidPathError):
        services.library.list_entries(root.id, "loras/linked")
    with pytest.raises(InvalidPathError):
        services.library.model_info(root.id, "loras/file-link.safetensors")
    assert "linked" not in _tree_folders(services, root.id, "loras")


def test_follow_symlinks_setting_opens_linked_folders(services, root_dir, root, tmp_path):
    outside = _link_outside(tmp_path, root_dir)

    listing = services.library.list_entries(root.id, "loras")
    assert sorted(f.name for f in listing.folders) == ["linked", "style"]

    inside = services.library.list_entries(root.id, "loras/linked")
    entry = inside.models[0]
    # The path stays the one relative to the root, not the real location.
    assert entry.path == "loras/linked/linked.safetensors"
    assert entry.detection.base_model == "sdxl"
    assert services.library.model_info(root.id, entry.path).entry.name == "linked.safetensors"
    assert [m.path for m in services.library.walk_models(root.id, "loras")] == ["loras/linked/linked.safetensors"]

    # A file reached through the link is found under the root by the path as written.
    assert services.library.locate(root_dir / "loras" / "linked" / "linked.safetensors") == (root.id, "loras/linked/linked.safetensors")
    # Renaming acts on the real file.
    services.library.rename(RenameRequest(root_id=root.id, path="loras/linked/linked.safetensors", new_name="renamed"))
    assert (outside / "renamed.safetensors").exists()


def test_symlink_loop_is_walked_once(services, root_dir, root):
    os.symlink(root_dir / "loras", root_dir / "loras" / "style" / "loop")
    write_safetensors(root_dir / "loras" / "m.safetensors", LORA_SD1)
    models = list(services.library.walk_models(root.id, "loras"))
    assert [m.name for m in models] == ["m.safetensors"]
    assert services.library.tree(root.id) is not None


def test_kind_filter_and_walk(services, root_dir, root):
    write_safetensors(root_dir / "loras" / "style" / "l.safetensors", LORA_SD1)
    (root_dir / "checkpoints" / "old.ckpt").write_bytes(b"x")
    all_models = list(services.library.walk_models(root.id))
    assert {m.name for m in all_models} == {"l.safetensors", "old.ckpt"}
    assert [m.name for m in services.library.walk_models(root.id, kind="lora")] == ["l.safetensors"]
    # A pickle is unknown to detection, so the folder decides.
    assert [m.name for m in services.library.walk_models(root.id, kind="checkpoint")] == ["old.ckpt"]


def test_model_info_with_sidecars_and_hash(services, root_dir, root):
    path = write_safetensors(root_dir / "loras" / "m.safetensors", LORA_SDXL)
    (root_dir / "loras" / "m.json").write_text(json.dumps({"description": "d", "sd version": "SDXL", "activation text": "trig", "junk": 1}))
    (root_dir / "loras" / "m.txt").write_text("hello")
    info = services.library.model_info(root.id, "loras/m.safetensors", compute_hash=True)
    assert info.webui == {"description": "d", "sd version": "SDXL", "activation text": "trig"}
    assert info.description == "hello"
    import hashlib

    assert info.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


# -- operations ------------------------------------------------------------------------


def test_rename_carries_companions(services, root_dir, root):
    lora = root_dir / "loras"
    write_safetensors(lora / "old.safetensors", LORA_SD1)
    (lora / "old.preview.png").write_bytes(b"p")
    (lora / "old.json").write_text("{}")
    result = services.library.rename(RenameRequest(root_id=root.id, path="loras/old.safetensors", new_name="new.safetensors"))
    assert result.paths[0].path == "loras/new.safetensors"
    assert sorted(p.name for p in lora.iterdir() if p.is_file()) == ["new.json", "new.preview.png", "new.safetensors"]


def test_rename_conflict(services, root_dir, root):
    write_safetensors(root_dir / "loras" / "a.safetensors", LORA_SD1)
    (root_dir / "loras" / "b.png").write_bytes(b"p")
    write_safetensors(root_dir / "loras" / "a2.safetensors", LORA_SD1)
    (root_dir / "loras" / "a.png").write_bytes(b"p")
    with pytest.raises(ConflictError):
        services.library.rename(RenameRequest(root_id=root.id, path="loras/a.safetensors", new_name="b"))
    assert (root_dir / "loras" / "a.safetensors").exists()
    with pytest.raises(InvalidPathError):
        services.library.rename(RenameRequest(root_id=root.id, path="loras/a.safetensors", new_name="../x"))


def test_move_between_roots_with_rename_on_conflict(services, root_dir, root, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    other_root = services.library.add_root(RootCreate(path=str(other)))
    write_safetensors(root_dir / "loras" / "m.safetensors", LORA_SD1)
    (root_dir / "loras" / "m.png").write_bytes(b"p")
    write_safetensors(other / "m.safetensors", LORA_SD1)
    with pytest.raises(ConflictError):
        services.library.move(MoveRequest(items=[PathRef(root_id=root.id, path="loras/m.safetensors")], dest_root_id=other_root.id))
    result = services.library.move(MoveRequest(items=[PathRef(root_id=root.id, path="loras/m.safetensors")], dest_root_id=other_root.id, on_conflict="rename"))
    assert result.paths[0].path == "m_1.safetensors"
    assert (other / "m_1.png").exists() and not (root_dir / "loras" / "m.png").exists()


def test_move_folder_into_itself_refused(services, root_dir, root):
    with pytest.raises(InvalidPathError):
        services.library.move(MoveRequest(items=[PathRef(root_id=root.id, path="loras")], dest_root_id=root.id, dest_dir="loras/style"))


def test_delete_permanent_and_to_trash_fallback(services, root_dir, root, monkeypatch):
    write_safetensors(root_dir / "loras" / "gone.safetensors", LORA_SD1)
    (root_dir / "loras" / "gone.png").write_bytes(b"p")
    services.library.delete(DeleteRequest(items=[PathRef(root_id=root.id, path="loras/gone.safetensors")], permanent=True))
    assert list((root_dir / "loras").glob("gone*")) == []

    write_safetensors(root_dir / "loras" / "t.safetensors", LORA_SD1)
    import send2trash

    def fail(_path):
        raise OSError("no trash here")

    monkeypatch.setattr(send2trash, "send2trash", fail)
    result = services.library.delete(DeleteRequest(items=[PathRef(root_id=root.id, path="loras/t.safetensors")]))
    trash_dir = Path(result.trashed_to[0])
    assert (trash_dir / "t.safetensors").exists()
    assert trash_dir.is_relative_to(services.settings.data_dir)


def test_cannot_delete_root(services, root):
    with pytest.raises(InvalidPathError):
        services.library.delete(DeleteRequest(items=[PathRef(root_id=root.id, path="")], permanent=True))


def test_import_copy_with_companions(services, root_dir, root, tmp_path):
    src = tmp_path / "incoming"
    write_safetensors(src / "new.safetensors", LORA_SDXL)
    (src / "new.preview.webp").write_bytes(b"w")
    result = services.library.import_paths(ImportRequest(sources=[str(src / "new.safetensors")], root_id=root.id, rel_dir="loras"))
    assert result.paths[0].path == "loras/new.safetensors"
    assert (root_dir / "loras" / "new.preview.webp").exists()
    assert (src / "new.safetensors").exists()
    with pytest.raises(ConflictError):
        services.library.import_paths(ImportRequest(sources=[str(src / "new.safetensors")], root_id=root.id, rel_dir="loras"))


def test_create_folder(services, root_dir, root):
    ref = services.library.create_folder(FolderCreate(root_id=root.id, path="loras", name="new"))
    assert ref.path == "loras/new" and (root_dir / "loras" / "new").is_dir()
    with pytest.raises(ConflictError):
        services.library.create_folder(FolderCreate(root_id=root.id, path="loras", name="new"))


def test_upload_writer(services, root_dir, root):
    writer = services.library.open_upload(root.id, "loras", "sub/up.bin", total=6)
    writer.write(b"abc")
    writer.write(b"def")
    ref = writer.commit()
    assert ref.path == "loras/sub/up.bin" and (root_dir / "loras" / "sub" / "up.bin").read_bytes() == b"abcdef"
    with pytest.raises(ConflictError):
        services.library.open_upload(root.id, "loras", "sub/up.bin")
    aborted = services.library.open_upload(root.id, "loras", "x.bin")
    aborted.write(b"1")
    aborted.abort()
    assert not (root_dir / "loras" / "x.bin.part").exists() and not (root_dir / "loras" / "x.bin").exists()


# -- the combined view -------------------------------------------------------------


def _add(services, path: Path, name: str, kind: str | None = None, layout: str = "comfyui"):
    path.mkdir(parents=True, exist_ok=True)
    return services.library.add_root(RootCreate(name=name, path=str(path), layout=layout, kind=kind))


def test_combined_view_is_off_by_default(services):
    assert services.settings.settings.library.combined_view is False


def _shown(combined) -> list[tuple[str, str, str, bool]]:
    return [(f.label, f.root_id, f.path, f.is_root) for f in combined.folders]


def test_combined_spreads_roots_that_hold_only_folders(services, root_dir, root, tmp_path):
    write_safetensors(root_dir / "loras" / "style" / "deep.safetensors", LORA_SD1)
    forge = _add(services, tmp_path / "forge", "forge")
    (tmp_path / "forge" / "embeddings").mkdir()

    combined = services.library.list_combined()
    assert _shown(combined) == [
        ("checkpoints", root.id, "checkpoints", False),
        ("embeddings", forge.id, "embeddings", False),
        ("loras", root.id, "loras", False),
        ("vae", root.id, "vae", False),
    ]
    assert combined.folders[2].folder_kind == "lora"
    assert combined.missing_roots == []


def test_a_root_with_files_stays_one_folder_named_after_its_directory(services, root_dir, root, tmp_path):
    """Its files, and its folders, stay inside it rather than scattering among every other root's."""
    lora = _add(services, tmp_path / "webui" / "models" / "Lora", "loras (2)", kind="lora", layout="custom")
    write_safetensors(tmp_path / "webui" / "models" / "Lora" / "loose.safetensors", LORA_SD1)
    (tmp_path / "webui" / "models" / "Lora" / "sdxl").mkdir()

    combined = services.library.list_combined()
    assert ("Lora", lora.id, "", True) in _shown(combined)
    assert "sdxl" not in [f.name for f in combined.folders]
    entry = next(f for f in combined.folders if f.is_root)
    assert entry.root_name == "loras (2)" and entry.folder_kind == "lora"
    # The folder-only root beside it is still spread out.
    assert ("loras", root.id, "loras", False) in _shown(combined)


def test_what_counts_as_a_file_follows_what_the_listing_shows(services, root_dir, root):
    (root_dir / "notes.txt").write_text("x")
    # A plain file is not listed while show_all_files is off, so there is nothing to scatter.
    assert not any(f.is_root for f in services.library.list_combined().folders)
    services.settings.update({"library": {"show_all_files": True}})
    assert _shown(services.library.list_combined()) == [("models", root.id, "", True)]
    services.settings.update({"library": {"show_all_files": False}})
    # A diffusers folder is shown as a model, so it keeps its root together too.
    (root_dir / "pipe").mkdir()
    (root_dir / "pipe" / "model_index.json").write_text("{}")
    assert _shown(services.library.list_combined()) == [("models", root.id, "", True)]


def test_combined_tells_equal_names_apart_by_root(services, root_dir, root, tmp_path):
    second = _add(services, tmp_path / "b" / "models", "comfy")
    (tmp_path / "b" / "models" / "LORAS").mkdir()
    # Two whole roots named after the same directory.
    third = _add(services, tmp_path / "c" / "vae", "vae one")
    fourth = _add(services, tmp_path / "d" / "vae", "vae two")
    write_safetensors(tmp_path / "c" / "vae" / "a.safetensors", LORA_SD1)
    write_safetensors(tmp_path / "d" / "vae" / "b.safetensors", LORA_SD1)

    labels = {(f.root_id, f.name): f.label for f in services.library.list_combined().folders}
    # Case does not tell names apart for a reader, and two roots with one name are numbered.
    assert labels[(root.id, "loras")] == "loras (comfy)"
    assert labels[(second.id, "LORAS")] == "LORAS (comfy 2)"
    assert labels[(root.id, "vae")] == "vae (comfy)"
    assert labels[(third.id, "vae")] == "vae (vae one)"
    assert labels[(fourth.id, "vae")] == "vae (vae two)"
    assert labels[(root.id, "checkpoints")] == "checkpoints"


def test_combined_leaves_out_nested_and_missing_roots(services, root_dir, root, tmp_path):
    """A root inside another is already reached through it; a missing one is reported, not fatal."""
    nested = _add(services, root_dir / "loras", "LoRA", kind="lora")
    write_safetensors(root_dir / "loras" / "x.safetensors", LORA_SD1)
    gone = _add(services, tmp_path / "gone", "gone")
    (tmp_path / "gone").rmdir()
    combined = services.library.list_combined()
    assert {f.root_id for f in combined.folders} == {root.id}
    assert nested.id not in {f.root_id for f in combined.folders}
    assert combined.missing_roots == [gone.id]


def test_combined_leads_with_roots_without_a_kind(services, tmp_path):
    _add(services, tmp_path / "loras", "LoRA", kind="lora", layout="custom")
    _add(services, tmp_path / "all", "All", layout="custom")
    write_safetensors(tmp_path / "loras" / "x.safetensors", LORA_SD1)
    write_safetensors(tmp_path / "all" / "x.safetensors", LORA_SD1)
    # Sorted by label on screen; both are whole roots named after their directories.
    assert [(f.label, f.is_root) for f in services.library.list_combined().folders] == [("all", True), ("loras", True)]


def test_combined_lists_a_linked_directory_once(services, root_dir, root, tmp_path):
    other = _add(services, tmp_path / "elsewhere", "elsewhere")
    (tmp_path / "elsewhere" / "sub").mkdir()
    # A link inside one root to another root, and a second link to a folder already listed.
    os.symlink(tmp_path / "elsewhere", root_dir / "to-root")
    os.symlink(tmp_path / "elsewhere" / "sub", root_dir / "to-sub")
    combined = services.library.list_combined()
    assert [(f.root_id, f.name) for f in combined.folders if f.name in ("sub", "to-sub", "to-root")] == [(other.id, "sub")]


def test_a_whole_root_is_kept_when_another_root_links_to_it(services, root_dir, root, tmp_path):
    other = _add(services, tmp_path / "elsewhere", "elsewhere")
    write_safetensors(tmp_path / "elsewhere" / "m.safetensors", LORA_SD1)
    os.symlink(tmp_path / "elsewhere", root_dir / "to-root")
    shown = _shown(services.library.list_combined())
    assert ("elsewhere", other.id, "", True) in shown
    assert "to-root" not in [label for label, *_ in shown]


def test_combined_view_id_cannot_be_a_root(services, root_dir):
    with pytest.raises(ValidationError):
        services.library.add_root(RootCreate(path=str(root_dir)), root_id=COMBINED_VIEW_ID)


# -- exporting a file ------------------------------------------------------------


def test_export_file_serves_only_finished_files_inside_the_root(services, root_dir, root, tmp_path):
    path = write_safetensors(root_dir / "loras" / "m.safetensors", LORA_SD1)
    (root_dir / "loras" / "busy.safetensors.part").write_bytes(b"x")
    assert services.library.export_file(root.id, "loras/m.safetensors") == path.resolve()
    with pytest.raises(InvalidPathError):
        services.library.export_file(root.id, "loras")
    with pytest.raises(InvalidPathError):
        services.library.export_file(root.id, "")
    with pytest.raises(NotFoundError):
        services.library.export_file(root.id, "loras/busy.safetensors.part")
    with pytest.raises(NotFoundError):
        services.library.export_file(root.id, "loras/none.safetensors")
    with pytest.raises(InvalidPathError):
        services.library.export_file(root.id, "../outside.txt")

    (tmp_path / "secret.txt").write_text("s")
    os.symlink(tmp_path / "secret.txt", root_dir / "link.txt")
    services.settings.update({"library": {"follow_symlinks": False}})
    with pytest.raises(InvalidPathError):
        services.library.export_file(root.id, "link.txt")
