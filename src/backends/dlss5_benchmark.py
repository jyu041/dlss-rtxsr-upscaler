"""Opt-in isolated DLSS5 benchmark matrix (never part of pytest)."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from .dlss5 import DLSS5Backend, ROOT
from .dlss5_diagnostics import collect
from .dlss5_metrics import effect_metrics, effect_observed, statistics
from .dlss5_recompose import SUPPORTED_NR_WORKING_SCALES, compute_working_dimensions, validate_nr_working_scale

DEFAULT_RESOLUTIONS = ((128, 128), (960, 540), (1280, 720), (1920, 1080), (2560, 1440))


def parse_resolutions(value: str) -> list[tuple[int, int]]:
    result = []
    for item in value.split(","):
        try:
            width, height = (int(part) for part in item.lower().split("x", 1))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid resolution: {item}") from None
        if width < 1 or height < 1:
            raise ValueError(f"Invalid resolution: {item}")
        result.append((width, height))
    return result


def parse_working_scales(value: str) -> list[float]:
    return [validate_nr_working_scale(item) for item in value.split(",")]


def _frame(width: int, height: int, index: int) -> np.ndarray:
    frame = np.empty((height, width, 4), dtype=np.uint8)
    frame[..., 0] = np.arange(width, dtype=np.uint32)[None, :] % 256
    frame[..., 1] = np.arange(height, dtype=np.uint32)[:, None] % 256
    frame[..., 2] = 64
    frame[..., 3] = 255
    size = max(8, min(width, height) // 8)
    left = (index * max(1, width // 32)) % max(1, width - size + 1)
    frame[height // 3 : height // 3 + size, left : left + size, :3] = 255
    return frame


def _vram_mib(gpu_index: int = 0) -> int | None:
    try:
        result = subprocess.run(["nvidia-smi", f"--id={gpu_index}", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=False)
        return int(result.stdout.strip().splitlines()[0]) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class _VramSampler:
    def __init__(self, gpu_index: int = 0, interval: float = 0.2):
        self.gpu_index, self.interval = gpu_index, interval
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="dlss5-vram-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            value = _vram_mib(self.gpu_index)
            if value is not None:
                self.samples.append(value)
            self._stop.wait(self.interval)

    def stop(self) -> int | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return max(self.samples) if self.samples else None


def _stage_stats(metadata: list[dict[str, Any]], name: str) -> dict[str, float | None]:
    return statistics([float(item[name]) for item in metadata])


def run_case(width: int, height: int, scale: float, warmup: int, frames: int) -> dict[str, Any]:
    backend = DLSS5Backend()
    scale = validate_nr_working_scale(scale)
    working = compute_working_dimensions(width, height, scale)
    if not backend.available:
        return {"status": "UNSUPPORTED", "native_resolution": [width, height], "working_scale": scale, "working_resolution": list(working), "reason": backend.reason}
    options = backend.options(upscaling_mode=1.0, motion_mode="optical_flow")
    native_frames = [_frame(width, height, index) for index in range(warmup + frames)]
    before = _vram_mib()
    telemetry: dict[str, Any] = {}
    sampler = _VramSampler()
    rendered = None
    try:
        rendered = backend.process_frames(native_frames, width=width, height=height, frame_count=len(native_frames), options=options, nr_working_scale=scale, telemetry=telemetry)
        first = next(rendered)
        after_init = _vram_mib()
        sampler.start()
        results = [first, *rendered]
        peak = sampler.stop()
        feature = telemetry.get("feature", {})
        metadata = [item[1] for item in results]
        if len(results) != len(native_frames):
            return {"status": "FAILED", "native_resolution": [width, height], "working_scale": scale, "working_resolution": list(working), "reason": "Unexpected frame count"}
        effects = [effect_metrics(native_frames[index], output) for index, (output, _) in enumerate(results) if index >= warmup and index in {warmup, warmup + frames // 2, warmup + frames - 1}]
        feature_stats = _stage_stats(metadata[warmup:], "feature_submit_ms")
        motion_stats = _stage_stats(metadata[warmup:], "motion_ms")
        combined_stats = _stage_stats(metadata[warmup:], "motion_plus_submit_ms")
        loop_stats = _stage_stats(metadata[warmup:], "processing_loop_ms")
        valid = all(item.get("feature_18_verified", True) for item in metadata) and all(tuple(output.shape) == (height, width, 4) for output, _ in results) and bool(telemetry.get("feature_18_verified", True))
        if not valid:
            return {"status": "FAILED", "native_resolution": [width, height], "working_scale": scale, "working_resolution": list(working), "reason": "Feature-18, output shape, or worker validation failed"}
        effect_mae = mean([item["mean_absolute_difference"] for item in effects]) if effects else 0.0
        return {"status": "PASS", "native_resolution": [width, height], "working_scale": scale, "working_resolution": list(working), "session_initialization_ms": telemetry.get("session_initialization_ms"), "warmup_total_ms": sum(item["processing_loop_ms"] for item in metadata[:warmup]), "warmup_average_ms": mean([item["processing_loop_ms"] for item in metadata[:warmup]]) if warmup else 0.0, "feature_submit_mean_ms": feature_stats["mean_ms"], "feature_submit_median_ms": feature_stats["median_ms"], "feature_submit_p95_ms": feature_stats["p95_ms"], "feature_submit_min_ms": feature_stats["min_ms"], "feature_submit_max_ms": feature_stats["max_ms"], "feature_submit_fps": 1000 / feature_stats["mean_ms"] if feature_stats["mean_ms"] else None, "motion_mean_ms": motion_stats["mean_ms"], "motion_median_ms": motion_stats["median_ms"], "motion_p95_ms": motion_stats["p95_ms"], "motion_plus_submit_mean_ms": combined_stats["mean_ms"], "motion_plus_submit_median_ms": combined_stats["median_ms"], "motion_plus_submit_p95_ms": combined_stats["p95_ms"], "motion_plus_submit_fps": 1000 / combined_stats["mean_ms"] if combined_stats["mean_ms"] else None, "preprocess_mean_ms": _stage_stats(metadata[warmup:], "preprocess_ms")["mean_ms"], "recompose_mean_ms": _stage_stats(metadata[warmup:], "recompose_ms")["mean_ms"], "processing_loop_mean_ms": loop_stats["mean_ms"], "processing_loop_median_ms": loop_stats["median_ms"], "processing_loop_p95_ms": loop_stats["p95_ms"], "processing_loop_fps": 1000 / loop_stats["mean_ms"] if loop_stats["mean_ms"] else None, "vram_before_mib": before, "vram_after_init_mib": after_init, "vram_peak_mib": peak, "vram_delta_peak_mib": peak - before if peak is not None and before is not None else None, "effect_metrics": effects, "effect_mae": effect_mae, "nr_effect_observed": any(effect_observed(item) for item in effects), "feature_18_evidence": telemetry.get("feature_18_evidence")}
    finally:
        if sampler._thread is not None:
            sampler.stop()


def _kill_owned_tree(pid: int) -> None:
    try:
        import psutil
        root = psutil.Process(pid)
        children = root.children(recursive=True)
        for process in reversed(children):
            process.terminate()
        psutil.wait_procs(children, timeout=3)
        for process in children:
            if process.is_running():
                process.kill()
        if root.is_running():
            root.terminate()
            root.wait(timeout=3)
    except Exception:
        pass


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Opt-in DLSS5 benchmark")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=4)
    parser.add_argument("--resolutions", default=",".join(f"{w}x{h}" for w, h in DEFAULT_RESOLUTIONS))
    parser.add_argument("--working-scales", default="1.0")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.frames < 1 or args.warmup < 0:
        parser.error("--frames must be positive and --warmup cannot be negative")
    if args.case:
        width, height = parse_resolutions(args.case)[0]
        scale = parse_working_scales(args.working_scales)[0]
        try:
            print(json.dumps(run_case(width, height, scale, args.warmup, args.frames), separators=(",", ":")))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "FAILED", "reason": str(exc), "native_resolution": [width, height], "working_scale": scale}))
            return 1
    backend = DLSS5Backend()
    if not backend.available:
        raise RuntimeError(f"DLSS5 benchmark requires EXPERIMENTAL READY: {backend.reason}")
    environment = collect()
    cases = []
    for width, height in parse_resolutions(args.resolutions):
        for scale in parse_working_scales(args.working_scales):
            command = [sys.executable, "-m", "src.backends.dlss5_benchmark", "--case", f"{width}x{height}", "--frames", str(args.frames), "--warmup", str(args.warmup), "--working-scales", str(scale)]
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                stdout, stderr = child.communicate(timeout=args.timeout)
                try:
                    case = json.loads(stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    case = {"status": "FAILED", "reason": stderr[-2000:] or "Invalid child benchmark result", "native_resolution": [width, height], "working_scale": scale}
            except subprocess.TimeoutExpired:
                _kill_owned_tree(child.pid)
                case = {"status": "TIMEOUT", "reason": f"case exceeded {args.timeout:g}s", "native_resolution": [width, height], "working_scale": scale, "working_resolution": list(compute_working_dimensions(width, height, scale))}
            cases.append(case)
            print(f"{width}x{height} scale={scale:g} {case.get('status','FAILED'):<10} work={case.get('working_resolution','-')} feature_fps={case.get('feature_submit_fps','-')} loop_fps={case.get('processing_loop_fps','-')} median={case.get('processing_loop_median_ms','-')} p95={case.get('processing_loop_p95_ms','-')} motion={case.get('motion_mean_ms','-')} vram={case.get('vram_peak_mib','-')} effect={case.get('nr_effect_observed','-')}")
    native_cases = {(tuple(case.get("native_resolution", [])), case.get("working_scale")): case for case in cases if case.get("status") == "PASS"}
    for case in cases:
        if case.get("status") == "PASS":
            native = native_cases.get((tuple(case["native_resolution"]), 1.0))
            case["effect_mae_ratio_vs_native"] = case["effect_mae"] / native["effect_mae"] if native and native.get("effect_mae") else None
    valid = [case for case in cases if case.get("status") == "PASS" and case.get("nr_effect_observed")]
    report = {"schema_version": 2, "timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": _commit(), "system": environment["application"], "gpu": environment["gpu"], "driver": environment["gpu"].get("driver_version"), "runtime": {"directory": environment["runtime_directory"], "files": environment["runtime_files"], "actual_sha256": environment["actual_sha256"], "expected_sha256": environment["expected_sha256"], "hash_match": environment["hash_match"]}, "benchmark_settings": {"resolutions": args.resolutions, "working_scales": parse_working_scales(args.working_scales), "warmup": args.warmup, "frames": args.frames, "timeout_seconds": args.timeout}, "cases": cases, "summary": {"fastest_valid_case": min(valid, key=lambda c: c.get("processing_loop_mean_ms", float("inf"))).get("native_resolution") if valid else None, "highest_valid_resolution": max(valid, key=lambda c: c["native_resolution"][0]).get("native_resolution") if valid else None, "failed_cases": [c.get("native_resolution") for c in cases if c.get("status") == "FAILED"], "timed_out_cases": [c.get("native_resolution") for c in cases if c.get("status") == "TIMEOUT"]}}
    path = ROOT / "logs" / f"dlss5-benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"JSON report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
