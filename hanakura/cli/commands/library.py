"""library root | list | info | identify | scan | import | move | rename | delete."""

from pathlib import Path
from typing import Annotated

import typer

from hanakura.cli.output import console, human_size, open_services, print_json, print_table

LAYOUT_HELP = "Layout preset: comfyui, sd-webui or custom"


def _locate(services, path: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    # Not resolved here: locate() matches the path as written first, so a path through a
    # symlinked folder inside a root is found there when symlinks are followed.
    return services.library.locate(Path(path).expanduser())


def root_list(json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False) -> None:
    """List model roots."""
    with open_services() as s:
        roots = s.library.list_roots()
    if json_output:
        print_json(roots)
        return
    print_table("Model roots", ["ID", "Name", "Layout", "Path", "Exists"], [(r.id, r.name, r.layout, r.path, "yes" if r.exists else "NO") for r in roots])


def root_add(
    path: Annotated[Path, typer.Argument(help="Folder to add", exists=True, file_okay=False, resolve_path=True)],
    layout: Annotated[str, typer.Option(help=LAYOUT_HELP)] = "custom",
    name: Annotated[str | None, typer.Option(help="Display name")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Add a model root."""
    from hanakura.core.library.models import RootCreate

    with open_services() as s:
        root = s.library.add_root(RootCreate.model_validate({"name": name, "path": str(path), "layout": layout}))
    if json_output:
        print_json(root)
    else:
        console.print(f"Added root [bold]{root.id}[/bold] ({root.layout}): {root.path}")


def root_remove(root_id: Annotated[str, typer.Argument(help="Root id")]) -> None:
    """Forget a model root. Files are not touched."""
    with open_services() as s:
        s.library.remove_root(root_id)
    console.print(f"Removed root {root_id}")


def _kind_label(entry) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    det = entry.detection
    if not entry.is_model:
        return "file", ""
    kind = det.kind if det else "?"
    base = (det.base_model if det else None) or (entry.sidecar.base_model if entry.sidecar else None) or ""
    if entry.mismatch:
        kind += " (!)"
    return kind, base


def library_list(
    path: Annotated[str | None, typer.Argument(help="Folder: a filesystem path, or a path inside --root")] = None,
    root: Annotated[str | None, typer.Option(help="Root id; PATH is then relative to it")] = None,
    recursive: Annotated[bool, typer.Option("--recursive", "-r", help="Include subfolders")] = False,
    kind: Annotated[str | None, typer.Option(help="Only this kind, e.g. lora, checkpoint, unknown")] = None,
    all_roots: Annotated[bool, typer.Option("--all-roots", help="The top level of every root side by side, as the web UI's All folders")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List models in a folder."""
    if all_roots:
        if path is not None or root is not None or recursive or kind is not None:
            from hanakura.core.errors import ValidationError

            raise ValidationError("--all-roots lists the top level of every root as folders; it takes no PATH, --root, --recursive or --kind")
        with open_services() as s:
            combined = s.library.list_combined()
        if json_output:
            print_json(combined)
            return
        rows = [(f"{f.label}/", "whole root" if f.is_root else "folder", f.folder_kind or "", f.root_name, f.path or "/") for f in combined.folders]
        print_table("All folders", ["Name", "Shows", "Kind", "Root", "Path in root"], rows)
        return
    with open_services() as s:
        if root is None:
            roots = s.library.list_roots()
            if path is None and len(roots) != 1:
                if json_output:
                    print_json(roots)
                else:
                    print_table("Model roots (pass a path or --root)", ["ID", "Name", "Path"], [(r.id, r.name, r.path) for r in roots])
                return
            root, rel = (roots[0].id, "") if path is None else _locate(s, path)
        else:
            rel = path or ""
        if recursive:
            models = list(s.library.walk_models(root, rel, kind=kind))
            folders = []
        else:
            listing = s.library.list_entries(root, rel, kind=kind)
            models, folders = listing.models, listing.folders
    if json_output:
        print_json({"root_id": root, "path": rel, "folders": folders, "models": models})
        return
    rows = [(f"{f.name}/", "folder", f.folder_kind or "", "", "") for f in folders]
    rows += [(m.path if recursive else m.name, *_kind_label(m), human_size(m.size), "yes" if m.preview else "") for m in models]
    print_table(f"{root}:{rel or '/'}", ["Name", "Kind", "Base", "Size", "Preview"], rows)


def library_info(
    path: Annotated[str, typer.Argument(help="Model file or diffusers folder")],
    hash_: Annotated[bool, typer.Option("--hash", help="Compute the SHA256 if not cached")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show detection result, hash and sidecar data for one model."""
    with open_services() as s:
        root_id, rel = _locate(s, path)
        info = s.library.model_info(root_id, rel, compute_hash=hash_)
    if json_output:
        print_json(info)
        return
    e = info.entry
    det = e.detection
    rows = [
        ("Path", f"{root_id}:{e.path}"),
        ("Size", human_size(e.size)),
        ("Kind", det.kind if det else "-"),
        ("Base model", (det.base_model if det else None) or "-"),
        ("Prediction", (det.prediction_type if det else None) or "-"),
        ("Confidence", f"{det.confidence:.2f}" if det else "-"),
        ("Rule", (det.rule_id if det else None) or "-"),
        ("Folder kind", e.folder_kind or "-"),
        ("Sidecar", f"{e.sidecar.source}: {e.sidecar.kind or '-'} / {e.sidecar.base_model or '-'}" if e.sidecar else "-"),
        ("Mismatch", "YES" if e.mismatch else "no"),
        ("SHA256", info.sha256 or "(not computed; use --hash)"),
        ("Preview", e.preview or "-"),
        ("Companions", ", ".join(e.companions) or "-"),
    ]
    for k, v in info.header_metadata.items():
        rows.append((k, str(v)[:200]))
    print_table(e.name, ["Field", "Value"], rows)


def library_identify(
    path: Annotated[str, typer.Argument(help="Model file")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Look the file's SHA256 up on the sources."""
    with open_services() as s:
        root_id, rel = _locate(s, path)
        with console.status("Hashing..."):
            info = s.library.model_info(root_id, rel, compute_hash=True)
        if not info.sha256:
            raise typer.BadParameter("Only files can be identified")
        with console.status("Looking up..."):
            results = s.sources.identify(info.sha256)
    if json_output:
        print_json({"sha256": info.sha256, "results": results})
        return
    if not results:
        console.print(f"No source knows {info.sha256}")
        return
    print_table(
        f"SHA256 {info.sha256}",
        ["Source", "Model", "Version", "Kind", "Base", "URL"],
        [(r.source, r.model.name, r.version_id or "", r.model.kind or "", r.model.base_model_label or "", r.model.page_url or "") for r in results],
    )


def library_scan(
    root: Annotated[str | None, typer.Option(help="Root id; all roots when omitted")] = None,
) -> None:
    """Detect every model in a root and fill the cache."""
    with open_services() as s:
        ids = [root] if root else [r.id for r in s.library.list_roots() if r.exists]
        for root_id in ids:
            with console.status(f"Scanning {root_id}..."):
                count = s.library.scan(root_id)
            console.print(f"{root_id}: {count} models")


def library_import(
    paths: Annotated[list[Path], typer.Argument(help="Files or folders to import", exists=True, resolve_path=True)],
    root: Annotated[str | None, typer.Option(help="Destination root id (default: the default root, or the first root)")] = None,
    to: Annotated[str | None, typer.Option(help="Folder inside the root (default: the layout's folder for the detected kind)")] = None,
    move: Annotated[bool, typer.Option("--move", help="Move instead of copy")] = False,
    rename: Annotated[bool, typer.Option("--rename", help="On a name clash, add a numeric suffix instead of failing")] = False,
) -> None:
    """Copy or move models into a root, with their previews and sidecars."""
    from hanakura.core.library.models import ImportRequest

    with open_services() as s:
        root_id = root or s.settings.settings.downloads.default_root or next((r.id for r in s.library.list_roots()), None)
        if root_id is None:
            raise typer.BadParameter("No model root exists; add one with 'library root add'")
        for p in paths:
            rel = to
            if rel is None:
                kind = s.detection.detect_path(p)[0].kind
                rel = s.library.default_dest(root_id, kind if kind != "unknown" else None)
            result = s.library.import_paths(ImportRequest(sources=[str(p)], root_id=root_id, rel_dir=rel, move=move, on_conflict="rename" if rename else "error"))
            for ref in result.paths:
                console.print(f"{'Moved' if move else 'Copied'} {p.name} -> {ref.root_id}:{ref.path}")


def library_move(
    src: Annotated[list[str], typer.Argument(help="Models or folders to move, then the destination folder last")],
    rename: Annotated[bool, typer.Option("--rename", help="On a name clash, add a numeric suffix instead of failing")] = False,
) -> None:
    """Move models (with companions) or folders to another folder, in any root."""
    from hanakura.core.library.models import MoveRequest, PathRef

    if len(src) < 2:
        raise typer.BadParameter("Give at least one source and a destination")
    *sources, dst = src
    with open_services() as s:
        dst_root, dst_rel = _locate(s, dst)
        items = [PathRef(root_id=r, path=p) for r, p in (_locate(s, x) for x in sources)]
        result = s.library.move(MoveRequest(items=items, dest_root_id=dst_root, dest_dir=dst_rel, on_conflict="rename" if rename else "error"))
    for ref in result.paths:
        console.print(f"Moved -> {ref.root_id}:{ref.path}")


def library_rename(
    path: Annotated[str, typer.Argument(help="Model or folder")],
    new_name: Annotated[str, typer.Argument(help="New name; the extension may be omitted")],
) -> None:
    """Rename a model and every companion file."""
    from hanakura.core.library.models import RenameRequest

    with open_services() as s:
        root_id, rel = _locate(s, path)
        result = s.library.rename(RenameRequest(root_id=root_id, path=rel, new_name=new_name))
    console.print(f"Renamed -> {result.paths[0].root_id}:{result.paths[0].path}")


def library_delete(
    paths: Annotated[list[str], typer.Argument(help="Models or folders to delete")],
    permanent: Annotated[bool, typer.Option("--permanent", help="Delete instead of moving to the trash")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation")] = False,
) -> None:
    """Delete models with their companions (to the trash by default)."""
    from hanakura.core.library.models import DeleteRequest, PathRef

    with open_services() as s:
        items = [PathRef(root_id=r, path=p) for r, p in (_locate(s, x) for x in paths)]
        to_trash = s.settings.settings.library.delete_to_trash and not permanent
        if not yes:
            what = "Move to the trash" if to_trash else "PERMANENTLY delete"
            typer.confirm(f"{what} {len(items)} item(s) and their companion files?", abort=True)
        result = s.library.delete(DeleteRequest(items=items, permanent=permanent))
    for ref in result.paths:
        console.print(f"Deleted {ref.root_id}:{ref.path}")
