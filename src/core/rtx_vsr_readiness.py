"""Static and bounded process-isolated RTX VSR readiness checks."""
from __future__ import annotations

import json
import platform
import queue
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional

EXPECTED_PACKAGE = "nvidia-vfx"
EXPECTED_VERSION = "0.1.0.1"
EXPECTED_SDK_VERSION = "1.2.0"
REQUIRED_QUALITIES = ("LOW", "MEDIUM", "HIGH", "ULTRA")
REQUIRED_MODE_PREFIXES = ("", "HIGHBITRATE_", "DEBLUR_", "DENOISE_")


@dataclass(frozen=True)
class VSRReadiness:
    state: str
    available: bool
    reason: str
    version: Optional[str] = None
    sdk_version: Optional[str] = None
    gpu_probe: Optional[dict] = None

    def as_dict(self):
        return asdict(self)


def inspect_api(module=None) -> VSRReadiness:
    """Inspect package/API shape without invoking native GPU code."""
    if module is None:
        # Keep the native extension out of the WebUI process.  This bounded
        # child performs import and enum inspection only; GPU probing remains
        # a separate explicit operation.
        try:
            completed = subprocess.run([sys.executable, "-u", "-c", _STATIC_CODE], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
            if completed.returncode:
                return VSRReadiness("UNAVAILABLE", False, completed.stderr.strip() or "static child inspection failed")
            data = json.loads(completed.stdout)
            module = type("StaticModule", (), {
                "__version__": data.get("version"),
                "get_sdk_version": staticmethod(lambda: data.get("sdk_version")),
                "VideoSuperRes": type("VideoSuperRes", (), {"QualityLevel": type("QualityLevel", (), {name: name for name in data.get("qualities", [])})}),
            })
        except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
            return VSRReadiness("UNAVAILABLE", False, f"bounded static nvidia-vfx inspection failed: {exc}")
    try:
        if module is None:
            import nvvfx as module
        version = str(getattr(module, "__version__", "unknown"))
        sdk_version = str(module.get_sdk_version()) if hasattr(module, "get_sdk_version") else None
        quality = getattr(getattr(module, "VideoSuperRes", None), "QualityLevel", None)
        if quality is None:
            return VSRReadiness("UNSUPPORTED API", False, "VideoSuperRes.QualityLevel is missing", version, sdk_version)
        missing = [prefix + quality_name for prefix in REQUIRED_MODE_PREFIXES for quality_name in REQUIRED_QUALITIES if not hasattr(quality, prefix + quality_name)]
        if missing:
            return VSRReadiness("UNSUPPORTED API", False, "Missing quality/mode values: " + ", ".join(missing), version, sdk_version)
        if version != EXPECTED_VERSION or sdk_version != EXPECTED_SDK_VERSION:
            return VSRReadiness("UNVALIDATED PACKAGE", False, f"Package identity is {version}/{sdk_version}; expected {EXPECTED_VERSION}/{EXPECTED_SDK_VERSION}", version, sdk_version)
        reason = "nvidia-vfx package and required VideoSuperRes API are present"
        return VSRReadiness("STATICALLY READY", True, reason, version, sdk_version)
    except Exception as exc:
        return VSRReadiness("UNAVAILABLE", False, f"nvidia-vfx import/API inspection failed: {exc}")


_STATIC_CODE = r'''
import json
import nvvfx
q = nvvfx.VideoSuperRes.QualityLevel
print(json.dumps({"version": str(getattr(nvvfx, "__version__", "unknown")), "sdk_version": str(nvvfx.get_sdk_version()) if hasattr(nvvfx, "get_sdk_version") else None, "qualities": [x for x in dir(q) if not x.startswith("_")]}, sort_keys=True))
'''


_PROBE_CODE = r'''
import json, sys
print("HEARTBEAT import", flush=True)
import torch
print("HEARTBEAT torch", flush=True)
if not torch.cuda.is_available(): raise RuntimeError("CUDA is unavailable")
import nvvfx
print("HEARTBEAT nvvfx", flush=True)
level = getattr(nvvfx.VideoSuperRes.QualityLevel, sys.argv[1])
frame = torch.zeros((3, 64, 64), device="cuda", dtype=torch.float32)
print("HEARTBEAT before_load", flush=True)
with nvvfx.VideoSuperRes(level) as effect:
    effect.output_width, effect.output_height = 128, 128
    effect.load()
    print("HEARTBEAT loaded", flush=True)
    result = effect.run(frame).image
    owned = torch.from_dlpack(result).clone()
    del result
    torch.cuda.synchronize()
    print(json.dumps({"shape": list(owned.shape), "finite": bool(torch.isfinite(owned).all().item())}), flush=True)
print("HEARTBEAT complete", flush=True)
'''


def probe_gpu(quality="LOW", timeout_seconds=30.0, heartbeat: Optional[Callable[[str], None]] = None, popen=subprocess.Popen):
    """Run one tiny native operation with a hard process timeout."""
    if platform.system() != "Windows":
        return {"state": "UNAVAILABLE", "reason": "RTX VSR validation requires Windows"}
    if quality not in REQUIRED_QUALITIES:
        raise ValueError(f"Unsupported probe quality: {quality}")
    process = popen([sys.executable, "-u", "-c", _PROBE_CODE, quality], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    lines = []
    output = queue.Queue()
    def read_output():
        try:
            for line in process.stdout or ():
                output.put(line)
        finally:
            output.put(None)
    threading.Thread(target=read_output, name="rtx-vsr-probe-reader", daemon=True).start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=min(.25, max(.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if line is not None:
                line = line.rstrip()
                lines.append(line)
                if heartbeat:
                    heartbeat(line)
                if line.startswith("{"):
                    result = json.loads(line)
                    result.update({"state": "GPU VALIDATED", "quality": quality, "heartbeats": lines})
                    return result
            elif process.poll() is not None:
                break
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
            return {"state": "BROKEN", "reason": f"GPU probe timed out after {timeout_seconds:.1f}s", "quality": quality, "heartbeats": lines}
        return {"state": "BROKEN", "reason": f"GPU probe exited with code {process.returncode}", "quality": quality, "heartbeats": lines}
    finally:
        if process.poll() is None:
            process.kill()
        if process.stdout:
            process.stdout.close()


def assess(timeout_seconds=30.0, heartbeat=None):
    static = inspect_api()
    if not static.available:
        return static
    result = probe_gpu(timeout_seconds=timeout_seconds, heartbeat=heartbeat)
    if result.get("state") != "GPU VALIDATED":
        return VSRReadiness("BROKEN", False, result.get("reason", "GPU probe failed"), static.version, static.sdk_version, result)
    return VSRReadiness("GPU VALIDATED", True, "bounded synthetic CUDA operation completed", static.version, static.sdk_version, result)
