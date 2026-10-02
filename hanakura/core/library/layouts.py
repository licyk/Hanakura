"""Layout presets: which folder under a root holds which kind of model.

Folder names were read from a ComfyUI checkout and a Stable Diffusion WebUI (Forge) install.
Several folder names
can map to one kind (ComfyUI's legacy aliases, the WebUI's LoRA and LyCORIS folders). Each
layout accepts a root at the installation folder or at its ``models`` folder.
"""

from pathlib import Path

_COMFYUI = {
    "checkpoints": "checkpoint",
    "loras": "lora",
    "vae": "vae",
    "text_encoders": "text_encoder",
    "clip": "text_encoder",
    "diffusion_models": "diffusion_model",
    "unet": "diffusion_model",
    "clip_vision": "clip_vision",
    "controlnet": "controlnet",
    "t2i_adapter": "controlnet",
    "upscale_models": "upscaler",
    "latent_upscale_models": "upscaler",
    "embeddings": "embedding",
    "hypernetworks": "hypernetwork",
    "style_models": "style_model",
    "vae_approx": "vae",
    "diffusers": "diffusers",
    "gligen": "gligen",
    "photomaker": "photomaker",
    "model_patches": "model_patch",
    "audio_encoders": "audio_encoder",
}

_SD_WEBUI_MODELS = {
    "Stable-diffusion": "checkpoint",
    "Lora": "lora",
    "LyCORIS": "lora",
    "VAE": "vae",
    "VAE-approx": "vae",
    "text_encoder": "text_encoder",
    "ControlNet": "controlnet",
    "ControlNetPreprocessor": "annotator",
    "hypernetworks": "hypernetwork",
    "ESRGAN": "upscaler",
    "RealESRGAN": "upscaler",
    "DAT": "upscaler",
    "SwinIR": "upscaler",
    "ScuNET": "upscaler",
    "LDSR": "upscaler",
    "BSRGAN": "upscaler",
    "GFPGAN": "face_restore",
    "Codeformer": "face_restore",
    "diffusers": "diffusers",
}


def _with_models_prefix(mapping: dict[str, str]) -> dict[str, str]:
    out = dict(mapping)
    out.update({f"models/{k}": v for k, v in mapping.items()})
    return out


LAYOUTS: dict[str, dict[str, str]] = {
    "comfyui": _with_models_prefix(_COMFYUI),
    # Embeddings sit beside the WebUI's models folder, so the root is the installation folder.
    "sd-webui": {**_with_models_prefix(_SD_WEBUI_MODELS), "embeddings": "embedding"},
    "custom": {},
}

# Preferred folder per kind, first choice first.
_PREFERRED: dict[str, dict[str, list[str]]] = {
    "comfyui": {
        "checkpoint": ["checkpoints"],
        "lora": ["loras"],
        "vae": ["vae"],
        "text_encoder": ["text_encoders", "clip"],
        "diffusion_model": ["diffusion_models", "unet"],
        "controlnet": ["controlnet"],
        "upscaler": ["upscale_models"],
        "embedding": ["embeddings"],
        "hypernetwork": ["hypernetworks"],
        "diffusers": ["diffusers"],
        "clip_vision": ["clip_vision"],
    },
    "sd-webui": {
        "checkpoint": ["models/Stable-diffusion"],
        "diffusion_model": ["models/Stable-diffusion"],
        "lora": ["models/Lora"],
        "vae": ["models/VAE"],
        "text_encoder": ["models/text_encoder"],
        "controlnet": ["models/ControlNet"],
        "upscaler": ["models/ESRGAN"],
        "embedding": ["embeddings"],
        "hypernetwork": ["models/hypernetworks"],
        "diffusers": ["models/diffusers"],
    },
}


def folder_kind(layout: str, rel_path: str) -> str | None:
    """Return the kind a layout expects for ``rel_path`` or its nearest mapped ancestor."""
    mapping = LAYOUTS.get(layout, {})
    if not mapping or not rel_path:
        return None
    parts = rel_path.strip("/").split("/")
    for i in range(len(parts), 0, -1):
        kind = mapping.get("/".join(parts[:i]))
        if kind is not None:
            return kind
    return None


def default_folder(layout: str, root: Path, kind: str) -> str:
    """Return the relative folder where a model of ``kind`` should go in this root, or ``""``."""
    candidates = _PREFERRED.get(layout, {}).get(kind, [])
    if not candidates:
        return ""
    for candidate in candidates:
        if (root / candidate).is_dir():
            return candidate
    first = candidates[0]
    if layout == "comfyui" and (root / "models").is_dir() and not (root / "checkpoints").is_dir():
        # Root points at the ComfyUI installation folder.
        return f"models/{first}"
    if layout == "sd-webui" and first.startswith("models/") and not (root / "models").is_dir() and any((root / n).is_dir() for n in ("Stable-diffusion", "Lora")):
        # Root points at the WebUI's models folder itself.
        return first.split("/", 1)[1]
    return first
