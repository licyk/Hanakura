"""Load, override and save settings."""

import copy
import json
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import ValidationError as PydanticValidationError

from sd_model_hub.core.errors import ValidationError
from sd_model_hub.core.paths import DATA_DIR_ENV, ENV_PREFIX, default_data_dir
from sd_model_hub.core.settings.models import ServerSettingsView, Settings, SettingsView, SourceSettingsView

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

SETTINGS_FILE_NAME = "settings.toml"


def _parse_scalar(raw: str) -> Any:
    """Turn a command-line or environment string into a value: JSON when it parses, else the string."""
    text = raw.strip()
    if text.lower() in ("null", "none"):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return raw


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _strip_none(value: Any) -> Any:
    """TOML has no null: drop keys whose value is None."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _get_dotted(data: Any, dotted: str) -> Any:
    node = data
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(dotted)
    return node


class SettingsService:
    """Owns ``settings.toml``. Environment variables with the ``SD_MODEL_HUB_`` prefix override it.

    An override uses ``__`` between levels, for example ``SD_MODEL_HUB_SERVER__PORT=8000``.
    Overrides are applied on top of the file and are never written back to it.
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        settings_path: Path | None = None,
        environ: dict[str, str] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        """``overrides`` come from a host application embedding this package.

        They sit above the file and the environment, are never written back, and cannot be
        changed through the API, so a host can pin a value for the life of the process.
        """
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.path = settings_path or self.data_dir / SETTINGS_FILE_NAME
        self._environ = environ if environ is not None else os.environ
        self._overrides = copy.deepcopy(overrides or {})
        self._lock = threading.RLock()
        self._listeners: list[Callable[[Settings], None]] = []
        self._file_data: dict[str, Any] = {}
        self._settings = Settings()
        self.reload()

    # -- loading -----------------------------------------------------------

    def env_overrides(self) -> dict[str, Any]:
        """Return the overrides found in the environment, as a nested dict."""
        out: dict[str, Any] = {}
        for key, raw in self._environ.items():
            if not key.startswith(ENV_PREFIX) or key == DATA_DIR_ENV or "__" not in key:
                continue
            dotted = key[len(ENV_PREFIX) :].lower().replace("__", ".")
            _set_dotted(out, dotted, _parse_scalar(raw))
        return out

    def env_override_names(self) -> list[str]:
        return sorted(k for k in self._environ if k.startswith(ENV_PREFIX) and k != DATA_DIR_ENV and "__" in k)

    def pinned_names(self) -> list[str]:
        """Dotted names of every value the host application pinned, such as ``library.combined_view``."""

        def walk(data: dict[str, Any], prefix: str) -> list[str]:
            names: list[str] = []
            for key, value in data.items():
                name = f"{prefix}{key}"
                names += walk(value, f"{name}.") if isinstance(value, dict) and value else [name]
            return names

        return sorted(walk(self._overrides, ""))

    def reload(self) -> None:
        with self._lock:
            if self.path.is_file():
                with open(self.path, "rb") as f:
                    self._file_data = tomllib.load(f)
            else:
                self._file_data = {}
            self._settings = self._validate(self._effective(self._file_data))

    def _effective(self, file_data: dict[str, Any]) -> dict[str, Any]:
        """Defaults, then the file, then the environment, then the host application's overrides."""
        merged = _deep_merge(Settings().model_dump(), _deep_merge(file_data, self.env_overrides()))
        return _deep_merge(merged, self._overrides)

    @staticmethod
    def _validate(data: dict[str, Any]) -> Settings:
        try:
            return Settings.model_validate(data)
        except PydanticValidationError as e:
            errors = [{key: value for key, value in error.items() if key != "url"} for error in e.errors()]
            first = e.errors()[0]
            raise ValidationError(f"Invalid settings: {first['msg']} at {'.'.join(str(p) for p in first['loc'])}", {"errors": errors}) from e

    @property
    def settings(self) -> Settings:
        """The effective settings: defaults, then the file, then the environment."""
        return self._settings

    def on_change(self, listener: Callable[[Settings], None]) -> None:
        self._listeners.append(listener)

    # -- saving ------------------------------------------------------------

    def update(self, patch: dict[str, Any]) -> Settings:
        """Deep-merge ``patch`` into the file settings, validate, save and return the effective settings.

        Dicts merge; every other value replaces. ``None`` clears an optional value, such as a token.
        """
        with self._lock:
            merged_file = _deep_merge(self._file_data, patch)
            file_settings = self._validate(_deep_merge(Settings().model_dump(), merged_file))
            effective = self._validate(self._effective(file_settings.model_dump()))
            self._write(file_settings)
            self._file_data = file_settings.model_dump()
            self._settings = effective
        for listener in self._listeners:
            listener(effective)
        return effective

    def mutate(self, fn: Callable[[dict[str, Any]], None]) -> Settings:
        """Apply ``fn`` to a copy of the file settings as a dict, then save."""
        with self._lock:
            data = _deep_merge(Settings().model_dump(), self._file_data)
            fn(data)
            return self.update(data)

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".toml.tmp")
        with open(tmp, "wb") as f:
            tomli_w.dump(_strip_none(settings.model_dump()), f)
        os.replace(tmp, self.path)

    # -- dotted access for the command line --------------------------------

    def get_value(self, dotted: str) -> Any:
        try:
            value = _get_dotted(self.view().model_dump(), dotted)
        except KeyError:
            raise ValidationError(f"Unknown setting: {dotted}") from None
        return value

    def set_value(self, dotted: str, raw: str) -> Settings:
        try:
            _get_dotted(self.settings.model_dump(), dotted)
        except KeyError:
            # Allow new keys only inside dict-valued groups, such as sources.<name> or downloads.kind_folders.
            parent = dotted.rsplit(".", 1)[0]
            try:
                if not isinstance(_get_dotted(self.settings.model_dump(), parent), dict):
                    raise KeyError(parent)
            except KeyError:
                raise ValidationError(f"Unknown setting: {dotted}") from None
        patch: dict[str, Any] = {}
        _set_dotted(patch, dotted, _parse_scalar(raw))
        return self.update(patch)

    # -- public view -------------------------------------------------------

    def view(self) -> SettingsView:
        s = self.settings
        return SettingsView(
            data_dir=str(self.data_dir),
            settings_file=str(self.path),
            server=ServerSettingsView(
                host=s.server.host,
                port=s.server.port,
                strict_port=s.server.strict_port,
                open_browser=s.server.open_browser,
                access_token_configured=bool(s.server.access_token),
                allowed_origins=s.server.allowed_origins,
            ),
            paths=s.paths,
            auth=s.auth,
            sources={
                name: SourceSettingsView(enabled=src.enabled, token_configured=bool(src.token), base_url=src.base_url, endpoint=src.endpoint) for name, src in s.sources.items()
            },
            network=s.network,
            downloads=s.downloads,
            content=s.content,
            library=s.library,
            env_overrides=self.env_override_names(),
            pinned=self.pinned_names(),
        )
