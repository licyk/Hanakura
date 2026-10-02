"""download model | url | hf | modelscope, run in the foreground with a progress bar."""

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn, TransferSpeedColumn

from hanakura.cli.output import console, open_services, print_json

TO_HELP = "Destination folder (absolute, or relative to the current directory)"
ROOT_HELP = "Destination root id; the folder is chosen from the layout and the model's kind"
REL_HELP = "Folder inside --root"


def _run(services, create_request, json_output: bool) -> None:  # type: ignore[no-untyped-def]
    """Create a job, render its progress from the event bus, and wait for it."""
    from hanakura.core.events.models import DownloadProgressEvent

    manager = services.downloads
    manager.start()
    job = manager.create(create_request)
    progress = Progress(TextColumn("{task.description}"), BarColumn(), DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(), console=console, transient=json_output)
    task = progress.add_task(job.title[:60], total=job.total_bytes)

    def on_event(event) -> None:  # type: ignore[no-untyped-def]
        if isinstance(event, DownloadProgressEvent) and event.job_id == job.id:
            progress.update(task, completed=event.bytes_done, total=event.total_bytes)

    unsubscribe = services.events.subscribe(on_event)
    try:
        with progress:
            try:
                final = manager.wait(job.id)
            except KeyboardInterrupt:
                current = manager.get(job.id)
                if current.can_pause:
                    manager.pause(job.id)
                    console.print("Paused; the partial file is kept. Run the same command again to resume.")
                else:
                    manager.cancel(job.id)
                    console.print("Cancelled; hub downloads restart from zero.")
                manager.wait(job.id, timeout=15)
                raise typer.Exit(130) from None
    finally:
        unsubscribe()
    if json_output:
        print_json(final)
    if final.state == "completed":
        if not json_output:
            console.print(f"[green]Done:[/green] {final.final_path}")
        return
    console.print(f"[red]{final.state}:[/red] {final.error or ''}")
    raise typer.Exit(6 if final.state == "failed" else 1)


def _dest(to: Path | None) -> str | None:
    return str(to.expanduser().resolve()) if to else None


def download_model(
    source: Annotated[str, typer.Argument(help="Source id: civitai, openmodeldb or github")],
    model_id: Annotated[str, typer.Argument(help="Model id")],
    version: Annotated[str | None, typer.Option(help="Version id (default: the latest)")] = None,
    file: Annotated[str | None, typer.Option(help="File id or file name (default: the primary file)")] = None,
    root: Annotated[str | None, typer.Option(help=ROOT_HELP)] = None,
    rel: Annotated[str | None, typer.Option("--dir", help=REL_HELP)] = None,
    to: Annotated[Path | None, typer.Option(help=TO_HELP)] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace an existing file")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the finished job as JSON")] = False,
) -> None:
    """Download a model file from a searchable source."""
    from hanakura.core.downloads.models import DownloadCreate, SourceFileRef

    file_id, file_name = (file, None) if file and file.isdigit() else (None, file)
    with open_services() as s:
        req = DownloadCreate(
            source_file=SourceFileRef(source=source, model_id=model_id, version_id=version, file_id=file_id, file_name=file_name),
            root_id=root,
            rel_dir=rel,
            dest_dir=_dest(to),
            overwrite=overwrite,
        )
        _run(s, req, json_output)


def download_url(
    url: Annotated[str, typer.Argument(help="http or https URL")],
    to: Annotated[Path | None, typer.Option(help=TO_HELP)] = None,
    root: Annotated[str | None, typer.Option(help=ROOT_HELP)] = None,
    rel: Annotated[str | None, typer.Option("--dir", help=REL_HELP)] = None,
    name: Annotated[str | None, typer.Option(help="File name (default: from the server)")] = None,
    sha256: Annotated[str | None, typer.Option(help="Expected SHA256; the download fails on a mismatch")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace an existing file")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the finished job as JSON")] = False,
) -> None:
    """Download a file from a plain URL."""
    from hanakura.core.downloads.models import DownloadCreate

    # Without --to, --root or --dir the file lands in the current directory.
    dest = _dest(to) if to else (None if root or rel else str(Path.cwd()))
    with open_services() as s:
        req = DownloadCreate(url=url, dest_dir=dest, root_id=root, rel_dir=rel, file_name=name, expected_sha256=sha256, overwrite=overwrite)
        _run(s, req, json_output)


def _hub(
    hub: Literal["huggingface", "modelscope"],
    repo_id: str,
    revision: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
    to: Path | None,
    root: str | None,
    rel: str | None,
    overwrite: bool,
    json_output: bool,
) -> None:
    from hanakura.core.downloads.models import DownloadCreate, HubSelection
    from hanakura.core.hubs.registry import parse_repo_ref

    _, repo, parsed_rev = parse_repo_ref(repo_id)
    with open_services() as s:
        dest = _dest(to)
        if dest is None and root is None and rel is None:
            dest = str((Path.cwd() / repo.split("/")[-1]).resolve())
        req = DownloadCreate(
            hub=HubSelection(hub=hub, repo_id=repo, revision=revision or parsed_rev, include=include or [], exclude=exclude or []),
            dest_dir=dest,
            root_id=root,
            rel_dir=rel,
            overwrite=overwrite,
        )
        _run(s, req, json_output)


def download_hf(
    repo_id: Annotated[str, typer.Argument(help="Repository id or URL, e.g. stabilityai/sdxl-turbo")],
    revision: Annotated[str | None, typer.Option(help="Branch, tag or commit")] = None,
    include: Annotated[list[str] | None, typer.Option(help="Glob of files to include; repeatable")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Glob of files to exclude; repeatable")] = None,
    to: Annotated[Path | None, typer.Option(help=TO_HELP + " (default: ./<repo name>)")] = None,
    root: Annotated[str | None, typer.Option(help="Destination root id")] = None,
    rel: Annotated[str | None, typer.Option("--dir", help=REL_HELP)] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace existing files")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the finished job as JSON")] = False,
) -> None:
    """Download files from a Hugging Face repository (no pause; Ctrl+C cancels)."""
    _hub("huggingface", repo_id, revision, include, exclude, to, root, rel, overwrite, json_output)


def download_modelscope(
    repo_id: Annotated[str, typer.Argument(help="Repository id or URL")],
    revision: Annotated[str | None, typer.Option(help="Branch, tag or commit (default: master)")] = None,
    include: Annotated[list[str] | None, typer.Option(help="Glob of files to include; repeatable")] = None,
    exclude: Annotated[list[str] | None, typer.Option(help="Glob of files to exclude; repeatable")] = None,
    to: Annotated[Path | None, typer.Option(help=TO_HELP + " (default: ./<repo name>)")] = None,
    root: Annotated[str | None, typer.Option(help="Destination root id")] = None,
    rel: Annotated[str | None, typer.Option("--dir", help=REL_HELP)] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Replace existing files")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the finished job as JSON")] = False,
) -> None:
    """Download files from a ModelScope repository (no pause; Ctrl+C cancels)."""
    _hub("modelscope", repo_id, revision, include, exclude, to, root, rel, overwrite, json_output)
