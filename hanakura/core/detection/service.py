"""Detection: header reading, kind classification and the rule table, with a file index cache."""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from hanakura.core.db import Database
from hanakura.core.detection.header import HeaderError, ModelHeader, read_header
from hanakura.core.detection.kinds import classify_kind
from hanakura.core.detection.models import DetectionResult
from hanakura.core.detection.rules import RuleTable

logger = logging.getLogger(__name__)

HEADER_EXTENSIONS = (".safetensors", ".sft", ".gguf")
METADATA_KEYS_KEPT = (
    "modelspec.architecture",
    "modelspec.title",
    "modelspec.author",
    "modelspec.description",
    "modelspec.trigger_phrase",
    "modelspec.prediction_type",
    "ss_base_model_version",
    "ss_network_module",
    "ss_output_name",
    "ss_sd_model_name",
    "general.architecture",
    "general.name",
)

# Metadata written by trainers, used when the rule table finds no base model.
_MODELSPEC_PREFIXES = {
    "stable-diffusion-xl-v1-refiner": "sdxl-refiner",
    "stable-diffusion-xl-v1": "sdxl",
    "stable-diffusion-v1": "sd1",
    "stable-diffusion-v2": "sd2",
    "stable-diffusion-3": "sd3",
    "flux-1": "flux1",
    "flux.1": "flux1",
    "chroma": "chroma",
    "anima": "cosmos",
}
_SS_BASE = {"sdxl": "sdxl", "sd_v1": "sd1", "sd_v2": "sd2", "flux1": "flux1", "sd3": "sd3", "chroma": "chroma", "anima": "cosmos"}
_GGUF_ARCH = {
    "flux": "flux1",
    "sd1": "sd1",
    "sdxl": "sdxl",
    "sd3": "sd3",
    "aura": "auraflow",
    "hidream": "hidream",
    "cosmos": "other",
    "ltxv": "ltxv",
    "hyvid": "hunyuan-video",
    "wan": "wan",
    "lumina2": "lumina2",
    "qwen_image": "qwen-image",
    "chroma": "chroma",
}
_GGUF_TEXT_ENCODERS = {"t5": "t5", "t5encoder": "t5", "llama": "llm", "qwen2": "llm", "qwen2vl": "llm", "qwen3": "llm", "gemma2": "llm", "gemma3": "llm"}
_DIFFUSERS_PIPELINES = {
    "StableDiffusionPipeline": "sd1",
    "StableDiffusionXLPipeline": "sdxl",
    "StableDiffusionXLImg2ImgPipeline": "sdxl-refiner",
    "StableDiffusion3Pipeline": "sd3",
    "FluxPipeline": "flux1",
    "Flux2Pipeline": "flux2",
    "PixArtAlphaPipeline": "pixart",
    "PixArtSigmaPipeline": "pixart",
    "AuraFlowPipeline": "auraflow",
    "HunyuanDiTPipeline": "hunyuan-dit",
    "WanPipeline": "wan",
    "QwenImagePipeline": "qwen-image",
    "Lumina2Pipeline": "lumina2",
    "StableCascadeCombinedPipeline": "stable-cascade",
    "StableVideoDiffusionPipeline": "svd",
}


