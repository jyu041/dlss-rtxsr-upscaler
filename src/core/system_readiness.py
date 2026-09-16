"""Cheap, non-invasive machine capability checks for first-run diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import subprocess

from .process_utils import tool


def _gpu_query() -> dict[str, object]:
    executable = tool("nvidia-smi")
    if not executable:
        return {"state": "MISSING", "detail": "nvidia-smi is unavailable"}
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"state": "TIMEOUT", "detail": "nvidia-smi did not respond within 5 seconds"}
    except OSError as exc:
        return {"state": "BROKEN", "detail": f"nvidia-smi could not launch: {exc}"}
    if result.returncode or not result.stdout.strip():
        return {"state": "BROKEN", "detail": f"nvidia-smi exited with code {result.returncode}"}
    identity = result.stdout.strip()
    match = re.search(r"RTX\s+(\d{2})", identity, re.IGNORECASE)
    return {"state": "READY", "identity": identity, "generation": int(match.group(1)) if match else None}


def _hags() -> dict[str, object]:
    if platform.system() != "Windows":
        return {"state": "NOT_APPLICABLE", "detail": "HAGS is a Windows setting"}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers") as key:
            value, _kind = winreg.QueryValueEx(key, "HwSchMode")
    except (FileNotFoundError, OSError):
        return {"state": "UNKNOWN", "detail": "HAGS registry value is not present"}
    return {"state": "ENABLED" if int(value) == 2 else "DISABLED" if int(value) == 1 else "UNKNOWN", "value": int(value)}


def _nvenc() -> dict[str, object]:
    executable = tool("ffmpeg")
    if not executable:
        return {"state": "MISSING", "encoders": []}
    try:
        result = subprocess.run([executable, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "BROKEN", "encoders": []}
    encoders = [name for name in ("h264_nvenc", "hevc_nvenc", "av1_nvenc") if name in (result.stdout + result.stderr)]
    return {"state": "READY" if result.returncode == 0 and {"h264_nvenc", "hevc_nvenc"}.issubset(encoders) else "INCOMPLETE", "encoders": encoders}


def collect() -> dict[str, object]:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    nvof = system_root / "System32" / "nvofapi64.dll"
    return {
        "os": platform.platform(),
        "gpu": _gpu_query(),
        "hags": _hags(),
        "nvenc": _nvenc(),
        "nvof_driver": {"state": "READY" if nvof.is_file() else "MISSING", "path": str(nvof)},
    }
