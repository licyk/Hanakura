"""Run Hanakura inside another application.

    from hanakura import HanakuraServer, ModelRoot

    hub = HanakuraServer(
        data_dir="./hub-data",                                  # database, caches, and by default the settings
        settings_path="./my-app/hanakura.toml",                # put the settings file where you like
        model_roots=[ModelRoot("/srv/models", layout="comfyui", name="Models")],
        lock_model_roots=True,                                  # the user cannot change them
        combined_view=True,                                     # Library opens on "All folders"
        port=0,                                                 # 0: any free port
        api_prefix="/hanakura",                                # keeps our routes out of yours
    )
    url = hub.start()      # returns as soon as it is listening: http://127.0.0.1:54123/hanakura
    ...
    hub.stop()

``hub.run()`` serves in the foreground instead. The object is also a context manager, and
``hub.services`` exposes the library, downloads and settings for direct use.
"""

import hashlib
import logging
import socket
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from hanakura.core.context import Services, build_services
from hanakura.core.errors import ValidationError
from hanakura.core.library.models import COMBINED_VIEW_ID
from hanakura.core.net.ports import PortUnavailableError, bind_first_free_port, is_loopback
from hanakura.core.settings.models import LayoutName

logger = logging.getLogger(__name__)

START_TIMEOUT = 30.0


@dataclass(frozen=True)
class ModelRoot:
    """A folder of models the host application provides.

    ``layout`` decides which folder holds which kind of model: ``comfyui`` (``checkpoints``,
    ``loras``, ``vae``, …), ``sd-webui`` (``models/Stable-diffusion``, ``models/Lora``, …, with
    ``embeddings`` beside ``models``), or ``custom`` for no mapping at all.
    ``kind`` supplies a fallback folder hint for a dedicated directory. An explicit ``id``
    remains stable across restarts; otherwise one is derived from the resolved path.
    """

    path: str | Path
    layout: LayoutName = "custom"
    name: str | None = None
    id: str | None = None
    kind: str | None = None

    def to_settings(self) -> dict[str, Any]:
        if self.id == COMBINED_VIEW_ID:
            raise ValidationError(f"{COMBINED_VIEW_ID!r} is reserved for the combined view and cannot be a root id")
        path = Path(self.path).expanduser().resolve()
        return {
            "id": self.id or f"host-{hashlib.sha256(str(path).encode()).hexdigest()[:16]}",
            "name": self.name or path.name or str(path),
            "path": str(path),
            "layout": self.layout,
            "kind": self.kind,
        }


