"""source list, search, info."""

from typing import TYPE_CHECKING, Annotated

import typer

from hanakura.cli.output import console, err_console, human_size, open_services, print_json, print_table

if TYPE_CHECKING:
    from hanakura.core.auth.models import CivitaiAuthStatus


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
        ("OAuth client", _client_label(status)),
        ("Sign-in (web UI)", ", ".join(status.flows) or "-"),
        ("Account", status.account.username or status.account.id if status.account else "-"),
        ("Token expires", status.expires_at.isoformat() if status.expires_at else "-"),
        ("Credentials kept in", storage),
    ]
    print_table("Civitai authentication", ["Field", "Value"], rows)
    if status.error:
        console.print(f"[yellow]{status.error}[/yellow]")
    if status.env_override:
        console.print("An environment variable supplies the token; remove it before OAuth can take effect.")


def _client_label(status: "CivitaiAuthStatus") -> str:
    if not status.oauth_enabled:
        return "turned off"
    if status.client_source == "custom":
        return "your own (auth.civitai.oauth_client_id)"
    if status.client_source == "bundled":
        return f"bundled ({status.client_name})"
    return "none: set auth.civitai.oauth_client_id"


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


FLOWS = ("auto", "browser", "device")
# The command line has no address Civitai could send a browser back to.
NO_CALLBACK = "The command line cannot receive Civitai's callback: sign in from Settings in the web UI (hanakura webui), or use --flow device."


def auth_connect(
    flow: Annotated[str, typer.Option(help="auto, browser or device. The command line signs in with a device code")] = "auto",
    no_open: Annotated[bool, typer.Option("--no-open", help="Print the address instead of opening a browser")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print the sign-in's outcome as JSON")] = False,
) -> None:
    """Connect a Civitai account: confirm a short code on Civitai's website, from any device."""
    import webbrowser

    from hanakura.core.errors import AuthRequiredError, ConflictError, SourceError, ValidationError

    if flow not in FLOWS:
        raise typer.BadParameter("flow must be auto, browser or device")
    if flow == "browser":
        raise ValidationError(NO_CALLBACK, {"reason": "callback_unsupported"})
    # Prompts go to stderr with --json, so stdout carries only the result.
    out = err_console if json_output else console
    with open_services() as s:
        chosen = s.auth.choose_flow(flow, browser_available=False, browser_reason=NO_CALLBACK)  # type: ignore[arg-type]
        start, secret = s.auth.start(flow=chosen)
        address = start.authorization_url
        out.print(f"Open {address}")
        if start.user_code:
            out.print(f"and confirm the code [bold]{start.user_code}[/bold] (valid until {start.expires_at.astimezone():%H:%M}).")
        if not no_open:
            try:
                webbrowser.open(address)
            except Exception as e:  # noqa: BLE001 - no browser here: the address above is enough
                out.print(f"Could not open a browser ({type(e).__name__}).")
        out.print("Waiting for the sign-in; Ctrl+C cancels it.")
        try:
            result = s.auth.wait_session(start.session_id, secret)
        except KeyboardInterrupt:
            # Cancelled before anything it would have connected is stored.
            s.auth.cancel_session(start.session_id, secret)
            raise
        status = s.auth.status(browser_available=False)
    if json_output:
        print_json({"session": result, "status": status})
    elif result.status == "connected":
        name = status.account.username or status.account.id if status.account else None
        console.print(f"Connected the Civitai account{f' {name}' if name else ''}; requests now use it.")
        if status.env_override:
            console.print("An environment variable supplies an API token, which still takes precedence.")
    if result.status == "connected":
        return
    message = result.error or "The sign-in did not finish."
    detail = {"reason": result.error_code or "failed"}
    if result.status in ("denied", "expired"):
        raise AuthRequiredError(message, detail)
    if result.status == "cancelled":
        raise ConflictError(message, detail)
    if result.error_code in ("insufficient_scope", "client_unavailable"):
        raise AuthRequiredError(message, detail)
    raise SourceError(message, detail)


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
