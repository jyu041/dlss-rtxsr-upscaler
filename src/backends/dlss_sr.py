"""Honest capability gate for standalone DLSS Super Resolution.

The approved community worker exposes DLSS/DLAA as the input path to its
DLSS5 Neural Rendering pass, but exposes no switch that disables Feature 18.
Keeping this backend explicit prevents a resize or RTX VSR fallback from being
reported as standalone DLSS SR.
"""

from __future__ import annotations

from .base import Backend, BackendStatus
from .dlss5 import DLSS5Backend


class DLSSSRBackend(Backend):
    def __init__(self):
        self._runtime = DLSS5Backend()
        self.available = False
        self.reason = (
            "Standalone DLSS SR is not exposed by approved worker protocol v4; "
            "the worker always runs the DLSS5 Feature-18 addon"
        )

    def status(self):
        base = self._runtime.status()
        if base.state in {"NO RUNTIME", "STAGED - NOT APPROVED", "HASH MISMATCH"}:
            return BackendStatus("DLSS SR", False, base.state, base.reason)
        return BackendStatus("DLSS SR", False, "FAILED SELFTEST", self.reason)

    def validate_runtime(self):
        details = self._runtime.validate_runtime()
        details["standalone_sr_supported"] = False
        details["reason"] = self.reason
        return details

    def selftest(self):
        raise RuntimeError(
            "Standalone DLSS SR self-test not run: protocol v4 has no SR-only request "
            "and executing the worker would exercise DLSS5 Feature 18 instead."
        )

    def process_frame(self, *args, **kwargs):
        raise RuntimeError("DLSS SR unavailable: " + self.reason)

    def process_video(self, *args, **kwargs):
        raise RuntimeError("DLSS SR unavailable: " + self.reason)

    def close(self):
        return None
