"""Repeatable native DLSS-G group benchmark; keeps results as JSON evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import (  # noqa: E402
    DlssgWorker,
    MOTION_MODE_EXTERNAL_R16G16_FLOAT,
    MOTION_MODE_NVIDIA_OPTICAL_FLOW,
)
from src.core.dlssg_gpu_timing import summarize_gpu_timestamps  # noqa: E402


def _frame(width: int, height: int, x: int) -> bytes:
    value = bytearray(width * height * 4)
    for y in range(height):
        for px in range(width):
            square = x <= px < x + max(16, width // 8) and height // 3 <= y < height // 3 + max(16, height // 8)
            offset = (y * width + px) * 4
            value[offset:offset + 4] = bytes((180, 190, 80, 255) if square else (16 + px % 16, 24 + y % 16, 32, 255))
    return bytes(value)


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(percentile) - 1]


def _gpu() -> dict[str, str]:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,temperature.gpu,pstate,power.draw", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=False,
    )
    return {"raw": result.stdout.strip(), "returncode": str(result.returncode)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--community-runtime", type=Path, required=True)
    parser.add_argument("--official-runtime-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--multiplier", type=int, choices=(2, 3, 4), required=True)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--motion-provider", choices=("nvof", "external"), default="nvof")
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--worker-log", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    motion_mode = MOTION_MODE_NVIDIA_OPTICAL_FLOW if args.motion_provider == "nvof" else MOTION_MODE_EXTERNAL_R16G16_FLOAT
    worker_log = args.worker_log.open("w", encoding="utf-8") if args.worker_log else None
    worker_lines: list[str] = []
    def _worker_line(line: str) -> None:
        worker_lines.append(line)
        if args.diagnostics:
            print(line, file=sys.stderr, flush=True)
        if worker_log:
            worker_log.write(line + "\n")
            worker_log.flush()
    callback = _worker_line if args.diagnostics or worker_log else None
    worker = DlssgWorker(args.worker.resolve(), args.community_runtime.resolve(), args.official_runtime_dir.resolve(), diagnostic_callback=callback, diagnostic_mode=args.diagnostics)
    samples: list[dict[str, float]] = []
    motion = struct.pack("<ee", -4.0, 0.0) * (args.width * args.height)
    start = time.perf_counter()
    try:
        worker.start()
        worker.create(args.width, args.height, multiplier=args.multiplier, motion_mode=motion_mode)
        for frame_id in range(args.warmup + args.frames):
            color = _frame(args.width, args.height, 32 + (frame_id % 8) * 4)
            payload = None if args.motion_provider == "nvof" else (bytes(args.width * args.height * 4) if frame_id == 0 else motion)
            result = worker.process(frame_id, color, payload, reset=frame_id == 0)
            if frame_id >= args.warmup:
                samples.append({
                    "total_ms": result.total_process_ms,
                    "upload_ms": result.upload_ms,
                    "evaluate_cpu_ms": result.evaluate_cpu_ms,
                    "gpu_wait_ms": result.gpu_wait_ms,
                    "readback_ms": result.readback_ms,
                    "nvof_upload_ms": result.nvof_upload_ms,
                    "nvof_execute_ms": result.nvof_execute_ms,
                    "flow_conversion_ms": result.flow_conversion_ms,
                    "generated_count": float(result.generated_count),
                })
    finally:
        worker.close()
        if worker_log:
            worker_log.close()
    summary: dict[str, object] = {
        "schema_version": 1,
        "timestamp": time.time(),
        "system": {"gpu": _gpu()},
        "worker": str(args.worker.resolve()),
        "settings": {"width": args.width, "height": args.height, "multiplier": args.multiplier, "frames": args.frames, "warmup": args.warmup, "motion_provider": args.motion_provider},
        "samples": samples,
        "stages_ms": {key: {"median": statistics.median([sample[key] for sample in samples]), "p95": _percentile([sample[key] for sample in samples], 95)} for key in samples[0] if key != "generated_count"},
        "gpu_timestamps": summarize_gpu_timestamps(worker_lines),
        "group_rate_median": 1000.0 / statistics.median([sample["total_ms"] for sample in samples]),
        "output_rate_median": args.multiplier * 1000.0 / statistics.median([sample["total_ms"] for sample in samples]),
        "wall_seconds": time.perf_counter() - start,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "json_output": str(args.json_output), "median_total_ms": summary["stages_ms"]["total_ms"]["median"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
