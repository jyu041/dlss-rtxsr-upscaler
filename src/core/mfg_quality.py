"""Deterministic image-quality metrics for withheld-frame MFG evaluation.

This module is renderer-independent.  It compares generated RGB(A) frames with
real reference frames that were withheld from a higher-frame-rate source.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Iterable

import numpy as np


def _rgb(frame: np.ndarray) -> np.ndarray:
    value = np.asarray(frame)
    if value.ndim != 3 or value.shape[2] < 3:
        raise ValueError("frame must be HxWx3 or HxWx4")
    if value.dtype != np.uint8:
        raise ValueError("frame dtype must be uint8")
    return value[..., :3].astype(np.float64)


def psnr_db(reference: np.ndarray, generated: np.ndarray) -> float | None:
    left = _rgb(reference)
    right = _rgb(generated)
    if left.shape != right.shape:
        raise ValueError("reference and generated frames must have equal RGB shapes")
    mse = float(np.mean(np.square(left - right)))
    if mse == 0.0:
        return None
    return float(10.0 * math.log10((255.0 * 255.0) / mse))


def _ssim_channel(left: np.ndarray, right: np.ndarray) -> float:
    # Global per-channel SSIM.  This intentionally avoids optional scipy/skimage
    # dependencies so CI and development evidence use the exact same formula.
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    mu_left = float(np.mean(left))
    mu_right = float(np.mean(right))
    centered_left = left - mu_left
    centered_right = right - mu_right
    var_left = float(np.mean(centered_left * centered_left))
    var_right = float(np.mean(centered_right * centered_right))
    covariance = float(np.mean(centered_left * centered_right))
    numerator = (2.0 * mu_left * mu_right + c1) * (2.0 * covariance + c2)
    denominator = (
        (mu_left * mu_left + mu_right * mu_right + c1)
        * (var_left + var_right + c2)
    )
    return float(numerator / denominator) if denominator else 1.0


def ssim_rgb(reference: np.ndarray, generated: np.ndarray) -> float:
    left = _rgb(reference)
    right = _rgb(generated)
    if left.shape != right.shape:
        raise ValueError("reference and generated frames must have equal RGB shapes")
    return float(np.mean([
        _ssim_channel(left[..., channel], right[..., channel])
        for channel in range(3)
    ]))


def frame_metrics(reference: np.ndarray, generated: np.ndarray) -> dict[str, object]:
    left = _rgb(reference)
    right = _rgb(generated)
    if left.shape != right.shape:
        raise ValueError("reference and generated frames must have equal RGB shapes")
    difference = left - right
    absolute = np.abs(difference)
    mse = float(np.mean(np.square(difference)))
    return {
        "mae": float(np.mean(absolute)),
        "rmse": float(math.sqrt(mse)),
        "psnr_db": None if mse == 0.0 else float(10.0 * math.log10((255.0 * 255.0) / mse)),
        "ssim_rgb": ssim_rgb(reference, generated),
        "identical": bool(np.array_equal(left, right)),
    }


def withheld_groups(frame_count: int, multiplier: int) -> list[dict[str, object]]:
    """Plan high-FPS ground-truth groups for an MFG multiplier.

    For multiplier M, anchors are M source frames apart.  Frames between them
    become references for generated indices 1..M-1.
    """
    if multiplier not in (2, 3, 4):
        raise ValueError("multiplier must be 2, 3, or 4")
    if frame_count < 0:
        raise ValueError("frame_count must be non-negative")

    groups: list[dict[str, object]] = []
    group = 0
    start = 0
    while start + multiplier < frame_count:
        groups.append({
            "group": group,
            "left_anchor": start,
            "right_anchor": start + multiplier,
            "withheld": tuple(range(start + 1, start + multiplier)),
        })
        group += 1
        start += multiplier
    return groups


def summarize_samples(samples: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = list(samples)
    by_index: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        index = int(row["generated_index"])
        if index not in (1, 2, 3):
            raise ValueError("generated_index must be 1, 2, or 3")
        by_index[index].append(row)

    def aggregate(group: list[dict[str, object]]) -> dict[str, object]:
        if not group:
            return {"count": 0}
        psnr_values = [
            float(row["psnr_db"])
            for row in group
            if row.get("psnr_db") is not None
        ]
        return {
            "count": len(group),
            "mean_mae": float(np.mean([float(row["mae"]) for row in group])),
            "mean_rmse": float(np.mean([float(row["rmse"]) for row in group])),
            "mean_psnr_db": float(np.mean(psnr_values)) if psnr_values else None,
            "mean_ssim_rgb": float(np.mean([float(row["ssim_rgb"]) for row in group])),
            "identical_count": sum(bool(row.get("identical")) for row in group),
        }

    return {
        "count": len(rows),
        "overall": aggregate(rows),
        "by_generated_index": {
            str(index): aggregate(by_index[index])
            for index in sorted(by_index)
        },
    }
