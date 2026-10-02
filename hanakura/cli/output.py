"""Tables, ``--json`` output and download progress for the command line."""

import json
import sys
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from hanakura.core.context import Services

console = Console()
err_console = Console(stderr=True)


def human_size(size: float | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return json.loads(value.json())
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def print_json(value: Any) -> None:
    """Print the same shape the API returns."""
    sys.stdout.write(json.dumps(to_jsonable(value), indent=2, ensure_ascii=False) + "\n")


def print_table(title: str | None, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    table = Table(title=title, show_lines=False, header_style="bold")
    for column in columns:
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(*["" if v is None else str(v) for v in row])
    console.print(table)


@contextmanager
def open_services(owned_downloads: bool = True):  # type: ignore[no-untyped-def]
    """Build the services for one command and close them afterwards."""
    from hanakura.core.context import build_services

    services: Services = build_services(owned_downloads_only=owned_downloads)
    try:
        yield services
    finally:
        services.close()
