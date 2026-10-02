import gzip
import json
import struct
from pathlib import Path

import pytest

from hanakura.core.db import Database
from hanakura.core.detection import DetectionService
from hanakura.core.detection.header import HeaderError, ModelHeader, read_gguf_header, read_safetensors_header
from hanakura.core.detection.rules import RuleTable
from tests.conftest import LORA_SD1, LORA_SDXL, write_safetensors

FIXTURES = sorted((Path(__file__).parent.parent / "fixtures" / "headers").glob("*.json.gz"))


@pytest.fixture(scope="module")
def detector() -> DetectionService:
    return DetectionService(Database(":memory:"))


def _load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f.name.split(".")[0] for f in FIXTURES])
def test_real_headers(detector, fixture):
    """Headers saved from real files in a Forge and a ComfyUI install."""
    data = _load(fixture)
    result = detector.detect_header(ModelHeader(format=data["format"], tensors=data["tensors"], metadata=data["metadata"]))
    assert (result.kind, result.base_model) == (data["expect"]["kind"], data["expect"]["base_model"])


def test_the_two_vae_misfires_stay_vaes(detector):
    """A video VAE looked like a diffusion model and an audio VAE like T5 to loose substring rules."""
    names = [f for f in FIXTURES if "minimax_h3_audio_vae" in f.name or "minimax_h3_video_vae" in f.name]
    assert len(names) == 2
    for f in names:
        data = _load(f)
        assert detector.detect_header(ModelHeader(format="safetensors", tensors=data["tensors"])).kind == "vae"


