import json
import struct
from pathlib import Path
from typing import Any

import pytest

from hanakura.core.context import Services, build_services
from hanakura.core.library.models import RootCreate


def write_safetensors(path: Path, tensors: dict[str, list[int]], metadata: dict[str, str] | None = None, payload: bytes = b"") -> Path:
    """Write a safetensors file with the given tensor table. Weights are not needed for detection."""
    header: dict[str, Any] = {name: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]} for name, shape in tensors.items()}
    if metadata:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)
    return path


LORA_SDXL = {
    "lora_unet_input_blocks_4_1_transformer_blocks_0_attn2_to_k.lora_down.weight": [16, 2048],
    "lora_unet_input_blocks_4_1_transformer_blocks_0_attn2_to_k.lora_up.weight": [640, 16],
}
LORA_SD1 = {
    "lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k.lora_down.weight": [8, 768],
    "lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k.lora_up.weight": [320, 8],
}


@pytest.fixture
def services(tmp_path: Path):
    s = build_services(data_dir=tmp_path / "data", environ={})
    yield s
    s.close()


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models"
    for sub in ("checkpoints", "loras/style", "vae"):
        (d / sub).mkdir(parents=True)
    return d


@pytest.fixture
def root(services: Services, root_dir: Path):
    return services.library.add_root(RootCreate(name="comfy", path=str(root_dir), layout="comfyui"))
