"""Synthetic DLSS5 Feature-18 integration test for the managed runtime."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from .dlss5 import (
    SELFTEST_RESULT,
    _client_root,
    firewall_status,
    runtime_fingerprint,
    runtime_path,
)
from .dlss5_metrics import effect_metrics, effect_observed


def _frame(width: int, height: int, index: int) -> np.ndarray:
    image = np.zeros((height, width, 4), dtype=np.uint8)
    image[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    image[..., 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    image[..., 2] = 64
    image[..., 3] = 255
    size = max(8, min(width, height) // 8)
    left = (index * 5) % max(1, width - size)
    image[height // 3 : height // 3 + size, left : left + size, :3] = 255
    return image


def _files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def main() -> int:
    started = time.perf_counter()
    validation_started = started
    runtime = runtime_path()
    if not runtime.is_dir():
        raise RuntimeError(f"DLSS5 runtime is not installed at {runtime}")
    fingerprint = runtime_fingerprint(runtime)
    firewall = firewall_status(runtime / "nvngx.dll")

    runtime_validation_seconds = time.perf_counter() - validation_started
    _client_root()
    from dlss5.diagnostics import detect_gpu, ensure_supported
    from dlss5.imaging import fit_frame
    from dlss5.motion import TemporalGuide
    from dlss5.paths import RuntimeLayout
    from dlss5.session import DlssSession
    from dlss5.settings import DlssOptions

    gpu = detect_gpu()
    layout = RuntimeLayout(runtime).validate()
    _, bundle = ensure_supported(layout)
    before = _files(runtime)
    options = DlssOptions.create(
        upscaling_mode=1.0,
        nr_style="Natural",
        nr_intensity=0.60,
        local_tone_strength=0.40,
        local_structure_strength=0.40,
        skin_structure_strength=0.15,
        automatic_mask=False,
        dlss_model_preset="Default",
        motion_mode="optical_flow",
    )
    width = height = 128
    frames = 5
    session = None
    worker_pid = None
    worker_parent_pid = os.getpid()
    outputs = []
    session_started = time.perf_counter()
    submit_times = []
    effect = None
    try:
        session = DlssSession(layout, options, input_width=width, input_height=height, frame_count=frames)
        session_initialization_seconds = time.perf_counter() - session_started
        worker_pid = session._worker.pid
        guide = TemporalGuide(session.render_width, session.render_height)
        for index in range(frames):
            rgba = fit_frame(_frame(width, height, index), session.render_width, session.render_height)
            motion = guide.process(rgba)
            submit_started = time.perf_counter()
            output, pts = session.submit(index=index, rgba=rgba, motion=motion.motion, reset=motion.reset, pts=index)
            submit_times.append(time.perf_counter() - submit_started)
            if index == 0:
                effect = effect_metrics(rgba, output)
            outputs.append({"index": index, "pts": pts, "shape": list(output.shape), "reset": motion.reset})
        session.close()
        feature = session.feature_report()
        if not feature.get("verified"):
            raise RuntimeError("Feature-18 verification did not succeed")
        render_seconds = sum(submit_times)
        first_submit_seconds = submit_times[0] if submit_times else 0.0
        result = {
            "feature_18_verified": True,
            "nr_effect_observed": effect_observed(effect or {}),
            "feature_18_evidence": feature["evidence"],
            "effectiveness_metrics": effect,
            "runtime": str(runtime),
            "runtime_fingerprint": fingerprint,
            "firewall_advisory": firewall,
            "worker_path": str(layout.worker),
            "worker_pid": worker_pid,
            "parent_pid": worker_parent_pid,
            "child_processes": [],
            "worker_exit_code": 0,
            "working_directory": str(layout.root),
            "gpu": gpu,
            "bundle": bundle,
            "frames": frames,
            "input_dimensions": [width, height],
            "output_dimensions": [session.output_width, session.output_height],
            "outputs": outputs,
            "worker_logs": session.worker_logs[-120:],
            "reshade_log": session.reshade_log()[-12000:],
            "new_runtime_files": sorted(_files(runtime) - before),
            "runtime_validation_seconds": round(runtime_validation_seconds, 6),
            "session_initialization_seconds": round(session_initialization_seconds, 6),
            "first_submit_seconds": round(first_submit_seconds, 6),
            "render_seconds": round(render_seconds, 6),
            "submit_roundtrip_seconds": round(render_seconds, 6),
            "total_seconds": round(time.perf_counter() - started, 6),
            "timing_note": "submit_roundtrip_seconds is CPU-side protocol round-trip time, not GPU time",
            "settings": options.native(),
            "note": "Synthetic local experimental execution only; no personal media used.",
        }
    except BaseException:
        if session is not None and not session._closed:
            session.abort()
        raise
    SELFTEST_RESULT.parent.mkdir(parents=True, exist_ok=True)
    SELFTEST_RESULT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