def _base_from_metadata(metadata: dict[str, Any]) -> str | None:
    arch = str(metadata.get("modelspec.architecture") or "").lower()
    for prefix, base in _MODELSPEC_PREFIXES.items():
        if arch.startswith(prefix):
            return base
    ss = str(metadata.get("ss_base_model_version") or "").lower()
    for prefix, base in _SS_BASE.items():
        if ss.startswith(prefix):
            return base
    return None


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class DetectionService:
    def __init__(self, db: Database, rules: RuleTable | None = None) -> None:
        self.db = db
        self.rules = rules or RuleTable.load_default()

    # -- pure detection ---------------------------------------------------------

    def detect_header(self, header: ModelHeader) -> DetectionResult:
        tensors = header.tensors
        kind = classify_kind(tensors.keys())
        if kind is None:
            if header.format == "gguf":
                return self._detect_gguf_metadata(header)
            return DetectionResult(kind="unknown", format=header.format)
        match = self.rules.match(kind.kind, tensors, kind.prefix)
        if match is not None:
            return DetectionResult(
                kind=kind.kind,
                base_model=match.rule.base_model,
                prediction_type=match.prediction_type,
                confidence=round(min(kind.confidence, match.rule.confidence), 3),
                rule_id=match.rule.id,
                kind_rule=kind.rule,
                format=header.format,
            )
        base = _base_from_metadata(header.metadata)
        if base is None and header.format == "gguf":
            base = _GGUF_ARCH.get(str(header.metadata.get("general.architecture", "")).lower())
        return DetectionResult(
            kind=kind.kind,
            base_model=base,
            confidence=round(kind.confidence * (0.6 if base else 1.0), 3),
            rule_id="metadata" if base else None,
            kind_rule=kind.rule,
            format=header.format,
        )

    @staticmethod
    def _detect_gguf_metadata(header: ModelHeader) -> DetectionResult:
        arch = str(header.metadata.get("general.architecture", "")).lower()
        if arch in _GGUF_ARCH:
            return DetectionResult(kind="diffusion_model", base_model=_GGUF_ARCH[arch], confidence=0.6, rule_id="gguf-architecture", format="gguf")
        if arch in _GGUF_TEXT_ENCODERS:
            return DetectionResult(kind="text_encoder", base_model=_GGUF_TEXT_ENCODERS[arch], confidence=0.6, rule_id="gguf-architecture", format="gguf")
        return DetectionResult(kind="unknown", format="gguf")

    def detect_diffusers(self, folder: Path) -> DetectionResult:
        try:
            index = json.loads((folder / "model_index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return DetectionResult(kind="diffusers", error=str(e), format="diffusers")
        class_name = str(index.get("_class_name", ""))
        base = _DIFFUSERS_PIPELINES.get(class_name)
        return DetectionResult(kind="diffusers", base_model=base, confidence=0.9 if base else 0.5, rule_id=f"diffusers:{class_name}" if class_name else None, format="diffusers")

    def detect_path(self, path: Path) -> tuple[DetectionResult, dict[str, Any]]:
        """Detect a file or diffusers folder without the cache. Returns the result and kept metadata."""
        if path.is_dir():
            return self.detect_diffusers(path), {}
        if path.suffix.lower() not in HEADER_EXTENSIONS:
            # Pickle-based files are never unpickled.
            return DetectionResult(kind="unknown", format=path.suffix.lower().lstrip(".") or None), {}
        try:
            header = read_header(path)
        except (HeaderError, OSError) as e:
            return DetectionResult(kind="unknown", error=str(e)), {}
        kept = {k: v for k, v in header.metadata.items() if k in METADATA_KEYS_KEPT and isinstance(v, (str, int, float, bool))}
        return self.detect_header(header), kept

    # -- cached detection -------------------------------------------------------

    def cached(self, path: Path) -> tuple[DetectionResult, dict[str, Any], str | None] | None:
        """Return the cached result if the file's size and mtime still match."""
        try:
            st = path.stat()
        except OSError:
            return None
        row = self.db.fetchone("SELECT * FROM file_index WHERE path = ?", (str(path),))
        if row is None or (not path.is_dir() and (row["size"] != st.st_size or row["mtime_ns"] != st.st_mtime_ns)):
            return None
        if path.is_dir() and row["mtime_ns"] != st.st_mtime_ns:
            return None
        data = json.loads(row["metadata"] or "{}")
        result = DetectionResult(
            kind=row["kind"] or "unknown",
            base_model=row["base_model"],
            prediction_type=row["prediction_type"],
            confidence=row["confidence"] or 0.0,
            rule_id=row["rule_id"],
            kind_rule=data.pop("_kind_rule", None),
            format=data.pop("_format", None),
            error=data.pop("_error", None),
        )
        return result, data, row["sha256"]

    def detect(self, path: Path, use_cache: bool = True) -> tuple[DetectionResult, dict[str, Any]]:
        if use_cache:
            hit = self.cached(path)
            if hit is not None:
                return hit[0], hit[1]
        result, kept = self.detect_path(path)
        self.store(path, result, kept)
        return result, kept

    def store(self, path: Path, result: DetectionResult, kept: dict[str, Any], sha256: str | None = None) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        size = 0 if path.is_dir() else st.st_size
        extra = {**kept, "_kind_rule": result.kind_rule, "_format": result.format, "_error": result.error}
        existing = self.db.fetchone("SELECT size, mtime_ns, sha256 FROM file_index WHERE path = ?", (str(path),))
        if sha256 is None and existing is not None and existing["size"] == size and existing["mtime_ns"] == st.st_mtime_ns:
            sha256 = existing["sha256"]
        self.db.execute(
            """INSERT INTO file_index(path, size, mtime_ns, sha256, kind, base_model, prediction_type, confidence, rule_id, metadata, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256, kind=excluded.kind,
               base_model=excluded.base_model, prediction_type=excluded.prediction_type, confidence=excluded.confidence, rule_id=excluded.rule_id,
               metadata=excluded.metadata, updated_at=excluded.updated_at""",
            (str(path), size, st.st_mtime_ns, sha256, result.kind, result.base_model, result.prediction_type, result.confidence, result.rule_id, json.dumps(extra)),
        )

    def sha256(self, path: Path) -> str:
        """Return the file's SHA256, computing it once and caching it in the file index."""
        hit = self.cached(path)
        if hit is not None and hit[2]:
            return hit[2]
        digest = sha256_file(path)
        if hit is None:
            result, kept = self.detect_path(path)
        else:
            result, kept = hit[0], hit[1]
        self.store(path, result, kept, sha256=digest)
        return digest

    def forget(self, path: Path) -> None:
        """Drop index rows for a path and anything below it."""
        p = str(path)
        self.db.execute("DELETE FROM file_index WHERE path = ? OR path LIKE ?", (p, p.rstrip(os.sep) + os.sep + "%"))
