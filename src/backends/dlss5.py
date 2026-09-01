import os
from pathlib import Path
from .base import Backend, BackendStatus
class DLSS5Backend(Backend):
    def __init__(self):
        self.runtime = Path(os.environ["DLSS5_RUNTIME_DIR"]) if os.environ.get("DLSS5_RUNTIME_DIR") else Path(__file__).resolve().parents[2]/"runtime"
        self.reason = "No verified proprietary DLSS5 runtime configured"
        self.available = False
        if self.runtime.is_dir() and any(self.runtime.glob("*.dll")):
            self.reason = "DLLs found, but provenance/signature approval is required in the local audit manifest"
    def status(self): return BackendStatus("DLSS 5", self.available, "AVAILABLE" if self.available else "UNAVAILABLE", self.reason)
    def process(self, *args, **kwargs): raise RuntimeError("DLSS 5 unavailable: " + self.reason)
