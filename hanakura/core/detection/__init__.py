"""Model type detection from tensor names and shapes."""

from hanakura.core.detection.models import BASE_MODELS, MODEL_KINDS, DetectionResult
from hanakura.core.detection.service import DetectionService

__all__ = ["BASE_MODELS", "MODEL_KINDS", "DetectionResult", "DetectionService"]
