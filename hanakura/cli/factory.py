"""Typer factory and custom classes, after ani2xcur-cli.

The private ``typer._click`` imports are confined to this module; ``pyproject.toml`` pins an
upper bound on Typer to guard them.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from typer import _click
from typer.core import TyperCommand, TyperGroup, TyperOption

from hanakura.core.paths import DATA_DIR_ENV
from hanakura.logger import LOGGER_NAME

DEBUG_OPTION_HELP = "Print debug logs"
DATA_DIR_OPTION_HELP = f"Use this data directory (settings, database, credentials) instead of {DATA_DIR_ENV} or the default"

# Re-exported for app.py, so it needs no private import of its own.
ClickException = _click.ClickException


def _debug_option_callback(ctx: _click.Context, _param: _click.Parameter, value: bool) -> None:
    """Turn on debug logging."""
    if value and not ctx.resilient_parsing:
        app_logger = logging.getLogger(LOGGER_NAME)
        app_logger.setLevel(logging.DEBUG)
        app_logger.debug("Debug logging enabled")


def _make_debug_option() -> TyperOption:
    """A ``--debug`` option that can be attached at any level."""
    return TyperOption(
        param_decls=["--debug"],
        is_flag=True,
        is_eager=True,
        expose_value=False,
        help=DEBUG_OPTION_HELP,
        callback=_debug_option_callback,
    )


def _has_debug_option(params: list[_click.Parameter] | None) -> bool:
    return any(isinstance(param, TyperOption) and "--debug" in param.opts for param in params or [])


def _with_debug_option(params: list[_click.Parameter] | None) -> list[_click.Parameter]:
    normalized = list(params or [])
    if _has_debug_option(normalized):
        return normalized
    return [_make_debug_option(), *normalized]


def _data_dir_option_callback(ctx: _click.Context, _param: _click.Parameter, value: str | None) -> None:
    """Point this command, and the processes it starts, at another data directory: through the environment variable
    every way of opening the services reads."""
    if value and not ctx.resilient_parsing:
        os.environ[DATA_DIR_ENV] = str(Path(value).expanduser().resolve())


def _make_data_dir_option() -> TyperOption:
    """A ``--data-dir`` option that can be attached at any level, before or after the command's name."""
    return TyperOption(
        param_decls=["--data-dir"],
        is_eager=True,
        expose_value=False,
        metavar="DIR",
        help=DATA_DIR_OPTION_HELP,
        callback=_data_dir_option_callback,
    )


def _with_shared_options(params: list[_click.Parameter] | None) -> list[_click.Parameter]:
    """``params`` with ``--debug`` and ``--data-dir``, unless the command defines them itself (``webui`` has its own
    ``--data-dir``)."""
    normalized = _with_debug_option(params)
    if any(isinstance(param, TyperOption) and "--data-dir" in param.opts for param in normalized):
        return normalized
    return [*normalized, _make_data_dir_option()]


class DebugTyperCommand(TyperCommand):
    """A Typer command that always has ``--debug``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["params"] = _with_shared_options(kwargs.get("params"))
        super().__init__(*args, **kwargs)


class AlphabeticalMixedGroup(TyperGroup):
    """A group with ``--debug`` that lists commands and subgroups alphabetically."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["params"] = _with_shared_options(kwargs.get("params"))
        super().__init__(*args, **kwargs)

    def list_commands(self, ctx: _click.Context) -> list[str]:  # type: ignore[override]
        return sorted(self.commands.keys())


class DebugOptionTyper(typer.Typer):
    """A Typer app whose commands use DebugTyperCommand by default."""

    def command(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        kwargs.setdefault("cls", DebugTyperCommand)
        return super().command(*args, **kwargs)


def typer_factory(help: str) -> typer.Typer:
    """Create an app or group with the shared settings."""
    return DebugOptionTyper(
        help=help,
        add_completion=True,
        no_args_is_help=True,
        cls=AlphabeticalMixedGroup,
        rich_markup_mode=None,
        rich_help_panel=None,
        pretty_exceptions_enable=False,
    )
