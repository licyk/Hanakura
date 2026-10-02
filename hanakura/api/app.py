"""``create_app(services)``: the FastAPI app with routers, the socket, and the web UI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hanakura.api.errors import install_error_handlers
from hanakura.api.openapi import HanakuraAPI
from hanakura.api.paths import validate_public_base_url
from hanakura.api.routers import app_info, auth, downloads, hubs, library, settings, sources
from hanakura.api.security import SecurityMiddleware
from hanakura.api.sockets import SocketBridge
from hanakura.api.static import SPAStaticFiles, web_dist_dir
from hanakura.core.context import Services
from hanakura.version import VERSION

logger = logging.getLogger(__name__)


def normalize_prefix(prefix: str | None) -> str:
    """``/hub/`` and ``hub`` both become ``/hub``; nothing becomes ``""``."""
    cleaned = (prefix or "").strip().strip("/")
    return f"/{cleaned}" if cleaned else ""


def create_app(
    services: Services,
    bound_host: str | None = None,
    bound_port: int | None = None,
    extra_hosts: set[str] | None = None,
    start_downloads: bool = True,
    serve_ui: bool = True,
    api_prefix: str | None = None,
    public_base_url: str | None = None,
) -> FastAPI:
    """Build the application.

    ``api_prefix`` moves everything this package serves — the API, the socket and the web UI —
    under one path, so a host application can mount it beside its own routes without a clash.
    The web UI needs no change: it derives its base URL from the URL its own script was loaded
    from, which already carries the prefix.

    When mounted, the host must enter this app's ``router.lifespan_context`` on its serving
    event loop and close the services afterwards. ``public_base_url`` supplies a trusted
    browser-facing URL for OAuth behind a proxy; it does not add a second route prefix.
    """
    prefix = normalize_prefix(api_prefix)
    public_base_url = validate_public_base_url(public_base_url)
    socket_bridge = SocketBridge(services.events, lambda: services.settings.settings.server.access_token)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await socket_bridge.start()
        if start_downloads:
            services.downloads.start()
        try:
            yield
        finally:
            services.downloads.shutdown()
            await socket_bridge.stop()

    app = HanakuraAPI(title="Hanakura", version=VERSION, lifespan=lifespan, docs_url=f"{prefix}/docs", redoc_url=None, openapi_url=f"{prefix}/openapi.json")
    app.state.services = services
    app.state.bound_port = bound_port
    app.state.api_prefix = prefix
    app.state.public_base_url = public_base_url
    install_error_handlers(app)

    for module in (app_info, settings, auth, sources, hubs, downloads, library):
        app.include_router(module.router, prefix=f"{prefix}/api")
    app.mount(f"{prefix}/ws", socket_bridge.asgi_app(prefix), name="socket")

    origins = services.settings.settings.server.allowed_origins
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
    app.add_middleware(
        SecurityMiddleware,
        bound_host=lambda: bound_host or services.settings.settings.server.host,
        allowed_origins=lambda: services.settings.settings.server.allowed_origins,
        access_token=lambda: services.settings.settings.server.access_token,
        extra_hosts=extra_hosts,
        prefix=prefix,
    )

    # Registered last, so it only receives paths nothing else matched.
    dist = web_dist_dir()
    if serve_ui and (dist / "index.html").is_file():
        app.mount(f"{prefix}/", SPAStaticFiles(directory=dist, html=True), name="ui")
    elif serve_ui:
        logger.warning("No web UI build found at %s; serving the API only", dist)
    return app