class HanakuraServer:
    """The web UI and API, embedded in another program."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        settings_path: str | Path | None = None,
        model_roots: Iterable[ModelRoot | str | Path] | None = None,
        lock_model_roots: bool = False,
        combined_view: bool | None = None,
        host: str | None = None,
        port: int | None = None,
        strict_port: bool = False,
        api_prefix: str | None = None,
        public_base_url: str | None = None,
        open_browser: bool = False,
        access_token: str | None = None,
        settings: dict[str, Any] | None = None,
        log_level: str = "warning",
    ) -> None:
        """
        ``data_dir`` holds the settings file, the database and the caches. ``settings_path`` puts
        the settings file somewhere else — your own configuration folder, for instance — while the
        database and caches stay in ``data_dir``.

        ``model_roots`` are folders of models, each with its own layout. With
        ``lock_model_roots`` they are fixed: the API refuses to add, change or remove a folder
        and the interface hides those actions.

        ``combined_view`` pins the Library's "All folders" entry, which lists the top level of
        every model folder side by side: ``True`` offers it first, ``False`` hides it, and
        ``None`` leaves the choice to the user (it is off by default).

        ``port`` is ``0`` for any free port, a number to ask for that one (moving up when it is
        taken, unless ``strict_port``), or ``None`` for the port in the settings.

        ``api_prefix`` moves the API, the socket and the web UI under one path, so they cannot
        collide with the host application's own routes.

        ``public_base_url`` is the trusted external URL of the UI, including any deployment
        path, used for OAuth callbacks and cookies behind a proxy. It does not change routing.

        ``settings`` pins any other setting, in the same shape as the settings file, for example
        ``{"downloads": {"verify_hash": False}}``. Pinned values cannot be changed through the UI.
        """
        self.data_dir = Path(data_dir).expanduser() if data_dir else None
        self.settings_path = Path(settings_path).expanduser() if settings_path else None
        self.lock_model_roots = lock_model_roots
        self.api_prefix = api_prefix or ""
        self.public_base_url = public_base_url
        self.open_browser = open_browser
        self.strict_port = strict_port
        self._requested_port = port
        self._log_level = log_level

        roots = [r if isinstance(r, ModelRoot) else ModelRoot(r) for r in (model_roots or [])]
        overrides: dict[str, Any] = {k: dict(v) if isinstance(v, dict) else v for k, v in (settings or {}).items()}
        server_overrides: dict[str, Any] = dict(overrides.get("server") or {})
        if host is not None:
            server_overrides["host"] = host
        if access_token is not None:
            server_overrides["access_token"] = access_token
        server_overrides["open_browser"] = open_browser
        if server_overrides:
            overrides["server"] = server_overrides
        if combined_view is not None:
            overrides["library"] = {**(overrides.get("library") or {}), "combined_view": combined_view}
        # Locked roots are an override, so they cannot be edited or lost; unlocked ones are a
        # starting point the user may add to, so they are saved normally at start-up.
        if model_roots is not None and lock_model_roots:
            overrides["paths"] = {**(overrides.get("paths") or {}), "model_roots": [r.to_settings() for r in roots]}
        self._roots = roots
        self._overrides = overrides

        self.services: Services | None = None
        self._socket: socket.socket | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._url: str | None = None

    # -- lifecycle ----------------------------------------------------------

    def _build(self) -> Services:
        services = build_services(
            data_dir=self.data_dir,
            settings_path=self.settings_path,
            settings_overrides=self._overrides,
            roots_locked=self.lock_model_roots,
        )
        if self._roots and not self.lock_model_roots:
            self._seed_roots(services)
        return services

    def _seed_roots(self, services: Services) -> None:
        """Add the host's folders to the saved settings, keeping any the user added."""
        from hanakura.core.errors import HanakuraError
        from hanakura.core.library.models import RootCreate

        known = {Path(r.path).resolve() for r in services.library.list_roots()}
        for root in self._roots:
            spec = root.to_settings()
            if Path(spec["path"]).resolve() in known:
                continue
            try:
                services.library.add_root(RootCreate(name=spec["name"], path=spec["path"], layout=spec["layout"], kind=spec["kind"]), root_id=spec["id"])
                known.add(Path(spec["path"]).resolve())
            except HanakuraError as e:
                logger.warning("Could not add the model folder %s: %s", spec["path"], e)

    def _bind(self, services: Services) -> socket.socket:
        server_settings = services.settings.settings.server
        host = server_settings.host
        port = server_settings.port if self._requested_port is None else self._requested_port
        if not is_loopback(host) and not server_settings.access_token:
            raise PortUnavailableError(f"Refusing to listen on {host} without an access token. Pass access_token=... to HanakuraServer.")
        sock = bind_first_free_port(host, port, strict=self.strict_port or port == 0)
        return sock

    def _make_app(self, services: Services, port: int) -> Any:
        from hanakura.api.app import create_app

        host = services.settings.settings.server.host
        return create_app(services, bound_host=host, bound_port=port, api_prefix=self.api_prefix, public_base_url=self.public_base_url)

    def start(self, timeout: float = START_TIMEOUT) -> str:
        """Start serving in a background thread and return the URL of the web UI."""
        import uvicorn

        if self._thread is not None:
            return self.url
        services = self._build()
        self.services = services
        try:
            self._socket = self._bind(services)
            port = self._socket.getsockname()[1]
            self._url = self._public_url(services.settings.settings.server.host, port)
            app = self._make_app(services, port)
            self._server = uvicorn.Server(uvicorn.Config(app=app, log_level=self._log_level, lifespan="on"))
            sock = self._socket
            self._thread = threading.Thread(target=lambda: self._server.run(sockets=[sock]), name="hanakura", daemon=True)
            self._thread.start()
            self._wait_until_started(timeout)
        except BaseException:
            self.stop()
            raise
        if self.open_browser:
            import webbrowser

            threading.Timer(0.5, lambda: webbrowser.open(self._url or "")).start()
        logger.info("Hanakura is running on %s", self._url)
        return self._url or ""

    def _wait_until_started(self, timeout: float) -> None:
        deadline = threading.Event()
        waited = 0.0
        while waited < timeout:
            if getattr(self._server, "started", False):
                return
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError("The server stopped while starting; see the log for the reason.")
            deadline.wait(0.05)
            waited += 0.05
        raise TimeoutError(f"The server did not start within {timeout} seconds")

    def run(self) -> None:
        """Serve in the foreground until interrupted."""
        self.start()
        try:
            while self._thread is not None and self._thread.is_alive():
                self._thread.join(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self, timeout: float = 10.0) -> None:
        """Stop serving and release everything. Safe to call more than once."""
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._server = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self.services is not None:
            self.services.close()
            self.services = None
        self._url = None

    # -- information --------------------------------------------------------

    @property
    def url(self) -> str:
        """Where the web UI is, once started."""
        if not self._url:
            raise RuntimeError("The server is not running; call start() first.")
        return self._url

    @property
    def port(self) -> int:
        return int(self.url.rsplit(":", 1)[1].split("/")[0])

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _public_url(self, host: str, port: int) -> str:
        from hanakura.api.app import normalize_prefix

        shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        if ":" in shown and not shown.startswith("["):
            shown = f"[{shown}]"
        return f"http://{shown}:{port}{normalize_prefix(self.api_prefix)}"

    # typing.Self needs Python 3.11; this package supports 3.10.
    def __enter__(self) -> "HanakuraServer":  # noqa: PYI034
        self.start()
        return self

    def __exit__(self, _type: type[BaseException] | None, _value: BaseException | None, _tb: TracebackType | None) -> None:
        self.stop()


def serve(block: bool = False, **options: Any) -> HanakuraServer:
    """Start a server with ``HanakuraServer`` options. With ``block`` it serves in the foreground.

    Returns the server, so a caller can read ``server.url`` and later ``server.stop()``.
    """
    server = HanakuraServer(**options)
    if block:
        server.run()
    else:
        server.start()
    return server


__all__ = ["HanakuraServer", "LayoutName", "ModelRoot", "serve"]

# Re-exported for type checking in host applications.
Layout = Literal["comfyui", "sd-webui", "custom"]
