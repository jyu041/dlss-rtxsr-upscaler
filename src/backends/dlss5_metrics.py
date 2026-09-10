"""Small, dependency-light evidence metrics for DLSS5 output."""

from __future__ import annotations

import hashlib
import math
from statistics import mean, median, quantiles
from typing import Any

import numpy as np

# These are deliberately permissive uint8-scale indicators, not image-quality goals.
EFFECT_MIN_CHANGED_RATIO = 0.001
EFFECT_MIN_MEAN_ABSOLUTE_DIFFERENCE = 0.25


def effect_metrics(source: np.ndarray, output: np.ndarray) -> dict[str, Any]:
    """Compare RGB pixels and return JSON-safe evidence (alpha is ignored)."""
    source = np.asarray(source, dtype=np.uint8)
    output = np.asarray(output, dtype=np.uint8)
    if source.shape != output.shape or source.ndim != 3 or source.shape[2] < 3:
        raise ValueError("DLSS5 effect comparison requires equal RGB/RGBA frame shapes")
    a = source[..., :3].astype(np.int16)
    b = output[..., :3].astype(np.int16)
    difference = np.abs(a - b)
    changed = np.any(difference != 0, axis=2)
    return {
        "mean_absolute_difference": float(np.mean(difference)),
        "max_absolute_difference": int(np.max(difference)),
        "changed_pixel_count": int(np.count_nonzero(changed)),
        "changed_pixel_ratio": float(np.mean(changed)),
        "rmse": float(np.sqrt(np.mean(np.square(a.astype(np.float32) - b.astype(np.float32))))),
        "input_sha256": hashlib.sha256(source.tobytes()).hexdigest().upper(),
        "output_sha256": hashlib.sha256(output.tobytes()).hexdigest().upper(),
    }


def effect_observed(metrics: dict[str, Any]) -> bool:
    """Conservative diagnostic decision; does not change backend readiness."""
    return (
        float(metrics.get("changed_pixel_ratio", 0)) >= EFFECT_MIN_CHANGED_RATIO
        and float(metrics.get("mean_absolute_difference", 0)) >= EFFECT_MIN_MEAN_ABSOLUTE_DIFFERENCE
    )


def statistics(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean_ms": None, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    p95 = quantiles(values, n=20, method="inclusive")[18] if len(values) > 1 else values[0]
    return {"mean_ms": mean(values), "median_ms": median(values), "p95_ms": p95, "min_ms": min(values), "max_ms": max(values)}
