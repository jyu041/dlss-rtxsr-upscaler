"""Bounded cancellation/recovery validation for Phase 4C4."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backends.dlss_sr import DLSSSRBackend
from src.backends.rtx_vsr import RTXVSRBackend
from src.video.dlss_sr import render_dlss_sr
from src.video.stream import render_vsr


class CancelAfter:
    def __init__(self, checks=2):
        self.checks = checks
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls > self.checks


def main():
    source = Path("runtime/phase4c4_short.mp4")
    vsr = RTXVSRBackend()
    try:
        render_vsr(source, "runtime/dlss-vsr-validation/cancel.mp4", vsr, 2.0, "LOW", "Super Resolution", cancel=CancelAfter())
    except InterruptedError:
        print("VSR CANCEL_PASS", flush=True)
    else:
        raise AssertionError("VSR cancellation unexpectedly completed")
    print("VSR RECOVERY", render_vsr(source, "runtime/dlss-vsr-validation/recovery.mp4", vsr, 2.0, "LOW", "Super Resolution"), flush=True)

    sr = DLSSSRBackend()
    try:
        render_dlss_sr(source, "runtime/dlss-sr-validation/cancel.mkv", sr, "Quality", "K", codec="H.264", cancel=CancelAfter())
    except InterruptedError:
        print("DLSS SR CANCEL_PASS", flush=True)
    else:
        raise AssertionError("DLSS SR cancellation unexpectedly completed")
    print("DLSS SR RECOVERY", render_dlss_sr(source, "runtime/dlss-sr-validation/recovery.mkv", sr, "Quality", "K", codec="H.264"), flush=True)


if __name__ == "__main__":
    main()
