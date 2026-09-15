from .base import Backend, BackendStatus
from src.core.rtx_vsr_readiness import inspect_api

class RTXVSRBackend(Backend):
    """Optional NVIDIA VFX adapter; it never falls back to a generic upscaler."""
    def __init__(self):
        self.nvvfx = None
        try:
            import nvvfx
            self.nvvfx = nvvfx
        except Exception:
            pass
        self._readiness = inspect_api(self.nvvfx) if self.nvvfx else inspect_api()
    def status(self):
        return BackendStatus("RTX VSR", self._readiness.available, self._readiness.state, self._readiness.reason)
    def process_frame(self, frame, output_width, output_height, quality="ULTRA"):
        """Process one HWC float/uint8 torch frame and detach DLPack storage immediately."""
        if not self.nvvfx: raise RuntimeError("RTX VSR unavailable: " + self._readiness.reason)
        import torch
        levels = self.quality_levels()
        with self.nvvfx.VideoSuperRes(levels[quality]) as sr:
            sr.output_width, sr.output_height = int(output_width), int(output_height)
            sr.load()
            source = frame.cuda().permute(2, 0, 1).float().contiguous()
            dlpack_result = sr.run(source).image
            # Materialize an owned tensor before the SDK context and DLPack producer die.
            result = torch.from_dlpack(dlpack_result).movedim(0, 2).contiguous().clone()
            del dlpack_result, source
            if torch.cuda.is_available(): torch.cuda.synchronize()
            return result
    def quality_levels(self):
        q = self.nvvfx.VideoSuperRes.QualityLevel if self.nvvfx else None
        return {name: getattr(q, name) for name in ("LOW", "MEDIUM", "HIGH", "ULTRA")}
    def mode_quality(self, mode, quality):
        if not self.nvvfx: raise RuntimeError("RTX VSR unavailable: " + self._readiness.reason)
        prefix = {"Super Resolution":"", "High Bitrate":"HIGHBITRATE_", "Deblur":"DEBLUR_", "Denoise":"DENOISE_"}.get(mode)
        if prefix is None: raise ValueError("Unknown RTX VSR mode")
        name = prefix + quality
        level = self.nvvfx.VideoSuperRes.QualityLevel
        if not hasattr(level, name): raise ValueError(f"Installed nvvfx does not expose {name}")
        return getattr(level, name)
    def process(self, frames, width, height, quality="ULTRA", cancel=None, progress=None):
        if not self.nvvfx: raise RuntimeError("RTX VSR unavailable: " + self._readiness.reason)
        for index, frame in enumerate(frames):
            if cancel and cancel.is_set(): return
            yield self.process_frame(frame, width, height, quality)
            if progress: progress(index + 1)
