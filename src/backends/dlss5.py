"""Gated adapter for the locally approved DLSS5 protocol client."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import Backend, BackendStatus

ROOT = Path(__file__).resolve().parents[2]
APPROVAL = ROOT / "runtime" / "dlss5-v3" / "approval.json"
SELFTEST_RESULT = ROOT / "runtime" / "dlss5-v3" / "selftest.json"
REQUIRED_HASHES = {
    "worker_sha256": ("nvngx.dll",),
    "renodx_sha256": ("renodx-dlss5.addon64",),
    "dlssnr_sha256": ("nvngx_dlssnr.dll",),
    "dxgi_sha256": ("dxgi.dll",),
    "dlss_sha256": ("nvngx_dlss.dll",),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _approval() -> dict[str, Any] | None:
    try:
        data = json.loads(APPROVAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def approval_runtime() -> Path | None:
    approval = _approval()
    if not approval or not approval.get("approved") or not approval.get("approved_by_user"):
        return None
    configured = Path(str(approval.get("runtime_dir", "")))
    return (configured if configured.is_absolute() else ROOT / configured).resolve()


def _hash_report(runtime: Path, approval: dict[str, Any]) -> tuple[bool, dict[str, str], str]:
    actual: dict[str, str] = {}
    for key, names in REQUIRED_HASHES.items():
        path = runtime / names[0]
        if not path.is_file():
            return False, actual, f"Missing required runtime file: {path}"
        actual[key] = _sha256(path)
        expected = str(approval.get(key, "")).upper()
        if actual[key] != expected:
            return False, actual, f"Hash mismatch for {path.name}: {actual[key]} != {expected}"
    return True, actual, "Approved runtime hashes match"


def firewall_status(worker: Path) -> dict[str, Any]:
    """Inspect, but never change, the worker's Windows Firewall rules."""
    script = (
        "Get-NetFirewallRule | "
        "Where-Object {$_.DisplayName -match 'DLSS5'} | ForEach-Object { "
        "$r=$_; $a=@($r | Get-NetFirewallApplicationFilter); "
        "[pscustomobject]@{name=$r.DisplayName;direction=$r.Direction.ToString();"
        "action=$r.Action.ToString();enabled=$r.Enabled.ToString();"
        "program=($a.Program -join '; ')} } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"valid": False, "reason": f"Firewall inspection failed: {exc}", "rules": []}
    if result.returncode:
        return {"valid": False, "reason": result.stderr.strip() or "Firewall inspection failed", "rules": []}
    try:
        parsed = json.loads(result.stdout) if result.stdout.strip() else []
    except ValueError:
        parsed = []
    rules = parsed if isinstance(parsed, list) else [parsed]
    expected = str(Path(worker).resolve()).casefold()
    for rule in rules:
        rule["program_exact"] = str(rule.get("program", "")).casefold() == expected
    outbound = [
        rule for rule in rules
        if rule.get("direction") == "Outbound"
        and rule.get("action") == "Block"
        and rule.get("enabled") == "True"
        and rule.get("program_exact")
    ]
    return {"valid": bool(outbound), "reason": "Outbound worker block verified" if outbound else "No exact enabled outbound block rule", "rules": rules}


def _client_root() -> Path:
    path = ROOT / "third_party" / "ComfyUI-DLSS5-Enhancer"
    if not (path / "dlss5" / "session.py").is_file():
        raise RuntimeError(f"Pinned DLSS5 protocol client is missing: {path}")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path


class DLSS5Backend(Backend):
    def __init__(self):
        self.runtime = approval_runtime()
        self.available = False
        self.reason = "No runtime"
        self._hashes: dict[str, str] = {}
        self._firewall: dict[str, Any] = {"valid": False, "rules": []}
        self._selftest_failed = False
        if self.runtime is None:
            self.reason = "Runtime is not approved by the local manifest"
            return
        approval = _approval() or {}
        matched, self._hashes, self.reason = _hash_report(self.runtime, approval)
        self._firewall = firewall_status(self.runtime / "nvngx.dll")
        if not matched:
            return
        if not self._firewall["valid"]:
            self.reason = self._firewall["reason"]
            return
        try:
            _client_root()
            from dlss5.paths import RuntimeLayout
            from dlss5.diagnostics import ensure_supported

            self.layout = RuntimeLayout(self.runtime).validate()
            self.gpu, self.bundle = ensure_supported(self.layout)
        except Exception as exc:
            self.reason = str(exc)
            return
        try:
            result = json.loads(SELFTEST_RESULT.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
        self._selftest_failed = bool(result) and not result.get("feature_18_verified", False)
        if result.get("feature_18_verified") and result.get("hashes") == self._hashes:
            self.available = True
            self.reason = "Signed Feature-18 self-test passed; outbound worker block verified"
        else:
            self.reason = "Approved runtime has not passed the signed Feature-18 self-test"

    def status(self):
        if self.available:
            state = "EXPERIMENTAL READY"
        elif self.reason.startswith("Hash mismatch"):
            state = "HASH MISMATCH"
        elif self.runtime is None:
            state = "STAGED - NOT APPROVED" if (ROOT / "runtime" / "dlss5-v3" / "approval.json").is_file() else "NO RUNTIME"
        elif self._selftest_failed:
            state = "FAILED SELFTEST"
        elif "self-test" in self.reason:
            state = "APPROVED - NOT TESTED"
        else:
            state = "FAILED SELFTEST"
        return BackendStatus("DLSS 5", self.available, state, self.reason)

    def validate_runtime(self) -> dict[str, Any]:
        if self.runtime is None or not self._hashes:
            raise RuntimeError(self.reason)
        return {"runtime": str(self.runtime), "hashes": self._hashes, "firewall": self._firewall}

    def selftest(self) -> dict[str, Any]:
        if self.runtime is None:
            raise RuntimeError(self.reason)
        command = [sys.executable, "-m", "src.backends.dlss5_selftest"]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            raise RuntimeError(f"DLSS5 self-test failed with exit code {result.returncode}")
        return json.loads(SELFTEST_RESULT.read_text(encoding="utf-8"))

    def _require_ready(self) -> None:
        if not self.available:
            raise RuntimeError(f"DLSS5 is not ready: {self.status().state}; {self.reason}")

    @staticmethod
    def options(**values):
        _client_root()
        from dlss5.settings import DlssOptions

        return DlssOptions.create(**values)

    def process_frame(self, rgba, *, options=None):
        """Process one HWC uint8 RGB/RGBA frame through Feature 18."""
        self._require_ready()
        import numpy as np

        _client_root()
        from dlss5.imaging import fit_frame
        from dlss5.motion import TemporalGuide
        from dlss5.session import DlssSession

        frame = np.asarray(rgba, dtype=np.uint8)
        if frame.ndim != 3 or frame.shape[2] not in (3, 4):
            raise ValueError("DLSS5 frames must be HWC RGB or RGBA arrays")
        if frame.shape[2] == 3:
            frame = np.concatenate((frame, np.full((*frame.shape[:2], 1), 255, dtype=np.uint8)), axis=2)
        options = options or self.options(upscaling_mode=1.0)
        with DlssSession(self.layout, options, input_width=frame.shape[1], input_height=frame.shape[0], frame_count=1) as session:
            source = fit_frame(frame, session.render_width, session.render_height)
            guide = TemporalGuide(session.render_width, session.render_height, enabled=False)
            motion = guide.process(source)
            output, _ = session.submit(index=0, rgba=source, motion=motion.motion, reset=True, pts=0)
        session.feature_report()
        return output

    def process_frames(self, frames, *, width, height, frame_count, options=None, cancel=None):
        """Yield temporally processed RGBA frames from one owned worker session."""
        self._require_ready()
        _client_root()
        from dlss5.imaging import fit_frame
        from dlss5.motion import TemporalGuide
        from dlss5.session import DlssSession

        options = options or self.options(upscaling_mode=1.0, motion_mode="optical_flow")
        with DlssSession(self.layout, options, input_width=width, input_height=height, frame_count=frame_count) as session:
            guide = TemporalGuide(
                session.render_width,
                session.render_height,
                flow_width=options.flow_width,
                scene_change_threshold=options.scene_change_threshold,
                enabled=options.wants_motion(frame_count),
            )
            for index, frame in enumerate(frames):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("DLSS5 render cancelled")
                source = fit_frame(frame, session.render_width, session.render_height)
                motion = guide.process(source)
                output, pts = session.submit(index=index, rgba=source, motion=motion.motion, reset=motion.reset, pts=index)
                yield output, {"index": index, "pts": pts, "reset": motion.reset, "scene_score": motion.scene_score}
            session.close()
            feature = session.feature_report()
            if not feature.get("verified"):
                raise RuntimeError("DLSS5 Feature-18 verification failed after temporal render")

    def process(self, *args, **kwargs):
        raise RuntimeError("Use process_frame/process_video after the signed Feature-18 self-test")
