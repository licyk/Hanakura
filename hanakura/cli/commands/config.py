"""config show | get | set | path."""

from typing import Annotated

import typer

from hanakura.cli.output import console, print_json


def _settings():  # type: ignore[no-untyped-def]
    from hanakura.core.settings import SettingsService

    return SettingsService()


def config_show(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show the effective settings. Tokens are shown only as configured or not."""
    view = _settings().view()
    if json_output:
        print_json(view)
        return
    console.print_json(view.model_dump_json())


def config_get(key: Annotated[str, typer.Argument(help="Dotted key, e.g. server.port")]) -> None:
    """Print one setting."""
    print_json(_settings().get_value(key))


def config_set(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. server.port or sources.civitai.token")],
    value: Annotated[str, typer.Argument(help="New value. JSON is parsed (numbers, true/false, lists); 'null' clears")],
) -> None:
    """Change one setting and save it."""
    service = _settings()
    service.set_value(key, value)
    shown = "(hidden)" if key.endswith("token") else service.get_value(key)
    console.print(f"{key} = {shown}")
    if f"HANAKURA_{key.upper().replace('.', '__')}" in service.env_override_names():
        console.print("[yellow]An environment variable overrides this setting.[/yellow]")


def config_path() -> None:
    """Print the path of the settings file."""
    print(_settings().path)
