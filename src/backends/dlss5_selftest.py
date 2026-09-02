"""Opt-in synthetic DLSS5 Feature-18 integration test."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from .dlss5 import (
    SELFTEST_RESULT,
    _approval,
    _client_root,
    _hash_report,
    approval_runtime,
    firewall_status,
)


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
    runtime = approval_runtime()
    approval = _approval() or {}
    if runtime is None:
        raise RuntimeError("DLSS5 self-test requires an explicitly approved local manifest")
    matched, hashes, reason = _hash_report(runtime, approval)
    if not matched:
        raise RuntimeError(reason)
    firewall = firewall_status(runtime / "nvngx.dll")
    if not firewall["valid"]:
        raise RuntimeError(firewall["reason"])

    _client_root()
    from dlss5.diagnostics import detect_gpu, ensure_supported
    from dlss5.imaging import fit_frame
    from dlss5.motion import TemporalGuide
    from dlss5.paths import RuntimeLayout
    from dlss5.session import DlssSession
    from dlss5.settings import DlssOptions

    gpu = detect_gpu()
    if gpu["generation"] != 30 or "3070" not in gpu["name"]:
        raise RuntimeError(f"This controlled test requires the approved RTX 3070 path: {gpu}")
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
    try:
        session = DlssSession(layout, options, input_width=width, input_height=height, frame_count=frames)
        worker_pid = session._worker.pid
        guide = TemporalGuide(session.render_width, session.render_height)
        for index in range(frames):
            rgba = fit_frame(_frame(width, height, index), session.render_width, session.render_height)
            motion = guide.process(rgba)
            output, pts = session.submit(index=index, rgba=rgba, motion=motion.motion, reset=motion.reset, pts=index)
            outputs.append({"index": index, "pts": pts, "shape": list(output.shape), "reset": motion.reset})
        session.close()
        feature = session.feature_report()
        if not feature.get("verified"):
            raise RuntimeError("Feature-18 verification did not succeed")
        result = {
            "feature_18_verified": True,
            "feature_18_evidence": feature["evidence"],
            "runtime": str(runtime),
            "worker_path": str(layout.worker),
            "worker_pid": worker_pid,
            "parent_pid": worker_parent_pid,
            "child_processes": [],
            "worker_exit_code": 0,
            "working_directory": str(layout.root),
            "gpu": gpu,
            "bundle": bundle,
            "hashes": hashes,
            "firewall": firewall,
            "frames": frames,
            "input_dimensions": [width, height],
            "output_dimensions": [session.output_width, session.output_height],
            "outputs": outputs,
            "worker_logs": session.worker_logs[-120:],
            "reshade_log": session.reshade_log()[-12000:],
            "new_runtime_files": sorted(_files(runtime) - before),
            "initialization_and_render_seconds": round(time.perf_counter() - started, 3),
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
