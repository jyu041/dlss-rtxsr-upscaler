"""Non-mutating DLSS-G release/readiness assessment."""

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
from .process_utils import tool
from .user_presets import load_last_used

EXPECTED_WORKER_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
EXPECTED_COMMUNITY_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
WORKER_NAME = "dlssg_sm86_offline.exe"
SELFTEST_TIMEOUT_SECONDS = 10


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
    return Path(raw).expanduser().resolve() if raw else None


def _community_runtime(value: str | Path | None, saved: str | None, runtime_profile: str | None = None) -> Path | None:
    explicit = _resolve(value, saved, "DLSSG_COMMUNITY_RUNTIME")
    if explicit is not None:
        return explicit
    if (runtime_profile or os.environ.get("DLSSG_RUNTIME_PROFILE", "legacy")) == "candidate-0.3.1":
        return (ROOT / "runtime" / "dlssg" / "candidate-0.3.1" / "version.dll").resolve()
    return None


def _worker_candidates() -> Iterable[Path]:
    yield ROOT / "runtime" / "dlssg_sm86_offline" / WORKER_NAME
    yield ROOT / "native" / "dlssg_sm86_offline" / "bin" / WORKER_NAME


def _find_worker(value: str | Path | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    configured = os.environ.get("DLSSG_WORKER_EXE")
    if configured:
        return Path(configured).expanduser().resolve()
    return next((candidate.resolve() for candidate in _worker_candidates() if candidate.is_file()), next(iter(_worker_candidates())))


def _tool_launch(name: str, args: list[str], verbose: bool) -> tuple[bool, str | None, str]:
    executable = tool(name)
    if not executable:
        return False, None, f"{name} is not on PATH"
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return False, executable if verbose else None, f"{name} did not respond within 5 seconds"
    except OSError as exc:
        return False, executable if verbose else None, f"{name} could not launch: {exc}"
    if result.returncode:
        return False, executable if verbose else None, f"{name} exited with code {result.returncode}"
    return True, executable if verbose else None, "ready"


def _ffmpeg_check(verbose: bool) -> ReadinessCheck:
    ok, identity, detail = _tool_launch("ffmpeg", ["-hide_banner", "-version"], verbose)
    if not ok:
        return ReadinessCheck("FFMPEG", "MISSING" if "not on PATH" in detail else "BROKEN", False, detail, identity)
    executable = tool("ffmpeg")
    try:
        result = subprocess.run([executable, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ReadinessCheck("FFMPEG", "BROKEN", False, "FFmpeg encoder query failed", identity)
    text = result.stdout + result.stderr
    missing = [name for name in ("h264_nvenc", "hevc_nvenc") if name not in text]
    if result.returncode or missing:
        return ReadinessCheck("FFMPEG", "INCOMPLETE", False, "missing " + ", ".join(missing or ["usable encoders"]), identity)
    return ReadinessCheck("FFMPEG", "READY", True, "launches with h264_nvenc and hevc_nvenc", identity)


def _ffprobe_check(verbose: bool) -> ReadinessCheck:
    ok, identity, detail = _tool_launch("ffprobe", ["-version"], verbose)
    return ReadinessCheck("FFPROBE", "READY" if ok else "MISSING" if "not on PATH" in detail else "BROKEN", ok, detail, identity)


def _gpu_check(verbose: bool) -> ReadinessCheck:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return ReadinessCheck("SYSTEM", "MISSING", False, "nvidia-smi is not on PATH; cannot identify GPU or driver")
    try:
        result = subprocess.run([executable, "--query-gpu=name,driver_version", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return ReadinessCheck("SYSTEM", "BROKEN", False, "nvidia-smi did not respond within 5 seconds")
    except OSError as exc:
        return ReadinessCheck("SYSTEM", "BROKEN", False, f"nvidia-smi could not launch: {exc}")
    if result.returncode or not result.stdout.strip():
        return ReadinessCheck("SYSTEM", "BROKEN", False, f"nvidia-smi GPU query failed with code {result.returncode}")
    identity = result.stdout.strip() if verbose else None
    return ReadinessCheck("SYSTEM", "READY", True, f"NVIDIA GPU/driver identified: {result.stdout.strip()}", identity)


def _vc_runtime_check() -> ReadinessCheck:
    if platform.system() != "Windows":
        return ReadinessCheck("VCRUNTIME", "INCOMPLETE", False, "C55 requires the Microsoft Visual C++ x64 runtime on Windows")
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    required = ("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "ucrtbase.dll")
    missing = [name for name in required if not (system32 / name).is_file()]
    return ReadinessCheck("VCRUNTIME", "READY" if not missing else "MISSING", not missing,
        "Microsoft Visual C++ x64 runtime present" if not missing else "Install Microsoft Visual C++ 2015-2022 Redistributable x64; missing " + ", ".join(missing))


def _selftest(worker: Path, verbose: bool) -> ReadinessCheck:
    try:
        result = subprocess.run([str(worker), "--selftest"], cwd=str(worker.parent), capture_output=True, text=True, timeout=SELFTEST_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return ReadinessCheck("PROJECT", "SELFTEST TIMEOUT", False, f"worker --selftest exceeded {SELFTEST_TIMEOUT_SECONDS} seconds")
    except OSError as exc:
        return ReadinessCheck("PROJECT", "SELFTEST BROKEN", False, f"worker --selftest could not launch: {exc}")
    detail = f"worker SHA verified; self-test {'PASS' if result.returncode == 0 else 'FAIL'} (exit code {result.returncode})"
    identity = f"exit_code={result.returncode}" if verbose else None
    return ReadinessCheck("PROJECT", "READY" if result.returncode == 0 else "SELFTEST FAILED", result.returncode == 0, detail, identity)


def assess(*, worker: str | Path | None = None, community_runtime: str | Path | None = None,
           official_runtime_dir: str | Path | None = None, runtime_profile: str | None = None, verbose: bool = False) -> dict:
    saved = load_last_used().get("dlssg", {})
    checks: list[ReadinessCheck] = []
    system = _gpu_check(verbose)
    windows = platform.system() == "Windows"
    nvof = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvofapi64.dll"
    if not windows or not nvof.is_file():
        system = ReadinessCheck("SYSTEM", "INCOMPLETE", False, system.detail + "; requires Windows and System32\\nvofapi64.dll")
    checks.extend((system, _vc_runtime_check(), _ffmpeg_check(verbose), _ffprobe_check(verbose)))

    worker_path = _find_worker(worker)
    worker_hash = sha256_file(worker_path)
    if worker_hash != EXPECTED_WORKER_SHA256:
        checks.append(ReadinessCheck("PROJECT", "MISSING" if not worker_path.is_file() else "IDENTITY MISMATCH", False,
            f"worker {_display(worker_path, verbose)}; exact Phase 4A SHA-256 required", worker_hash if verbose else None))
    else:
        checks.append(_selftest(worker_path, verbose))

    profile = runtime_profile or saved.get("runtime_profile") or os.environ.get("DLSSG_RUNTIME_PROFILE", "legacy")
    if profile not in {"legacy", "candidate-0.3.1"}:
        raise ValueError(f"Unknown DLSS-G runtime profile: {profile}")
    community_path = _community_runtime(community_runtime, saved.get("community_runtime"), profile)
    community_hash = sha256_file(community_path) if community_path else None
    community_ok = community_hash == EXPECTED_COMMUNITY_SHA256
    checks.append(ReadinessCheck("COMMUNITY", "READY" if community_ok else "MISSING" if not community_path or not community_path.is_file() else "IDENTITY MISMATCH", community_ok,
        f"user-supplied version.dll {_display(community_path, verbose)}; matching hash is provenance, not a safety guarantee" if community_path else "Absolute community version.dll path is required", community_hash if verbose else None))

    official_path = _resolve(official_runtime_dir, saved.get("official_runtime_dir"), "DLSSG_OFFICIAL_RUNTIME_DIR")
    official_ok = bool(official_path and official_path.is_dir() and any(official_path.iterdir()))
    checks.append(ReadinessCheck("OFFICIAL", "CONFIGURED / UNVALIDATED" if official_ok else "MISSING", official_ok,
        f"directory {_display(official_path, verbose)} is present but official runtime contents are validated only by native initialization" if official_ok else "Official NVIDIA NGX runtime directory is required"))

    static_ready = all(item.ok for item in checks)
    return {"state": "DLSS-G STATICALLY READY" if static_ready else "DLSS-G NOT READY", "ready": static_ready,
            "static_ready": static_ready, "checks": [asdict(item) for item in checks],
            "policy": {"worker_sha256": EXPECTED_WORKER_SHA256, "community_sha256": EXPECTED_COMMUNITY_SHA256,
                       "community_hash_is_provenance_only": True, "runtime_profile": profile, "no_fallback": True, "no_download": True,
                       "official_runtime_static_validation": "not attestable without loading native runtime"}}


def format_summary(report: dict) -> str:
    lines = [report["state"]]
    for item in report["checks"]:
        if item["layer"] == "OFFICIAL" and item["state"] == "CONFIGURED / UNVALIDATED":
            lines.append("PASS OFFICIAL: configured; native runtime remains dynamically unvalidated")
        else:
            lines.append(f"{'PASS' if item['ok'] else 'BLOCKED'} {item['layer']}: {item['detail']}")
    return "\n".join(lines)
