from .base import Backend, BackendStatus
import numpy as np
from src.core.rtx_vsr_readiness import inspect_api
from src.video.rtx_vsr_worker import RTXVSRSession

class RTXVSRBackend(Backend):
    """Optional NVIDIA VFX adapter; it never falls back to a generic upscaler."""
    def __init__(self):
        # Native nvvfx is loaded only by the supervised worker process.
        self._readiness = inspect_api()
    def status(self):
        return BackendStatus("RTX VSR", self._readiness.available, self._readiness.state, self._readiness.reason)
    def process_frame(self, frame, output_width, output_height, quality="ULTRA"):
        array = np.asarray(frame, dtype=np.uint8)
        session = RTXVSRSession()
        try:
            session.start(array.shape[1], array.shape[0], int(output_width), int(output_height), "Super Resolution", quality)
            return session.process_frame(0, array)
        finally:
            session.close()
    def quality_levels(self):
        return {name: name for name in ("LOW", "MEDIUM", "HIGH", "ULTRA")}
    def mode_quality(self, mode, quality):
        prefix = {"Super Resolution":"", "High Bitrate":"HIGHBITRATE_", "Deblur":"DEBLUR_", "Denoise":"DENOISE_"}.get(mode)
        if prefix is None: raise ValueError("Unknown RTX VSR mode")
        name = prefix + quality
        if quality not in ("LOW", "MEDIUM", "HIGH", "ULTRA"): raise ValueError(f"Unsupported RTX VSR quality: {quality}")
        return name
    def process(self, frames, width, height, quality="ULTRA", cancel=None, progress=None):
        for index, frame in enumerate(frames):
            if cancel and cancel.is_set(): return
            yield self.process_frame(frame, width, height, quality)
            if progress: progress(index + 1)
