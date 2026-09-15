"""Project-owned standalone optical-flow guidance for DLSS SR.

The algorithm mirrors the retained MIT TemporalGuide: OpenCV DIS at a capped,
area-downscaled grayscale resolution, calculating current-to-previous flow and
scaling vectors back to the render dimensions.  The wire protocol uses the
native host's HxWx2 contiguous float32 layout.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(slots=True)
class MotionFrame:
    motion: np.ndarray
    reset: bool
    scene_score: float


class StandaloneDLSSMotion:
    def __init__(self, width: int, height: int, flow_width: int = 640) -> None:
        self.width, self.height = int(width), int(height)
        scale = min(1.0, flow_width / max(1, self.width))
        self.flow_width = max(64, int(round(self.width * scale / 2) * 2))
        self.flow_height = max(64, int(round(self.height * scale / 2) * 2))
        self.previous_gray: np.ndarray | None = None
        self.zero_motion = np.zeros((self.height, self.width, 2), dtype=np.float32)
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        self.dis.setUseSpatialPropagation(True)
        self.dis.setFinestScale(1)

    def _small_gray(self, rgba: np.ndarray) -> np.ndarray:
        rgba = np.asarray(rgba, dtype=np.uint8)
        if rgba.ndim != 3 or rgba.shape[:2] != (self.height, self.width) or rgba.shape[2] not in (3, 4):
            raise ValueError("DLSS SR motion frames must match the configured RGB/RGBA dimensions")
        gray = cv2.cvtColor(rgba, cv2.COLOR_RGB2GRAY if rgba.shape[2] == 3 else cv2.COLOR_RGBA2GRAY)
        return cv2.resize(gray, (self.flow_width, self.flow_height), interpolation=cv2.INTER_AREA)

    def process(self, frame: np.ndarray) -> MotionFrame:
        current = self._small_gray(frame)
        if self.previous_gray is None:
            result = MotionFrame(self.zero_motion.copy(), True, 1.0)
        else:
            score = float(np.mean(cv2.absdiff(current, self.previous_gray))) / 255.0
            reset = score > 0.24
            if reset:
                motion = self.zero_motion.copy()
            else:
                # DIS(current, previous) is the retained current-to-previous
                # convention; X is horizontal and Y is vertical.
                motion = self.dis.calc(current, self.previous_gray, None)
                motion = cv2.resize(motion, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
                motion[..., 0] *= self.width / self.flow_width
                motion[..., 1] *= self.height / self.flow_height
                if not np.isfinite(motion).all():
                    reset = True
                    motion = self.zero_motion.copy()
                else:
                    motion = np.ascontiguousarray(motion.astype(np.float32))
            result = MotionFrame(motion, reset, score)
        self.previous_gray = current
        return result
