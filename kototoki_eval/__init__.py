"""Offline, text-first STT evaluation independent of inference engines."""

from .scoring import evaluate, micro_summary
from .schema import from_segments, normalize

__all__ = ["evaluate", "micro_summary", "from_segments", "normalize"]
