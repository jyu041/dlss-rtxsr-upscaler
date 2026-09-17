"""Adapter for the managed DLSS5 protocol client and runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .base import Backend, BackendStatus
from .dlss5_recompose import compute_working_dimensions, downsample_for_nr, residual_recompose_cpu, validate_nr_working_scale

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = ROOT / "runtime" / "dlss5-v3"
SELFTEST_RESULT = DEFAULT_RUNTIME / "selftest.json"
REQUIRED_RUNTIME_FILES = {
    "worker_sha256": "nvngx.dll",
    "renodx_sha256": "renodx-dlss5.addon64",
    "dlssnr_sha256": "nvngx_dlssnr.dll",
    "dxgi_sha256": "dxgi.dll",
    "dlss_sha256": "nvngx_dlss.dll",
}

DLSS5_OUTPUT_SCALES = (1.0, 1.5, 1.724, 2.0, 3.0)


def output_scale_supported(gpu: dict[str, Any] | None, bundle: dict[str, Any] | None, scale: float) -> bool:
    """Apply the evidence-backed output-scale policy for the runtime pair."""
    value = float(scale)
    if value not in DLSS5_OUTPUT_SCALES:
        return False
    ampere_pair = isinstance(gpu, dict) and gpu.get("generation") == 30 and isinstance(bundle, dict) and bool(bundle.get("known_ampere_pair"))
    return value == 1.0 or not ampere_pair


def validate_working_scale_for_options(options, scale: float) -> float:
    """Validate the independent NR working scale/output-scale restriction."""
    value = validate_nr_working_scale(scale)
    if value < 1.0 and abs(options.upscaling_factor - 1.0) >= 1e-9:
        raise ValueError("Reduced DLSS5 NR working resolution currently requires DLSS5 output scale 1.0x.")
    return value


def _validate_recompose_backend(value: str) -> str:
    if value not in {"auto", "cuda", "cpu"}:
        raise ValueError("recompose_backend must be auto, cuda, or cpu")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def runtime_path() -> Path:
    configured = os.environ.get("DLSS5_RUNTIME_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_RUNTIME.resolve()


def runtime_fingerprint(runtime: Path) -> dict[str, str]:
    """Return an automatic cache fingerprint; users never need to approve hashes."""
    result: dict[str, str] = {}
    for key, name in REQUIRED_RUNTIME_FILES.items():
        path = runtime / name
        if not path.is_file():
            raise RuntimeError(f"Missing required DLSS5 runtime file: {path}")
        result[key] = _sha256(path)
    return result


def firewall_status(worker: Path) -> dict[str, Any]:
    """Inspect an optional outbound block for diagnostics; it is never a readiness gate."""
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
        return {"valid": False, "reason": f"Firewall inspection unavailable: {exc}", "rules": []}
    if result.returncode:
        return {"valid": False, "reason": result.stderr.strip() or "Firewall inspection unavailable", "rules": []}
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
    return {"valid": bool(outbound), "reason": "Optional outbound worker block present" if outbound else "No optional outbound worker block configured", "rules": rules}


def _client_root() -> Path:
    path = ROOT / "third_party" / "ComfyUI-DLSS5-Enhancer"
    if not (path / "dlss5" / "session.py").is_file():
        raise RuntimeError(f"Pinned DLSS5 protocol client is missing: {path}")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return path


_FEATURE18_FAILURE_PATTERNS = (
    re.compile(r"feature\s*18\s+evaluate(?:d|ion)?\s+failed", re.IGNORECASE),
    re.compile(r"nr\s+upscaling\s+fell\s+back\s+to\s+native", re.IGNORECASE),
    re.compile(r"following\s+frames\s+use\s+the\s+native\s+path", re.IGNORECASE),
)


def _feature18_failure_evidence(log: str) -> list[str]:
    return [line for line in log.splitlines() if any(pattern.search(line) for pattern in _FEATURE18_FAILURE_PATTERNS)]


def _record_feature_telemetry(telemetry: dict[str, Any] | None, feature: dict[str, Any], failures: list[str]) -> None:
    if telemetry is None:
        return
    telemetry["feature_18_verified"] = bool(feature.get("verified"))
    telemetry["native_fallback"] = bool(feature.get("native_fallback")) or bool(failures)
    telemetry["feature_18_evidence"] = feature.get("evidence")
    if failures:
        telemetry["feature_18_failure_evidence"] = failures


def _validate_feature_report(session, feature: dict[str, Any] | None = None, telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Accept a DLSS5 result only while Feature-18 is verified and active."""
    report = feature if feature is not None else session.feature_report()
    log = session.reshade_log()
    failures = _feature18_failure_evidence(log)
    _record_feature_telemetry(telemetry, report, failures)
    if not report.get("verified"):
        raise RuntimeError("DLSS5 Feature-18 verification failed; the output is not accepted as a Neural Rendering result.")
    if report.get("native_fallback") or failures:
        evidence = failures or [str(item) for item in report.get("evidence", []) if "fallback" in str(item).lower()]
        detail = f" Evidence: {' | '.join(evidence[-3:])}" if evidence else ""
        raise RuntimeError("DLSS5 Feature-18 evaluation fell back to the native path; the output is not accepted as a DLSS5 Neural Rendering result." + detail)
    return report


