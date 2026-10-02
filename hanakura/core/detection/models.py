"""Detection result models and the vocabulary of kinds and base models."""

from typing import Literal

from hanakura.core.record import Record

ModelKind = Literal[
    "checkpoint",
    "diffusion_model",
    "lora",
    "vae",
    "text_encoder",
    "controlnet",
    "embedding",
    "upscaler",
    "diffusers",
    "unknown",
]

MODEL_KINDS: list[str] = ["checkpoint", "diffusion_model", "lora", "vae", "text_encoder", "controlnet", "embedding", "upscaler", "diffusers", "unknown"]

# Base model ids, with display names. Rule files and source adapters map onto these ids.
BASE_MODELS: dict[str, str] = {
    "sd1": "SD 1.x",
    "sd2": "SD 2.x",
    "sdxl": "SDXL",
    "sdxl-refiner": "SDXL Refiner",
    "sd3": "SD 3.x",
    "stable-cascade": "Stable Cascade",
    "svd": "Stable Video Diffusion",
    "flux1": "Flux.1",
    "flux2": "Flux.2",
    "chroma": "Chroma",
    "auraflow": "AuraFlow",
    "pixart": "PixArt",
    "hunyuan-dit": "Hunyuan DiT",
    "hunyuan-video": "Hunyuan Video",
    "mochi": "Mochi",
    "ltxv": "LTX Video",
    "lumina2": "Lumina 2",
    "wan": "Wan",
    "qwen-image": "Qwen Image",
    "hidream": "HiDream",
    "cosmos": "Cosmos / Anima",
    "clip-l": "CLIP-L",
    "clip-g": "CLIP-G",
    "clip-h": "CLIP-H",
    "t5": "T5",
    "llm": "LLM text encoder",
    "other": "Other",
}


_BASE_ALIASES: list[tuple[str, str]] = [
    # Checked in order; the first substring found in the lowercased text wins.
    ("sdxl refiner", "sdxl-refiner"),
    ("xl", "sdxl"),
    ("pony", "sdxl"),
    ("illustrious", "sdxl"),
    ("noobai", "sdxl"),
    ("playground v2.5", "sdxl"),
    ("sd 1", "sd1"),
    ("sd1", "sd1"),
    ("sd 2", "sd2"),
    ("sd2", "sd2"),
    ("sd 3", "sd3"),
    ("sd3", "sd3"),
    ("flux.2", "flux2"),
    ("flux2", "flux2"),
    ("flux", "flux1"),
    ("chroma", "chroma"),
    ("aura", "auraflow"),
    ("pixart", "pixart"),
    ("hunyuan video", "hunyuan-video"),
    ("hunyuan", "hunyuan-dit"),
    ("mochi", "mochi"),
    ("ltx", "ltxv"),
    ("lumina", "lumina2"),
    ("wan", "wan"),
    ("qwen", "qwen-image"),
    ("hidream", "hidream"),
    ("cascade", "stable-cascade"),
    ("svd", "svd"),
    ("anima", "cosmos"),
    ("cosmos", "cosmos"),
]

_KIND_ALIASES = {
    "checkpoint": "checkpoint",
    "lora": "lora",
    "locon": "lora",
    "lycoris": "lora",
    "dora": "lora",
    "textualinversion": "embedding",
    "embedding": "embedding",
    "hypernetwork": "hypernetwork",
    "vae": "vae",
    "controlnet": "controlnet",
    "upscaler": "upscaler",
    "text_encoder": "text_encoder",
    "diffusion_model": "diffusion_model",
}


def normalize_base_model(text: str | None) -> str | None:
    """Map a free-text base model, such as Civitai's ``SDXL 1.0`` or ``Pony``, onto a base id."""
    if not text:
        return None
    lowered = text.strip().lower()
    if lowered in BASE_MODELS:
        return lowered
    for needle, base in _BASE_ALIASES:
        if needle in lowered:
            return base
    return None


def normalize_kind(text: str | None) -> str | None:
    """Map a source's model type, such as Civitai's ``LORA`` or ``TextualInversion``, onto a kind."""
    if not text:
        return None
    return _KIND_ALIASES.get(text.strip().lower().replace(" ", ""))


# Kinds that detection can tell apart. A folder or sidecar kind outside this set is never flagged.
DETECTABLE_KINDS = frozenset({"checkpoint", "diffusion_model", "lora", "vae", "text_encoder", "controlnet", "embedding", "upscaler", "diffusers"})


def kinds_compatible(a: str, b: str) -> bool:
    groups = [{"checkpoint", "diffusion_model", "diffusers"}]
    return a == b or any(a in g and b in g for g in groups)


class DetectionResult(Record):
    kind: ModelKind = "unknown"
    base_model: str | None = None
    prediction_type: str | None = None
    confidence: float = 0.0
    rule_id: str | None = None
    kind_rule: str | None = None
    format: str | None = None
    error: str | None = None
