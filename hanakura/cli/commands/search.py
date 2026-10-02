"""source list, search, info."""

from typing import Annotated

import typer

from hanakura.cli.output import console, human_size, open_services, print_json, print_table


def auth_status(json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False) -> None:
    """Show which Civitai credential is in use: a manual API token or a connected account."""
    with open_services() as s:
        status = s.auth.status()
        storage = s.auth.storage_description
    if json_output:
        print_json(status)
        return
    rows = [
        ("Selected method", status.method),
        ("Used for requests", f"{status.effective_method} ({status.credential_source})"),
        ("Manual token", "configured" if status.manual_token_configured else "not configured"),
        ("Environment override", "yes" if status.env_override else "no"),
        ("OAuth state", status.oauth_state),
        ("OAuth client id", "configured" if status.oauth_configured else "not configured"),
        ("Account", status.account.username or status.account.id if status.account else "-"),
        ("Token expires", status.expires_at.isoformat() if status.expires_at else "-"),
        ("Credentials kept in", storage),
    ]
    print_table("Civitai authentication", ["Field", "Value"], rows)
    if status.error:
        console.print(f"[yellow]{status.error}[/yellow]")
    if status.env_override:
        console.print("An environment variable supplies the token; remove it before OAuth can take effect.")


def auth_use(
    method: Annotated[str, typer.Argument(help="manual or oauth")],
) -> None:
    """Choose which Civitai credential to use. Nothing else changes this."""
    if method not in ("manual", "oauth"):
        raise typer.BadParameter("method must be 'manual' or 'oauth'")
    with open_services() as s:
        status = s.auth.set_method(method)  # type: ignore[arg-type]
    console.print(f"Civitai authentication: {status.method} (used: {status.effective_method})")


def auth_disconnect() -> None:
    """Revoke and forget the connected Civitai account. The manual token is kept."""
    with open_services() as s:
        status = s.auth.disconnect()
    console.print("Disconnected the Civitai account.")
    if status.error:
        console.print(f"[yellow]{status.error}[/yellow]")


def auth_connect() -> None:
    """Explain how to connect a Civitai account, which needs a browser."""
    with open_services() as s:
        status = s.auth.status()
        port = s.settings.settings.server.port
    if not status.oauth_configured:
        console.print("Civitai OAuth is not configured. Set it with:\n  hanakura config set auth.civitai.oauth_client_id <client id>")
    console.print(f"Start the server and connect from Settings in the web UI:\n  hanakura webui\n  then open http://127.0.0.1:{port}/#/settings")
    console.print("A manual API token works without any of this:\n  hanakura config set sources.civitai.token <token>")


def source_list(json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False) -> None:
    """List sources and hubs, with token status."""
    with open_services() as s:
        sources = s.sources.list_sources()
        hubs = s.hubs.list_hubs()
    if json_output:
        print_json({"sources": sources, "hubs": hubs})
        return
    rows = [(x.id, "source", "yes" if x.enabled else "no", "yes" if x.token_configured else "no", ", ".join(o.value for o in x.capabilities.kinds)) for x in sources]
    rows += [(h.id, "hub", "yes" if h.enabled else "no", "yes" if h.token_configured else "no", h.endpoint) for h in hubs]
    print_table("Sources", ["ID", "Type", "Enabled", "Token", "Kinds / endpoint"], rows)


def search(
    query: Annotated[str, typer.Argument(help="Search text")] = "",
    source: Annotated[str, typer.Option(help="Source id: civitai, openmodeldb, github, huggingface or modelscope")] = "civitai",
    kind: Annotated[str | None, typer.Option(help="Model kind filter, e.g. lora or checkpoint")] = None,
    base_model: Annotated[str | None, typer.Option(help="Base model filter, as the source names it (see 'source list')")] = None,
    sort: Annotated[str | None, typer.Option(help="Sort order, as the source names it")] = None,
    limit: Annotated[int, typer.Option(min=1, max=100, help="Number of results")] = 20,
    cursor: Annotated[str | None, typer.Option(help="Next-page cursor from a previous --json result")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Search a source or hub for models."""
    with open_services() as s:
        if source in s.hubs.adapters:
            from hanakura.core.hubs.models import HubQuery

            page = s.hubs.search(source, HubQuery(query=query, sort=sort, limit=limit, cursor=cursor))
            if json_output:
                print_json(page)
                return
            print_table(f"{source}: {query}", ["Repository", "Downloads", "Likes", "Task"], [(r.id, r.downloads, r.likes, r.task or "") for r in page.items])
        else:
            from hanakura.core.sources.models import SearchQuery

            spage = s.sources.search(source, SearchQuery(query=query, kind=kind, base_model=base_model, sort=sort, limit=limit, cursor=cursor))
            if json_output:
                print_json(spage)
                return
            print_table(
                f"{source}: {query}",
                ["ID", "Name", "Kind", "Base", "Creator", "Downloads"],
                [(m.id, m.name, m.kind or "", m.base_model_label or m.base_model or "", m.creator or "", m.stats.downloads or "") for m in spage.items],
            )
            if spage.next_cursor:
                console.print(f"More results: --cursor {spage.next_cursor}")


def info(
    source: Annotated[str, typer.Argument(help="Source or hub id")],
    model_id: Annotated[str, typer.Argument(help="Model id or repository id")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show a model's versions and files."""
    with open_services() as s:
        if source in s.hubs.adapters:
            repo = s.hubs.get_repo(source, model_id)
            if json_output:
                print_json(repo)
                return
            console.print(f"[bold]{repo.id}[/bold] @ {repo.revision}  {repo.page_url}")
            print_table("Files", ["Path", "Size", "SHA256"], [(f.path, human_size(f.size), (f.sha256 or "")[:16]) for f in repo.files])
            return
        detail = s.sources.get_model(source, model_id)
    if json_output:
        print_json(detail)
        return
    console.print(f"[bold]{detail.name}[/bold] ({detail.kind or '?'}) by {detail.creator or '?'}  {detail.page_url or ''}")
    for v in detail.versions:
        words = f"  trigger: {', '.join(v.trained_words)}" if v.trained_words else ""
        print_table(
            f"Version {v.id}: {v.name} [{v.base_model_label or '-'}]{words}",
            ["File id", "Name", "Size", "Primary", "Scan", "SHA256"],
            [(f.id, f.name, human_size(f.size), "yes" if f.primary else "", f.scan_result or "", (f.sha256 or "")[:16]) for f in v.files],
        )
