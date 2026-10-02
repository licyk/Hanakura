"""webui: bind the port, build the services, and serve the API and the web UI."""

import logging
import os
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from hanakura.logger import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


def webui(
    host: Annotated[str | None, typer.Option(help="Address to bind (default from settings: 127.0.0.1)")] = None,
    port: Annotated[int | None, typer.Option(min=1, max=65535, help="First port to try (default from settings)")] = None,
    strict_port: Annotated[bool | None, typer.Option("--strict-port/--no-strict-port", help="Fail instead of trying the next port")] = None,
    open_browser: Annotated[bool | None, typer.Option("--open/--no-open", help="Open the web UI in a browser")] = None,
    data_dir: Annotated[Path | None, typer.Option(help="Data directory (settings, database, caches)", file_okay=False, resolve_path=True)] = None,
    api_prefix: Annotated[str | None, typer.Option(help="Serve the API, the socket and the web UI under this path, e.g. /hanakura")] = None,
) -> None:
    """Start the server and open the web UI."""
    import uvicorn

    from hanakura.api.app import create_app, normalize_prefix
    from hanakura.core.context import build_services
    from hanakura.core.net.ports import PortUnavailableError, bind_first_free_port, is_loopback
    from hanakura.core.net.runtime_file import remove_runtime_file, write_runtime_file

    if data_dir is not None:
        os.environ["HANAKURA_DATA_DIR"] = str(data_dir)
    services = build_services(data_dir=data_dir)
    server_settings = services.settings.settings.server
    host = host or server_settings.host
    port = port or server_settings.port
    strict = server_settings.strict_port if strict_port is None else strict_port
    should_open = server_settings.open_browser if open_browser is None else open_browser

    if not is_loopback(host):
        logger.warning("Binding to %s makes the server reachable from other machines.", host)
        if not server_settings.access_token:
            services.close()
            logger.error("Set server.access_token first (hanakura config set server.access_token <secret>).")
            raise typer.Exit(4)

    try:
        sock = bind_first_free_port(host, port, strict=strict)
    except PortUnavailableError as e:
        services.close()
        logger.error("%s", e)
        raise typer.Exit(3) from None
    actual_port = sock.getsockname()[1]
    if actual_port != port:
        logger.warning("Port %s is unavailable. Using port %s.", port, actual_port)
    url_host = f"[{host}]" if ":" in host else host
    url_host = "127.0.0.1" if host in ("0.0.0.0", "::") else url_host
    url = f"http://{url_host}:{actual_port}{normalize_prefix(api_prefix)}"

    app = create_app(services, bound_host=host, bound_port=actual_port, api_prefix=api_prefix)
    config = uvicorn.Config(app=app, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    write_runtime_file(services.settings.data_dir, host, actual_port, url)
    print(f"SERVER_READY url={url}", flush=True)
    logger.info("Hanakura running on %s", url)
    if should_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.run(sockets=[sock])
    finally:
        remove_runtime_file(services.settings.data_dir)
        services.close()
        sock.close()
