"""version, env."""

import os
import platform
from importlib import metadata
from typing import Annotated

import typer

from hanakura.cli.output import print_json, print_table
from hanakura.version import VERSION

COMPONENTS = ("fastapi", "uvicorn", "python-socketio", "httpx", "pydantic", "typer", "huggingface_hub", "modelscope")

ENV_VARS = {
    "HANAKURA_DATA_DIR": "Data directory holding settings.toml, the database and caches",
    "HANAKURA_LOG_LEVEL": "Log level: DEBUG, INFO, WARNING or ERROR",
    "HANAKURA_<GROUP>__<FIELD>": "Override one setting, e.g. HANAKURA_SERVER__PORT=8000 or HANAKURA_SOURCES__CIVITAI__TOKEN=...",
}


def version(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show the version of Hanakura and its main components."""
    components: dict[str, str | None] = {}
    for name in COMPONENTS:
        try:
            components[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            components[name] = None
    if json_output:
        print_json({"hanakura": VERSION, "python": platform.python_version(), "components": components})
        return
    print_table(None, ["Component", "Version"], [("hanakura", VERSION), ("python", platform.python_version()), *((k, v or "not installed") for k, v in components.items())])


def env(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List the environment variables Hanakura reads, and those currently set."""
    in_use = {k: ("***" if "TOKEN" in k else v) for k, v in sorted(os.environ.items()) if k.startswith("HANAKURA_")}
    if json_output:
        print_json({"known": ENV_VARS, "set": in_use})
        return
    print_table("Environment variables", ["Name", "Meaning"], ENV_VARS.items())
    if in_use:
        print_table("Set now", ["Name", "Value"], in_use.items())
