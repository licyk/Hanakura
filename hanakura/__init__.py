"""Hanakura: download and manage Stable Diffusion models.

To embed the web UI and API in another application:

    from hanakura import HanakuraServer, ModelRoot

    hub = HanakuraServer(model_roots=[ModelRoot("/srv/models", layout="comfyui")], port=0)
    print(hub.start())   # http://127.0.0.1:54123
"""

from typing import TYPE_CHECKING, Any

from hanakura.version import VERSION

if TYPE_CHECKING:
    from hanakura.embed import HanakuraServer, ModelRoot, serve

__all__ = ["VERSION", "HanakuraServer", "ModelRoot", "serve"]

_LAZY = {"HanakuraServer", "ModelRoot", "serve"}


def __getattr__(name: str) -> Any:
    """Import the server lazily, so ``hanakura version`` does not pay for FastAPI."""
    if name in _LAZY:
        from hanakura import embed

        return getattr(embed, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
