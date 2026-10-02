"""SD Model Hub: download and manage Stable Diffusion models.

To embed the web UI and API in another application:

    from sd_model_hub import ModelHubServer, ModelRoot

    hub = ModelHubServer(model_roots=[ModelRoot("/srv/models", layout="comfyui")], port=0)
    print(hub.start())   # http://127.0.0.1:54123
"""

import warnings
from typing import TYPE_CHECKING, Any

from sd_model_hub.version import VERSION

DEPRECATION_MESSAGE = "sd-model-hub is deprecated and no longer receives updates. It continues as Hanakura: install it with `python -m pip install hanakura`."

# FutureWarning rather than DeprecationWarning: Python hides the latter outside ``__main__``, and
# this one is for the people running the program, not only for developers.
warnings.warn(DEPRECATION_MESSAGE, FutureWarning, stacklevel=2)

if TYPE_CHECKING:
    from sd_model_hub.embed import ModelHubServer, ModelRoot, serve

__all__ = ["VERSION", "ModelHubServer", "ModelRoot", "serve"]

_LAZY = {"ModelHubServer", "ModelRoot", "serve"}


def __getattr__(name: str) -> Any:
    """Import the server lazily, so ``sd-model-hub version`` does not pay for FastAPI."""
    if name in _LAZY:
        from sd_model_hub import embed

        return getattr(embed, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
