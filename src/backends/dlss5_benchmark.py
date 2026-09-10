"""Opt-in isolated DLSS5 benchmark matrix (never part of pytest)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from .dlss5 import DLSS5Backend, ROOT
from .dlss5_metrics import effect_metrics, effect_observed, statistics

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


def _vram_mib() -> int | None:
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=False)
        return int(result.stdout.strip().splitlines()[0]) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def run_case(width: int, height: int, warmup: int, frames: int) -> dict[str, Any]:
    backend = DLSS5Backend()
    if not backend.available:
        return {"status": "UNSUPPORTED", "reason": backend.reason, "resolution": [width, height]}
    options = backend.options(upscaling_mode=1.0, motion_mode="optical_flow")
    before = _vram_mib()
    session_started = time.perf_counter()
    outputs = []
    submit_ms, motion_ms = [], []
    peak = before
    session = None
    try:
        __import__("sys").path.insert(0, str(ROOT / "third_party" / "ComfyUI-DLSS5-Enhancer"))
        from dlss5.imaging import fit_frame
        from dlss5.motion import TemporalGuide
        from dlss5.session import DlssSession
        session = DlssSession(backend.layout, options, input_width=width, input_height=height, frame_count=warmup + frames)
        init_ms = (time.perf_counter() - session_started) * 1000
        after_init = _vram_mib()
        peak = max((x for x in (peak, after_init) if x is not None), default=None)
        guide = TemporalGuide(session.render_width, session.render_height, enabled=True)
        effects = []
        all_submit_ms = []
        for index in range(warmup + frames):
            source = fit_frame(_frame(width, height, index), session.render_width, session.render_height)
            motion_start = time.perf_counter()
            guide_result = guide.process(source)
            motion_ms.append((time.perf_counter() - motion_start) * 1000)
            if index == warmup + frames // 2:
                guide_result = guide_result.__class__(guide_result.motion, True, guide_result.scene_score)
            submit_start = time.perf_counter()
            output, _ = session.submit(index=index, rgba=source, motion=guide_result.motion, reset=guide_result.reset, pts=index)
            elapsed = (time.perf_counter() - submit_start) * 1000
            all_submit_ms.append(elapsed)
            if index >= warmup:
                submit_ms.append(elapsed)
                if len(effects) < 3:
                    effects.append(effect_metrics(source, output))
            outputs.append(output)
            sample = _vram_mib()
            if sample is not None:
                peak = max(peak or sample, sample)
        session.close()
        feature = session.feature_report()
        valid = bool(feature.get("verified")) and len(outputs) == warmup + frames and all(output.shape == (session.output_height, session.output_width, 4) for output in outputs)
        if not valid:
            return {"status": "FAILED", "reason": "Feature-18 evidence, output shape, or frame count validation failed", "resolution": [width, height]}
        motion_stats = statistics(motion_ms[warmup:])
        submit_stats = statistics(submit_ms)
        observed = any(effect_observed(item) for item in effects)
        total_ms = sum(submit_ms)
        return {"status": "PASS", "resolution": [width, height], "session_initialization_ms": init_ms, "warmup_total_ms": sum(all_submit_ms[:warmup]) + sum(motion_ms[:warmup]), "warmup_average_ms": (sum(all_submit_ms[:warmup]) + sum(motion_ms[:warmup])) / warmup if warmup else 0.0, "submit_roundtrip_mean_ms": submit_stats["mean_ms"], "submit_roundtrip_median_ms": submit_stats["median_ms"], "submit_roundtrip_p95_ms": submit_stats["p95_ms"], "submit_roundtrip_min_ms": submit_stats["min_ms"], "submit_roundtrip_max_ms": submit_stats["max_ms"], "steady_state_fps": 1000 * len(submit_ms) / total_ms if total_ms else None, "motion_mean_ms": motion_stats["mean_ms"], "motion_median_ms": motion_stats["median_ms"], "motion_p95_ms": motion_stats["p95_ms"], "vram_before_mib": before, "vram_after_init_mib": after_init, "vram_peak_mib": peak, "vram_delta_peak_mib": peak - before if peak is not None and before is not None else None, "effect_metrics": effects, "nr_effect_observed": observed, "feature_18_evidence": feature.get("evidence")}
    finally:
        if session is not None and not session._closed:
            session.abort()


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Opt-in DLSS5 benchmark")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=4)
    parser.add_argument("--resolutions", default=",".join(f"{w}x{h}" for w, h in DEFAULT_RESOLUTIONS))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--case", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.frames < 1 or args.warmup < 0:
        parser.error("--frames must be positive and --warmup cannot be negative")
    if args.case:
        try:
            width, height = parse_resolutions(args.case)[0]
            print(json.dumps(run_case(width, height, args.warmup, args.frames), separators=(",", ":")))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "FAILED", "reason": str(exc), "resolution": parse_resolutions(args.case)[0]}))
            return 1
    backend = DLSS5Backend()
    if not backend.available:
        raise RuntimeError(f"DLSS5 benchmark requires EXPERIMENTAL READY: {backend.reason}")
    from .dlss5_diagnostics import collect
    environment = collect()
    cases = []
    for width, height in parse_resolutions(args.resolutions):
        command = [sys.executable, "-m", "src.backends.dlss5_benchmark", "--case", f"{width}x{height}", "--frames", str(args.frames), "--warmup", str(args.warmup)]
        child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = child.communicate(timeout=args.timeout)
            try:
                case = json.loads(stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                case = {"status": "FAILED", "reason": stderr[-2000:] or "Invalid child benchmark result", "resolution": [width, height]}
        except subprocess.TimeoutExpired:
            _kill_owned_tree(child.pid)
            case = {"status": "TIMEOUT", "reason": f"case exceeded {args.timeout:g}s", "resolution": [width, height]}
        cases.append(case)
        print(f"{width}x{height:<5} {case.get('status','FAILED'):<10} init={case.get('session_initialization_ms','-')} ms fps={case.get('steady_state_fps','-')} median={case.get('submit_roundtrip_median_ms','-')} p95={case.get('submit_roundtrip_p95_ms','-')} motion={case.get('motion_mean_ms','-')} vram={case.get('vram_peak_mib','-')} effect={case.get('nr_effect_observed','-')}")
    valid = [case for case in cases if case.get("status") == "PASS" and case.get("nr_effect_observed")]
    report = {"schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(), "git_commit": _commit(), "system": environment["application"], "gpu": environment["gpu"], "driver": environment["gpu"].get("driver_version"), "runtime": {"directory": environment["runtime_directory"], "files": environment["runtime_files"], "actual_sha256": environment["actual_sha256"], "expected_sha256": environment["expected_sha256"], "hash_match": environment["hash_match"]}, "benchmark_settings": {"resolutions": args.resolutions, "warmup": args.warmup, "frames": args.frames, "timeout_seconds": args.timeout}, "cases": cases, "summary": {"fastest_valid_case": min(valid, key=lambda c: c.get("submit_roundtrip_mean_ms", float("inf"))).get("resolution") if valid else None, "highest_valid_resolution": max(valid, key=lambda c: c["resolution"][0]).get("resolution") if valid else None, "failed_cases": [c["resolution"] for c in cases if c.get("status") == "FAILED"], "timed_out_cases": [c["resolution"] for c in cases if c.get("status") == "TIMEOUT"]}}
    path = ROOT / "logs" / f"dlss5-benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"JSON report: {path}")
    return 0


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
