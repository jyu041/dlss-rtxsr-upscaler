"""CPU-side helpers for experimental reduced-resolution DLSS5 NR."""

from __future__ import annotations

import math

import cv2
import numpy as np

SUPPORTED_NR_WORKING_SCALES = (1.0, 0.75, 2.0 / 3.0, 0.5)


def validate_nr_working_scale(scale: float) -> float:
    value = float(scale)
    if not math.isfinite(value) or not any(math.isclose(value, allowed, rel_tol=0.0, abs_tol=1e-9) for allowed in SUPPORTED_NR_WORKING_SCALES):
        raise ValueError("Unsupported nr_working_scale. Choose 1.0, 0.75, 0.6666666667, or 0.5.")
    return next(allowed for allowed in SUPPORTED_NR_WORKING_SCALES if math.isclose(value, allowed, rel_tol=0.0, abs_tol=1e-9))


def compute_working_dimensions(native_width: int, native_height: int, nr_working_scale: float) -> tuple[int, int]:
    scale = validate_nr_working_scale(nr_working_scale)
    width, height = int(native_width), int(native_height)
    if width <= 0 or height <= 0:
        raise ValueError("Native dimensions must be positive")
    if scale == 1.0:
        return width, height
    return max(2, int(math.floor(width * scale / 2 + 0.5) * 2)), max(2, int(math.floor(height * scale / 2 + 0.5) * 2))


def downsample_for_nr(native_rgba: np.ndarray, working_width: int, working_height: int) -> np.ndarray:
    frame = np.asarray(native_rgba, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[2] != 4:
        raise ValueError("Reduced DLSS5 processing requires an RGBA frame")
    if frame.shape[:2] == (working_height, working_width):
        return np.ascontiguousarray(frame)
    return np.ascontiguousarray(cv2.resize(frame, (working_width, working_height), interpolation=cv2.INTER_AREA))


def residual_recompose(native_rgba: np.ndarray, working_source: np.ndarray, working_nr: np.ndarray) -> np.ndarray:
    native = np.asarray(native_rgba, dtype=np.uint8)
    source = np.asarray(working_source, dtype=np.uint8)
    nr = np.asarray(working_nr, dtype=np.uint8)
    if native.ndim != 3 or source.shape != nr.shape or source.ndim != 3 or source.shape[2] < 3 or native.shape[2] != 4:
        raise ValueError("Residual composition requires native RGBA and equal working RGB/RGBA frames")
    residual = nr[..., :3].astype(np.float32) - source[..., :3].astype(np.float32)
    residual = cv2.resize(residual, (native.shape[1], native.shape[0]), interpolation=cv2.INTER_LINEAR)
    result = np.rint(native[..., :3].astype(np.float32) + residual).clip(0.0, 255.0).astype(np.uint8)
    return np.ascontiguousarray(np.dstack((result, native[..., 3])))
