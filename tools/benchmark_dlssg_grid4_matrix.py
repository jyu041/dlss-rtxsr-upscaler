"""Run a bounded RTX 3070-class DLSS-G profile/multiplier performance matrix.

The matrix never changes application defaults. It runs the pinned C55/grid1
baseline and managed grid4 candidate through the same no-encode workload for
2X/3X/4X, recording deterministic sink hashes and native/IPC timing. Optional
encoded runs add end-to-end NVENC measurements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "tools" / "dlssg_video.py"
C55 = ROOT / "runtime" / "dlssg" / "worker" / "dlssg_sm86_offline.exe"
GRID4 = ROOT / "runtime" / "dlssg" / "grid4-worker" / "dlssg_sm86_offline.exe"
COMMUNITY = ROOT / "runtime" / "dlssg" / "legacy" / "version.dll"
OFFICIAL = ROOT / "runtime" / "dlssg" / "official"


def _bounded_clip(source: Path, destination: Path, frames: int) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-frames:v", str(frames), "-an", "-c:v", "ffv1", "-level", "3",
            "-pix_fmt", "yuv444p", str(destination),
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"bounded clip creation failed: {result.stderr[-2000:]}")


def _run(
    source: Path,
    output: Path,
    *,
    profile: str,
    multiplier: int,
    encode: bool,
) -> dict:
    worker = GRID4 if profile == "grid4-gpu-candidate" else C55
    command = [
        sys.executable, str(VIDEO),
        "--input", str(source),
        "--output", str(output),
        "--worker", str(worker),
        "--community-runtime", str(COMMUNITY),
        "--official-runtime-dir", str(OFFICIAL),
        "--multiplier", str(multiplier),
        "--nvof-profile", profile,
        "--terminal-frame-policy", "duplicate",
        "--no-audio", "--no-scene-cut-detection", "--quiet-worker-log",
    ]
    if not encode:
        command.append("--no-encode-control")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    manifest = output.with_suffix(".dlssg-manifest.json")
    if result.returncode or not manifest.is_file():
        raise RuntimeError(
            f"{profile} {multiplier}X encode={encode} failed rc={result.returncode}: "
            f"{(result.stderr or result.stdout)[-3000:]}"
        )
    report = json.loads(manifest.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise RuntimeError(f"{profile} {multiplier}X did not report PASS")
    if report.get("interpolation_disabled_frame_ids"):
        raise RuntimeError(f"{profile} {multiplier}X disabled interpolation")
    lifecycle = report.get("lifecycle_timing_seconds") or {}
    if lifecycle.get("device_removal_results"):
        raise RuntimeError(f"{profile} {multiplier}X reported device removal")
    if int(report.get("output_frames", 0)) != int(report.get("expected_output_frames", -1)):
        raise RuntimeError(f"{profile} {multiplier}X frame count mismatch")
    return report


def _compact(report: dict) -> dict:
    lifecycle = report.get("lifecycle_timing_seconds") or {}
    timing = report.get("timings_mean_ms") or {}
    return {
        "profile": report.get("nvof_profile"),
        "multiplier": report.get("multiplier"),
        "input_frames": report.get("input_frames"),
        "generated_frames": report.get("generated_frames"),
        "output_frames": report.get("output_frames"),
        "sink_sha256": report.get("no_encode_sink_sha256"),
        "total_wall_seconds": report.get("total_wall_seconds"),
        "end_to_end_fps": report.get("end_to_end_fps"),
        "effective_input_fps": report.get("effective_input_fps"),
        "native_total_process_ms": timing.get("total_process_ms"),
        "gpu_wait_ms": timing.get("gpu_wait_ms"),
        "readback_ms": timing.get("readback_ms"),
        "nvof_upload_ms": timing.get("nvof_upload_ms"),
        "nvof_execute_ms": timing.get("nvof_execute_ms"),
        "flow_conversion_ms": timing.get("flow_conversion_ms"),
        "worker_rpc_ipc_gap_ms_per_pair": report.get("worker_rpc_ipc_gap_ms_per_pair"),
        "decode_ms_per_frame": report.get("decode_ms_per_frame"),
        "encode_write_ms_per_output": report.get("encode_write_ms_per_output"),
        "worker_create_seconds": lifecycle.get("worker_create_seconds"),
        "worker_exit_code": lifecycle.get("worker_exit_code"),
        "device_removal_results": lifecycle.get("device_removal_results", []),
        "vram_before_mib": report.get("vram_before_mib"),
        "vram_peak_mib": report.get("vram_peak_mib"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--encoded", action="store_true", help="also run NVENC end-to-end cases")
    parser.add_argument("--review-dir", type=Path, default=ROOT / "runtime" / "audit" / "dlssg-grid4-review", help="preserve encoded C55/grid4 review videos and their manifests/logs")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "audit" / "dlssg-grid4-matrix.json")
    args = parser.parse_args()
    if args.frames < 3:
        parser.error("--frames must be at least 3")
    for path in (C55, GRID4, COMMUNITY):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not OFFICIAL.is_dir():
        raise FileNotFoundError(OFFICIAL)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    review_dir = args.review_dir.resolve()
    if args.encoded:
        review_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nve-grid4-matrix-") as temporary:
        temp = Path(temporary)
        bounded = temp / "source.mkv"
        _bounded_clip(args.input.resolve(), bounded, args.frames)
        for multiplier in (2, 3, 4):
            for profile in ("validated", "grid4-gpu-candidate"):
                modes = (False, True) if args.encoded else (False,)
                for encode in modes:
                    destination = (
                        review_dir / f"{profile}-{multiplier}x-encoded.mp4"
                        if encode
                        else temp / f"{profile}-{multiplier}x-sink.mp4"
                    )
                    report = _run(
                        bounded,
                        destination,
                        profile=profile,
                        multiplier=multiplier,
                        encode=encode,
                    )
                    row = _compact(report)
                    row["encoded"] = encode
                    rows.append(row)
                    print(
                        f"{profile} {multiplier}X {'encoded' if encode else 'sink'}: "
                        f"wall={float(row['total_wall_seconds']):.3f}s "
                        f"native={float(row['native_total_process_ms'] or 0):.3f}ms"
                    )

    comparisons: list[dict] = []
    for multiplier in (2, 3, 4):
        for encoded in ((False, True) if args.encoded else (False,)):
            baseline = next(row for row in rows if row["multiplier"] == multiplier and row["profile"] == "validated" and row["encoded"] == encoded)
            grid4 = next(row for row in rows if row["multiplier"] == multiplier and row["profile"] == "grid4-gpu-candidate" and row["encoded"] == encoded)
            base_wall = float(baseline["total_wall_seconds"])
            grid_wall = float(grid4["total_wall_seconds"])
            base_native = float(baseline["native_total_process_ms"] or 0.0)
            grid_native = float(grid4["native_total_process_ms"] or 0.0)
            comparisons.append({
                "multiplier": multiplier,
                "encoded": encoded,
                "wall_change_percent": ((grid_wall / base_wall) - 1.0) * 100.0 if base_wall else None,
                "native_total_change_percent": ((grid_native / base_native) - 1.0) * 100.0 if base_native else None,
                "sink_hash_equal": (
                    baseline["sink_sha256"] == grid4["sink_sha256"]
                    if not encoded else None
                ),
            })

    result = {
        "schema_version": 1,
        "status": "PASS",
        "frames": args.frames,
        "review_dir": str(review_dir) if args.encoded else None,
        "rows": rows,
        "comparisons": comparisons,
        "promotion_policy": (
            "Grid4 remains experimental regardless of this result. Promotion "
            "requires review of 2X/3X/4X quality, performance, recreation soak, "
            "and existing C55 regression behavior."
        ),
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"DLSSG_GRID4_MATRIX_PASS report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
