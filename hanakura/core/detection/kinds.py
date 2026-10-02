"""Decide what kind of file a tensor table is, before asking which architecture.

The key patterns are facts about the file formats, reimplemented rather than copied from ComfyUI
(GPL-3.0), and checked against 555 real model files. Every pattern is anchored to an exact key or
a prefix; loose substrings such as ``blocks.0.`` match the insides of unrelated models, which is
how two newer VAEs were once taken for a diffusion model and a T5 text encoder.
"""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from hanakura.core.detection.models import ModelKind

LORA_MARKERS = (".lora_up.", ".lora_down.", ".lora_A.", ".lora_B.", ".hada_w1", ".lokr_w1", ".lora_mid.")
CONTROLNET_PREFIXES = ("control_model.",)
CONTROLNET_SEGMENTS = ("input_hint_block.", "controlnet_cond_embedding.")
CHECKPOINT_UNET_PREFIX = "model.diffusion_model."
CHECKPOINT_COMPANION_PREFIXES = ("first_stage_model.", "cond_stage_model.", "conditioner.embedders.")
T5_MARKER = "encoder.block.0.layer.0.SelfAttention.q.weight"
TEXT_ENCODER_MARKERS = (
    T5_MARKER,
    "text_model.encoder.layers.0.self_attn.q_proj.weight",  # CLIP (transformers layout)
    "transformer.resblocks.0.attn.in_proj_weight",  # OpenCLIP layout
    "model.layers.0.self_attn.q_proj.weight",  # Llama, Qwen and other decoder-only encoders
    "layers.0.self_attn.q_proj.weight",
)
# Bare diffusion model markers (no prefix): one key each architecture alone has, plus the classic
# UNet's first input block, which SD1, SD2, SDXL and their relatives share.
DIFFUSION_MARKERS = (
    "input_blocks.0.0.weight",
    "joint_blocks.0.context_block.attn.qkv.weight",
    "clf.1.weight",
    "double_layers.0.attn.w1q.weight",
    "mlp_t5.0.weight",
    "txt_in.individual_token_refiner.blocks.0.norm1.weight",
    "double_blocks.0.img_attn.norm.key_norm.scale",
    "double_blocks.0.img_attn.norm.key_norm.weight",
    "t5_yproj.weight",
    "adaln_single.emb.timestep_embedder.linear_1.bias",
    "t_block.1.weight",
    "cap_embedder.1.weight",
    "head.modulation",
    "txt_norm.weight",
    "caption_projection.0.linear.weight",
    "blocks.0.adaln_modulation_self_attn.1.weight",  # Cosmos (under the "net." prefix)
)
DIFFUSION_PREFIXES = ("", CHECKPOINT_UNET_PREFIX, "model.", "net.")
EMBEDDING_KEYS = ("emb_params", "clip_l", "clip_g")
EMBEDDING_PREFIXES = ("string_to_param.",)
UPSCALER_MARKERS = (
    "conv_first.weight",  # ESRGAN (new layout), SwinIR, DAT
    "model.0.weight",  # ESRGAN (old layout)
    "body.0.rdb1.conv1.weight",
)
VAE_SHARE_THRESHOLD = 0.9


@dataclass(frozen=True)
class KindResult:
    kind: ModelKind
    rule: str
    prefix: str = ""
    confidence: float = 1.0


def _top_level_share(keys: list[str], names: Iterable[str]) -> float:
    if not keys:
        return 0.0
    counts = Counter(k.split(".", 1)[0] for k in keys)
    return sum(counts[n] for n in names) / len(keys)


def _is_lora(keys: list[str], key_set: set[str]) -> KindResult | None:
    if any(any(m in k for m in LORA_MARKERS) for k in keys):
        return KindResult("lora", "lora-markers")
    return None


def _is_controlnet(keys: list[str], key_set: set[str]) -> KindResult | None:
    for k in keys:
        if k.startswith(CONTROLNET_PREFIXES):
            return KindResult("controlnet", "controlnet-prefix", prefix="control_model.", confidence=0.8)
        head = k.split(".", 1)[0] + "."
        if head in CONTROLNET_SEGMENTS:
            return KindResult("controlnet", "controlnet-segment", confidence=0.8)
    return None


def _is_checkpoint(keys: list[str], key_set: set[str]) -> KindResult | None:
    has_unet = any(k.startswith(CHECKPOINT_UNET_PREFIX) for k in keys)
    if has_unet and any(k.startswith(CHECKPOINT_COMPANION_PREFIXES) for k in keys):
        return KindResult("checkpoint", "checkpoint-prefixes", prefix=CHECKPOINT_UNET_PREFIX)
    return None


def _is_vae(keys: list[str], key_set: set[str]) -> KindResult | None:
    if T5_MARKER in key_set:
        return None
    if not any(k.startswith("decoder.") for k in keys):
        return None
    if _top_level_share(keys, ("encoder", "decoder")) >= VAE_SHARE_THRESHOLD:
        return KindResult("vae", "vae-share")
    return None


def _is_text_encoder(keys: list[str], key_set: set[str]) -> KindResult | None:
    for marker in TEXT_ENCODER_MARKERS:
        if marker in key_set:
            return KindResult("text_encoder", "te-marker")
    return None


def _is_diffusion_model(keys: list[str], key_set: set[str]) -> KindResult | None:
    for prefix in DIFFUSION_PREFIXES:
        if any(prefix + m in key_set for m in DIFFUSION_MARKERS):
            return KindResult("diffusion_model", "diffusion-marker", prefix=prefix)
    return None


def _is_embedding(keys: list[str], key_set: set[str]) -> KindResult | None:
    if len(keys) <= 8 and (any(k in key_set for k in EMBEDDING_KEYS) or any(k.startswith(EMBEDDING_PREFIXES) for k in keys)):
        return KindResult("embedding", "embedding-keys", confidence=0.8)
    return None


def _is_upscaler(keys: list[str], key_set: set[str]) -> KindResult | None:
    if any(m in key_set for m in UPSCALER_MARKERS) and len(keys) < 3000:
        return KindResult("upscaler", "upscaler-marker", confidence=0.6)
    return None


# Order matters: LoRA first (its keys embed other models' names), VAE before text encoder and
# diffusion model (both misfires in testing were VAEs).
KIND_TESTS: list[Callable[[list[str], set[str]], KindResult | None]] = [
    _is_lora,
    _is_controlnet,
    _is_checkpoint,
    _is_embedding,
    _is_vae,
    _is_text_encoder,
    _is_diffusion_model,
    _is_upscaler,
]


def classify_kind(keys: Iterable[str]) -> KindResult | None:
    """Return the kind of a tensor table, or ``None`` when no test matches."""
    key_list = list(keys)
    key_set = set(key_list)
    for test in KIND_TESTS:
        result = test(key_list, key_set)
        if result is not None:
            return result
    return None
