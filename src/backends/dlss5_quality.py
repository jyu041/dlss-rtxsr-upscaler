"""Experimental DLSS5 quality/composition helpers.

The helpers in this module are runtime-agnostic. They operate on source and
Neural Rendering RGBA frames so the same validation logic can be shared by
the v3 and isolated v10 application paths without changing either runtime's
native ABI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

import cv2
import numpy as np


AUTO_WORKING_SCALE = "auto"
SUPPORTED_AUTO_WORKING_SCALES = (1.0, 0.875, 0.75, 2.0 / 3.0, 0.5)


def resolve_working_scale(
    requested: float | str,
    width: int,
    height: int,
    *,
    target_pixels: int = 1280 * 720,
) -> float:
    """Resolve a fixed or automatic NR working scale.

    Auto keeps the highest supported scale whose working pixel count is at or
    below target_pixels. If even the minimum scale is above the target, the
    minimum scale is used. This makes the automatic decision deterministic for
    a whole session/scene instead of oscillating frame-by-frame.
    """
    if isinstance(requested, str):
        if requested.strip().lower() != AUTO_WORKING_SCALE:
            raise ValueError("working scale must be a supported number or 'auto'")
        if width <= 0 or height <= 0 or target_pixels <= 0:
            raise ValueError("working-scale geometry and target_pixels must be positive")
        native_pixels = int(width) * int(height)
        for scale in SUPPORTED_AUTO_WORKING_SCALES:
            if native_pixels * scale * scale <= target_pixels:
                return scale
        return SUPPORTED_AUTO_WORKING_SCALES[-1]
    value = float(requested)
    if not math.isfinite(value):
        raise ValueError("working scale must be finite")
    if not any(math.isclose(value, item, rel_tol=0.0, abs_tol=1e-9) for item in SUPPORTED_AUTO_WORKING_SCALES):
        raise ValueError("unsupported working scale")
    return next(item for item in SUPPORTED_AUTO_WORKING_SCALES if math.isclose(value, item, rel_tol=0.0, abs_tol=1e-9))


def _rgba(frame: np.ndarray) -> np.ndarray:
    value = np.asarray(frame, dtype=np.uint8)
    if value.ndim != 3 or value.shape[2] != 4:
        raise ValueError("DLSS5 quality composition requires an RGBA uint8 frame")
    return np.ascontiguousarray(value)


def _source_at_output_size(source_rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    source = _rgba(source_rgba)
    if source.shape[:2] == (height, width):
        return source
    return np.ascontiguousarray(
        cv2.resize(source, (width, height), interpolation=cv2.INTER_LANCZOS4)
    )


def _tone_color_compose(
    source_rgba: np.ndarray,
    neural_rgba: np.ndarray,
    *,
    color_strength: float,
    tone_preservation: float,
) -> np.ndarray:
    """Control neural chroma and broad tone independently of structural detail."""
    if not 0.0 <= float(color_strength) <= 1.0:
        raise ValueError("color_strength must be in [0, 1]")
    if not 0.0 <= float(tone_preservation) <= 1.0:
        raise ValueError("tone_preservation must be in [0, 1]")

    neural = _rgba(neural_rgba)
    source = _source_at_output_size(source_rgba, neural.shape[1], neural.shape[0])
    if color_strength == 1.0 and tone_preservation == 0.0:
        return neural.copy()

    source_ycc = cv2.cvtColor(source[..., :3].astype(np.float32), cv2.COLOR_RGB2YCrCb)
    neural_ycc = cv2.cvtColor(neural[..., :3].astype(np.float32), cv2.COLOR_RGB2YCrCb)
    residual = neural_ycc - source_ycc

    if tone_preservation:
        sigma = max(1.0, min(neural.shape[0], neural.shape[1]) / 240.0)
        broad = cv2.GaussianBlur(residual[..., 0], (0, 0), sigmaX=sigma, sigmaY=sigma)
        residual[..., 0] -= float(tone_preservation) * broad
    residual[..., 1:] *= float(color_strength)

    composed_ycc = source_ycc + residual
    rgb = cv2.cvtColor(composed_ycc, cv2.COLOR_YCrCb2RGB)
    rgb = np.rint(rgb).clip(0.0, 255.0).astype(np.uint8)
    return np.ascontiguousarray(np.dstack((rgb, source[..., 3])))


@dataclass
class QualityTelemetry:
    compose_ms: float
    temporal_flow_ms: float
    temporal_blend_ms: float
    shimmer_suppression: float
    color_strength: float
    tone_preservation: float
    history_reset: bool


class TemporalResidualStabilizer:
    """Motion-compensated temporal stabilization of the neural residual.

    The source frame always remains the anchor. Only neural-source is
    accumulated, which avoids smearing source motion the way whole-frame
    temporal averaging can.
    """

    def __init__(
        self,
        *,
        shimmer_suppression: float = 0.0,
        color_strength: float = 1.0,
        tone_preservation: float = 0.0,
        flow_scale: float = 0.25,
    ) -> None:
        if not 0.0 <= float(shimmer_suppression) <= 1.0:
            raise ValueError("shimmer_suppression must be in [0, 1]")
        if not 0.0 <= float(color_strength) <= 1.0:
            raise ValueError("color_strength must be in [0, 1]")
        if not 0.0 <= float(tone_preservation) <= 1.0:
            raise ValueError("tone_preservation must be in [0, 1]")
        if not 0.1 <= float(flow_scale) <= 1.0:
            raise ValueError("flow_scale must be in [0.1, 1.0]")
        self.shimmer_suppression = float(shimmer_suppression)
        self.color_strength = float(color_strength)
        self.tone_preservation = float(tone_preservation)
        self.flow_scale = float(flow_scale)
        self._previous_source: np.ndarray | None = None
        self._stable_residual: np.ndarray | None = None

    def reset(self) -> None:
        self._previous_source = None
        self._stable_residual = None

    def _warp_history(self, current_source: np.ndarray) -> tuple[np.ndarray | None, float]:
        if self._previous_source is None or self._stable_residual is None:
            return None, 0.0
        started = time.perf_counter()
        height, width = current_source.shape[:2]
        flow_width = max(32, int(round(width * self.flow_scale)))
        flow_height = max(32, int(round(height * self.flow_scale)))
        current_small = cv2.resize(current_source[..., :3], (flow_width, flow_height), interpolation=cv2.INTER_AREA)
        previous_small = cv2.resize(self._previous_source[..., :3], (flow_width, flow_height), interpolation=cv2.INTER_AREA)
        current_gray = cv2.cvtColor(current_small, cv2.COLOR_RGB2GRAY)
        previous_gray = cv2.cvtColor(previous_small, cv2.COLOR_RGB2GRAY)

        flow = cv2.calcOpticalFlowFarneback(
            current_gray,
            previous_gray,
            None,
            0.5,
            3,
            15,
            3,
            5,
            1.1,
            0,
        )
        flow = cv2.resize(flow, (width, height), interpolation=cv2.INTER_LINEAR)
        flow[..., 0] *= width / flow_width
        flow[..., 1] *= height / flow_height
        grid_x, grid_y = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )
        warped = cv2.remap(
            self._stable_residual,
            grid_x + flow[..., 0],
            grid_y + flow[..., 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return warped, (time.perf_counter() - started) * 1000.0

    def compose(
        self,
        source_rgba: np.ndarray,
        neural_rgba: np.ndarray,
        *,
        reset: bool = False,
    ) -> tuple[np.ndarray, QualityTelemetry]:
        started = time.perf_counter()
        neural = _rgba(neural_rgba)
        source = _source_at_output_size(source_rgba, neural.shape[1], neural.shape[0])
        if reset:
            self.reset()

        current_residual = (
            neural[..., :3].astype(np.float32) - source[..., :3].astype(np.float32)
        )
        flow_ms = 0.0
        blend_started = time.perf_counter()
        if self.shimmer_suppression > 0.0:
            warped, flow_ms = self._warp_history(source)
            if warped is not None:
                history_weight = min(0.95, self.shimmer_suppression)
                current_residual = (
                    current_residual * (1.0 - history_weight)
                    + warped * history_weight
                )
        blend_ms = (time.perf_counter() - blend_started) * 1000.0

        stabilized = source.copy()
        stabilized[..., :3] = np.rint(
            source[..., :3].astype(np.float32) + current_residual
        ).clip(0.0, 255.0).astype(np.uint8)

        final = _tone_color_compose(
            source,
            stabilized,
            color_strength=self.color_strength,
            tone_preservation=self.tone_preservation,
        )

        self._previous_source = source.copy()
        self._stable_residual = current_residual.copy()
        telemetry = QualityTelemetry(
            compose_ms=(time.perf_counter() - started) * 1000.0,
            temporal_flow_ms=flow_ms,
            temporal_blend_ms=blend_ms,
            shimmer_suppression=self.shimmer_suppression,
            color_strength=self.color_strength,
            tone_preservation=self.tone_preservation,
            history_reset=bool(reset),
        )
        return final, telemetry
