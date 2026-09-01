from .base import Backend, BackendStatus
class RTXVSRBackend(Backend):
    """Thin, optional adapter. It never falls back to a generic upscaler."""
    def __init__(self):
        self.nvvfx = None; self.reason = "nvidia-vfx is not installed"
        try:
            import nvvfx
            self.nvvfx = nvvfx; self.reason = "nvvfx imported; GPU initialization is deferred to the job"
        except Exception as e: self.reason = f"nvvfx unavailable: {e}"
    def status(self): return BackendStatus("RTX VSR", bool(self.nvvfx), "AVAILABLE" if self.nvvfx else "UNAVAILABLE", self.reason)
    def process_frame(self, frame, output_width, output_height, quality="ULTRA"):
        """Process one HWC float/uint8 torch frame and detach DLPack storage immediately."""
        if not self.nvvfx: raise RuntimeError("RTX VSR unavailable: " + self.reason)
        import torch
        levels = {"LOW": self.nvvfx.effects.QualityLevel.LOW, "MEDIUM": self.nvvfx.effects.QualityLevel.MEDIUM, "HIGH": self.nvvfx.effects.QualityLevel.HIGH, "ULTRA": self.nvvfx.effects.QualityLevel.ULTRA}
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
    def process(self, frames, width, height, quality="ULTRA", cancel=None, progress=None):
        if not self.nvvfx: raise RuntimeError("RTX VSR unavailable: " + self.reason)
        for index, frame in enumerate(frames):
            if cancel and cancel.is_set(): return
            yield self.process_frame(frame, width, height, quality)
            if progress: progress(index + 1)
