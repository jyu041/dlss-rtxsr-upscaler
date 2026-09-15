"""Pure, non-mutating DLSS-G release/readiness assessment.

This module deliberately does not download, configure, load, or start any
native runtime.  It answers whether the five required layers are present and
identifiable, so the UI and release tooling share one decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Iterable

from .paths import ROOT
from .user_presets import load_last_used

EXPECTED_WORKER_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
EXPECTED_COMMUNITY_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
WORKER_NAME = "dlssg_sm86_offline.exe"


@dataclass(frozen=True)
class ReadinessCheck:
    layer: str
    state: str
    ok: bool
    detail: str
    identity: str | None = None


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except (OSError, ValueError):
        return None


def _display(path: Path | None, verbose: bool) -> str:
    if path is None:
        return "<not configured>"
    return str(path) if verbose else f"<configured>/{path.name}"


def _resolve(value: str | Path | None, saved: str | None, env_name: str) -> Path | None:
    raw = value or saved or os.environ.get(env_name)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _worker_candidates() -> Iterable[Path]:
    yield ROOT / "runtime" / "dlssg_sm86_offline" / WORKER_NAME
    yield ROOT / "native" / "dlssg_sm86_offline" / "bin" / WORKER_NAME


def _find_worker(value: str | Path | None) -> Path | None:
    if value:
        return Path(value).expanduser().resolve()
    configured = os.environ.get("DLSSG_WORKER_EXE")
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in _worker_candidates():
        if candidate.is_file():
            return candidate.resolve()
    return next(iter(_worker_candidates()))


def _ffmpeg_check(verbose: bool) -> ReadinessCheck:
    path = shutil.which("ffmpeg")
    if not path:
        return ReadinessCheck("SYSTEM", "MISSING", False, "FFmpeg is not on PATH")
    try:
        result = subprocess.run([path, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ReadinessCheck("SYSTEM", "BROKEN", False, "FFmpeg did not respond within 5 seconds")
    encoders = result.stdout + result.stderr
    missing = [name for name in ("h264_nvenc", "hevc_nvenc") if name not in encoders]
    if result.returncode or missing:
        return ReadinessCheck("SYSTEM", "INCOMPLETE", False, "FFmpeg lacks " + ", ".join(missing or ["a usable encoder"]))
    return ReadinessCheck("SYSTEM", "READY", True, "Windows tools and h264_nvenc/hevc_nvenc available", Path(path).name if verbose else None)


def assess(*, worker: str | Path | None = None, community_runtime: str | Path | None = None,
           official_runtime_dir: str | Path | None = None, verbose: bool = False) -> dict:
    saved = load_last_used().get("dlssg", {})
    checks: list[ReadinessCheck] = []
    system_ok = platform.system() == "Windows"
    nvof_ok = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvofapi64.dll"
    gpu_tool = shutil.which("nvidia-smi")
    gpu_ok = False
    if gpu_tool:
        try:
            gpu_ok = subprocess.run([gpu_tool, "-L"], capture_output=True, text=True, timeout=5, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            gpu_ok = False
    checks.append(ReadinessCheck("SYSTEM", "READY" if system_ok and gpu_ok and nvof_ok.is_file() else "INCOMPLETE", system_ok and gpu_ok and nvof_ok.is_file(),
        "Windows + NVIDIA GPU + driver Optical Flow API" if system_ok and gpu_ok and nvof_ok.is_file() else "Requires Windows, a working NVIDIA GPU, and System32\\nvofapi64.dll"))

    worker_path = _find_worker(worker)
    worker_hash = sha256_file(worker_path) if worker_path else None
    worker_ok = worker_hash == EXPECTED_WORKER_SHA256
    checks.append(ReadinessCheck("PROJECT", "READY" if worker_ok else "MISSING" if not worker_path or not worker_path.is_file() else "IDENTITY MISMATCH", worker_ok,
        f"worker {_display(worker_path, verbose)}; expected Phase 4A production identity" if worker_path else "Project worker is not configured", worker_hash if verbose else None))

    community_path = _resolve(community_runtime, saved.get("community_runtime"), "DLSSG_COMMUNITY_RUNTIME")
    community_hash = sha256_file(community_path) if community_path else None
    community_ok = community_hash == EXPECTED_COMMUNITY_SHA256
    checks.append(ReadinessCheck("COMMUNITY", "READY" if community_ok else "MISSING" if not community_path or not community_path.is_file() else "IDENTITY MISMATCH", community_ok,
        f"user-supplied version.dll {_display(community_path, verbose)}; exact known identity required" if community_path else "Absolute community version.dll path is required", community_hash if verbose else None))

    official_path = _resolve(official_runtime_dir, saved.get("official_runtime_dir"), "DLSSG_OFFICIAL_RUNTIME_DIR")
    official_files = list(official_path.iterdir()) if official_path and official_path.is_dir() else []
    official_ok = bool(official_files)
    checks.append(ReadinessCheck("OFFICIAL", "READY" if official_ok else "MISSING", official_ok,
        f"user-supplied NVIDIA NGX runtime directory {_display(official_path, verbose)}" if official_ok else "Official NVIDIA NGX runtime directory is required"))

    ffmpeg = _ffmpeg_check(verbose)
    checks[0] = ReadinessCheck("SYSTEM", "READY" if checks[0].ok and ffmpeg.ok else "INCOMPLETE", checks[0].ok and ffmpeg.ok,
                               checks[0].detail + ("; " + ffmpeg.detail if not ffmpeg.ok else "; FFmpeg ready"))
    ready = all(check.ok for check in checks)
    return {"state": "DLSS-G READY" if ready else "DLSS-G NOT READY", "ready": ready,
            "checks": [asdict(check) for check in checks], "policy": {"worker_sha256": EXPECTED_WORKER_SHA256,
            "community_sha256": EXPECTED_COMMUNITY_SHA256, "no_fallback": True, "no_download": True}}


def format_summary(report: dict) -> str:
    lines = [report["state"]]
    for check in report["checks"]:
        mark = "PASS" if check["ok"] else "BLOCKED"
        lines.append(f"{mark} {check['layer']}: {check['detail']}")
    return "\n".join(lines)