class DLSS5Backend(Backend):
    def __init__(self):
        candidate = runtime_path()
        self.runtime: Path | None = candidate if candidate.is_dir() else None
        self.available = False
        self.reason = "No runtime"
        self._hashes: dict[str, str] = {}
        self._firewall: dict[str, Any] = {"valid": False, "reason": "Not inspected", "rules": []}
        self._selftest_failed = False
        if self.runtime is None:
            self.reason = f"DLSS5 runtime is not installed at {candidate}"
            return
        try:
            self._hashes = runtime_fingerprint(self.runtime)
        except RuntimeError as exc:
            self.reason = str(exc)
            return
        self._firewall = firewall_status(self.runtime / "nvngx.dll")
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
        current_test = result.get("runtime_fingerprint") == self._hashes
        self._selftest_failed = bool(result) and current_test and not result.get("feature_18_verified", False)
        if result.get("feature_18_verified") and current_test:
            self.available = True
            self.reason = "Verified Feature-18 self-test passed"
        else:
            self.reason = "Runtime installed; automatic Feature-18 self-test has not passed for this runtime"

    def status(self):
        if self.available:
            state = "EXPERIMENTAL READY"
        elif self.runtime is None:
            state = "NO RUNTIME"
        elif self._selftest_failed:
            state = "FAILED SELFTEST"
        elif "self-test" in self.reason:
            state = "INSTALLED - SELFTEST REQUIRED"
        else:
            state = "RUNTIME ERROR"
        return BackendStatus("DLSS 5", self.available, state, self.reason)

    def validate_runtime(self) -> dict[str, Any]:
        if self.runtime is None or not self._hashes:
            raise RuntimeError(self.reason)
        return {"runtime": str(self.runtime), "runtime_fingerprint": self._hashes, "firewall_advisory": self._firewall}

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

    def supported_output_scales(self) -> list[float]:
        if isinstance(getattr(self, "gpu", None), dict) and isinstance(getattr(self, "bundle", None), dict):
            return [scale for scale in DLSS5_OUTPUT_SCALES if output_scale_supported(self.gpu, self.bundle, scale)]
        return list(DLSS5_OUTPUT_SCALES)

    def _validate_output_scale(self, options) -> None:
        scale = float(options.upscaling_factor)
        if not output_scale_supported(getattr(self, "gpu", None), getattr(self, "bundle", None), scale):
            if scale != 1.0 and isinstance(getattr(self, "gpu", None), dict) and self.gpu.get("generation") == 30 and isinstance(getattr(self, "bundle", None), dict) and self.bundle.get("known_ampere_pair"):
                raise RuntimeError("DLSS5 output scaling above 1.0x is disabled for the validated RTX 30 Ampere v3 runtime because Quality/Balanced/Performance/Ultra Performance reproducibly fall back with NGX InvalidParameter (0xBAD00005). Use 1.0x DLSS5 output scale.")
            raise ValueError(f"Unsupported DLSS5 output scale: {scale:g}x")

    @staticmethod
    def options(**values):
        _client_root()
        from dlss5.settings import DlssOptions

        return DlssOptions.create(**values)

    def process_frame(self, rgba, *, options=None, nr_working_scale=1.0, recompose_backend="auto", telemetry=None):
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
        self._validate_output_scale(options)
        scale = validate_working_scale_for_options(options, nr_working_scale)
        requested_backend = _validate_recompose_backend(recompose_backend)
        native = frame
        working_width, working_height = compute_working_dimensions(frame.shape[1], frame.shape[0], scale)
        session_options = options if scale == 1.0 else self.options(**{**asdict(options), "upscaling_mode": 1.0})
        with DlssSession(self.layout, session_options, input_width=working_width if scale < 1.0 else frame.shape[1], input_height=working_height if scale < 1.0 else frame.shape[0], frame_count=1) as session:
            source = fit_frame(native, session.render_width, session.render_height) if scale == 1.0 else downsample_for_nr(native, working_width, working_height)
            guide = TemporalGuide(session.render_width, session.render_height, enabled=False)
            motion = guide.process(source)
            output, _ = session.submit(index=0, rgba=source, motion=motion.motion, reset=True, pts=0)
        feature = session.feature_report()
        _validate_feature_report(session, feature, telemetry)
        if scale == 1.0:
            return output
        try:
            compositor = self._create_compositor(requested_backend, frame.shape[1], frame.shape[0], working_width, working_height)
        except Exception:
            if requested_backend == "auto":
                if telemetry is not None:
                    telemetry["recompose_backend_requested"] = requested_backend
                    telemetry["recompose_backend_used"] = "cpu"
                    telemetry["recompose_fallback_reason"] = "No usable CUDA compositor"
                return residual_recompose_cpu(native, source, output)
            raise
        if compositor is None:
            if telemetry is not None:
                telemetry["recompose_backend_requested"] = requested_backend
                telemetry["recompose_backend_used"] = "cpu"
            return residual_recompose_cpu(native, source, output)
        try:
            result, composition_telemetry = compositor.compose(native, source, output)
            if telemetry is not None:
                telemetry.update(composition_telemetry)
                telemetry["recompose_backend_requested"] = requested_backend
                telemetry["recompose_backend_used"] = "cuda"
            return result
        except Exception:
            raise
        finally:
            compositor.close()

    def process_frames(self, frames, *, width, height, frame_count, options=None, cancel=None, nr_working_scale=1.0, telemetry=None, recompose_backend="auto"):
        """Yield temporally processed RGBA frames from one owned worker session."""
        self._require_ready()
        import numpy as np
        _client_root()
        from dlss5.imaging import fit_frame
        from dlss5.motion import TemporalGuide
        from dlss5.session import DlssSession

        options = options or self.options(upscaling_mode=1.0, motion_mode="optical_flow")
        self._validate_output_scale(options)
        scale = validate_working_scale_for_options(options, nr_working_scale)
        requested_backend = _validate_recompose_backend(recompose_backend)
        working_width, working_height = compute_working_dimensions(width, height, scale)
        session_options = options if scale == 1.0 else self.options(**{**asdict(options), "upscaling_mode": 1.0})
        session_started = time.perf_counter()
        with DlssSession(self.layout, session_options, input_width=working_width if scale < 1.0 else width, input_height=working_height if scale < 1.0 else height, frame_count=frame_count) as session:
            if telemetry is not None:
                telemetry["session_initialization_ms"] = (time.perf_counter() - session_started) * 1000
            compositor = None
            if scale < 1.0:
                compositor_started = time.perf_counter()
                try:
                    compositor = self._create_compositor(requested_backend, width, height, working_width, working_height)
                except Exception as exc:
                    if requested_backend == "auto":
                        if telemetry is not None:
                            telemetry["recompose_fallback_reason"] = str(exc)
                        compositor = None
                    else:
                        raise
                if telemetry is not None:
                    telemetry["cuda_compositor_initialization_ms"] = (time.perf_counter() - compositor_started) * 1000 if compositor is not None else None
                    telemetry["recompose_backend_requested"] = requested_backend
                    telemetry["recompose_backend_used"] = "cuda" if compositor is not None else "cpu"
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
                native = np.asarray(frame, dtype=np.uint8)
                loop_started = time.perf_counter()
                preprocess_started = time.perf_counter()
                source = fit_frame(native, session.render_width, session.render_height) if scale == 1.0 else downsample_for_nr(native, working_width, working_height)
                preprocess_ms = (time.perf_counter() - preprocess_started) * 1000
                motion_started = time.perf_counter()
                motion = guide.process(source)
                motion_ms = (time.perf_counter() - motion_started) * 1000
                submit_started = time.perf_counter()
                output, pts = session.submit(index=index, rgba=source, motion=motion.motion, reset=motion.reset, pts=index)
                feature_submit_ms = (time.perf_counter() - submit_started) * 1000
                motion_plus_submit_ms = (time.perf_counter() - motion_started) * 1000
                recompose_started = time.perf_counter()
                cuda_telemetry = {}
                if scale == 1.0:
                    final = output
                elif compositor is None:
                    final = residual_recompose_cpu(native, source, output)
                else:
                    final, cuda_telemetry = compositor.compose(native, source, output)
                recompose_ms = (time.perf_counter() - recompose_started) * 1000
                processing_loop_ms = (time.perf_counter() - loop_started) * 1000
                metadata = {"index": index, "pts": pts, "reset": motion.reset, "scene_score": motion.scene_score, "native_dimensions": [width, height], "working_dimensions": [working_width, working_height], "nr_working_scale": scale, "preprocess_ms": preprocess_ms, "motion_ms": motion_ms, "feature_submit_ms": feature_submit_ms, "motion_plus_submit_ms": motion_plus_submit_ms, "recompose_ms": recompose_ms, "recompose_wall_ms": recompose_ms, "processing_loop_ms": processing_loop_ms}
                if scale < 1.0:
                    metadata.update({"recompose_backend_requested": requested_backend, "recompose_backend_used": "cuda" if compositor is not None else "cpu"})
                    if cuda_telemetry:
                        metadata.update(cuda_telemetry)
                        if telemetry is not None:
                            telemetry["cuda_allocator"] = compositor.allocator_stats()
                            if telemetry.get("capture_compositor_samples") and index in {0, frame_count // 2, frame_count - 1}:
                                telemetry.setdefault("compositor_samples", []).append({"native": native.copy(), "source": source.copy(), "nr": output.copy(), "cuda": final.copy()})
                if telemetry is not None:
                    telemetry.setdefault("frames", []).append(metadata)
                yield final, metadata
            session.close()
            try:
                feature = session.feature_report()
                _validate_feature_report(session, feature, telemetry)
            finally:
                if compositor is not None:
                    compositor.close()

    def _create_compositor(self, requested_backend, native_width, native_height, working_width, working_height):
        if requested_backend == "cpu":
            return None
        from .dlss5_cuda_recompose import CudaResidualCompositor, select_cuda_device
        device = select_cuda_device(self.gpu.get("name") if isinstance(self.gpu, dict) else None)
        if device is None:
            raise RuntimeError("No unambiguous CUDA device matches the DLSS5 runtime GPU")
        return CudaResidualCompositor(native_width, native_height, working_width, working_height, device=device)

    def process(self, *args, **kwargs):
        raise RuntimeError("Use process_frame/process_video after the verified Feature-18 self-test")