SYNTHETIC = {
    # Not yet checked against real files: ControlNet, embeddings and upscalers (plan section 11).
    "controlnet_sd1": (
        {"control_model.input_hint_block.0.weight": [16, 3, 3, 3], "control_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [320, 768]},
        "controlnet",
        "sd1",
    ),
    "controlnet_sdxl_diffusers": (
        {"controlnet_cond_embedding.conv_in.weight": [16, 3, 3, 3], "down_blocks.1.attentions.0.transformer_blocks.0.attn2.to_k.weight": [640, 2048]},
        "controlnet",
        "sdxl",
    ),
    "embedding_sd1": ({"emb_params": [4, 768]}, "embedding", "sd1"),
    "embedding_sdxl": ({"clip_l": [4, 768], "clip_g": [4, 1280]}, "embedding", "sdxl"),
    "upscaler_esrgan": ({"conv_first.weight": [64, 3, 3, 3], "body.0.rdb1.conv1.weight": [32, 64, 3, 3]}, "upscaler", None),
    "sd1_checkpoint": (
        {
            "model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [320, 768],
            "first_stage_model.decoder.conv_in.weight": [512, 4, 3, 3],
            "cond_stage_model.transformer.text_model.embeddings.position_ids": [1, 77],
        },
        "checkpoint",
        "sd1",
    ),
    "flux_unet": ({"double_blocks.0.img_attn.norm.key_norm.scale": [128], "img_in.weight": [3072, 64]}, "diffusion_model", "flux1"),
    "sdxl_vpred": (
        {
            "model.diffusion_model.label_emb.0.0.weight": [1280, 2816],
            "conditioner.embedders.0.transformer.text_model.embeddings.position_ids": [1, 77],
            "v_pred": [],
        },
        "checkpoint",
        "sdxl",
    ),
    "t5": ({"encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096], "shared.weight": [32128, 4096]}, "text_encoder", "t5"),
    "clip_l": ({"text_model.encoder.layers.0.self_attn.q_proj.weight": [768, 768]}, "text_encoder", "clip-l"),
    "lora_sdxl": (LORA_SDXL, "lora", "sdxl"),
    "lora_sd1": (LORA_SD1, "lora", "sd1"),
    "lora_flux": ({"lora_unet_double_blocks_0_img_attn_proj.lora_down.weight": [16, 3072]}, "lora", "flux1"),
    "random": ({"foo.bar": [1], "baz": [2, 2]}, "unknown", None),
}


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_synthetic_headers(detector, name):
    tensors, kind, base = SYNTHETIC[name]
    result = detector.detect_header(ModelHeader(format="safetensors", tensors=tensors))
    assert (result.kind, result.base_model) == (kind, base)


def test_prediction_type(detector):
    tensors, _, _ = SYNTHETIC["sdxl_vpred"]
    assert detector.detect_header(ModelHeader(format="safetensors", tensors=tensors)).prediction_type == "v"


def test_metadata_fallback_when_no_rule(detector):
    result = detector.detect_header(ModelHeader(format="safetensors", tensors={"x.lora_down.weight": [4, 4]}, metadata={"ss_base_model_version": "sdxl_base_v1-0"}))
    assert (result.kind, result.base_model, result.rule_id) == ("lora", "sdxl", "metadata")


def test_header_length_checks(tmp_path):
    bad = tmp_path / "bad.safetensors"
    bad.write_bytes(struct.pack("<Q", 10**12) + b"{}")
    with pytest.raises(HeaderError):
        read_safetensors_header(bad)
    short = tmp_path / "short.safetensors"
    short.write_bytes(b"\x01\x02")
    with pytest.raises(HeaderError):
        read_safetensors_header(short)
    notjson = tmp_path / "nj.safetensors"
    notjson.write_bytes(struct.pack("<Q", 4) + b"abcd")
    with pytest.raises(HeaderError):
        read_safetensors_header(notjson)


def test_file_detection_and_cache(tmp_path):
    svc = DetectionService(Database(tmp_path / "db.sqlite"))
    path = write_safetensors(tmp_path / "a.safetensors", LORA_SDXL, {"modelspec.title": "A"})
    result, meta = svc.detect(path)
    assert result.base_model == "sdxl" and meta == {"modelspec.title": "A"}
    assert svc.cached(path) is not None
    write_safetensors(path, LORA_SD1)  # size changes: the cache row is no longer valid
    assert svc.cached(path) is None
    assert svc.detect(path)[0].base_model == "sd1"


def test_pickles_are_never_opened(tmp_path, detector):
    path = tmp_path / "model.ckpt"
    path.write_bytes(b"not really a pickle")
    result, _ = detector.detect_path(path)
    assert result.kind == "unknown" and result.format == "ckpt"


def test_diffusers_folder(tmp_path, detector):
    folder = tmp_path / "sdxl-model"
    folder.mkdir()
    (folder / "model_index.json").write_text(json.dumps({"_class_name": "StableDiffusionXLPipeline"}))
    result, _ = detector.detect_path(folder)
    assert (result.kind, result.base_model) == ("diffusers", "sdxl")


def _gguf_string(s: str) -> bytes:
    raw = s.encode()
    return struct.pack("<Q", len(raw)) + raw


def test_gguf_header(tmp_path, detector):
    path = tmp_path / "flux-Q4.gguf"
    body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 2) + struct.pack("<Q", 1)
    body += _gguf_string("general.architecture") + struct.pack("<I", 8) + _gguf_string("flux")
    for name, dims in (("double_blocks.0.img_attn.norm.key_norm.scale", [128]), ("img_in.weight", [64, 3072])):
        body += _gguf_string(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims) + struct.pack("<I", 0) + struct.pack("<Q", 0)
    path.write_bytes(body)
    header = read_gguf_header(path)
    assert header.tensors["img_in.weight"] == [3072, 64]
    assert header.metadata["general.architecture"] == "flux"
    result, _ = detector.detect_path(path)
    assert (result.kind, result.base_model) == ("diffusion_model", "flux1")


def test_rule_ids_unique_and_priorities_loaded():
    table = RuleTable.load_default()
    assert len({r.id for r in table.rules}) == len(table.rules)
    assert [r.priority for r in table.rules] == sorted((r.priority for r in table.rules), reverse=True)
