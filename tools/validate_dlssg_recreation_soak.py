"""Repeat fresh DLSS-G worker/feature creation and require deterministic output.

This is an explicit RTX hardware gate, not an ordinary pytest. Each cycle starts
a new worker process, creates a new DLSS-G feature, renders the same bounded
source through the no-encode sink, closes cleanly, and compares the raw sink
hash. The isolation matches this project's production architecture and avoids
carrying feature-dependent kernel state across recreations.
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
DEFAULT_COMMUNITY = ROOT / "runtime" / "dlssg" / "legacy" / "version.dll"
DEFAULT_OFFICIAL = ROOT / "runtime" / "dlssg" / "official"
DEFAULT_C55 = ROOT / "runtime" / "dlssg" / "worker" / "dlssg_sm86_offline.exe"
DEFAULT_GRID4 = ROOT / "runtime" / "dlssg" / "grid4-worker" / "dlssg_sm86_offline.exe"


def _bounded_clip(source: Path, destination: Path, frames: int) -> None:
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-frames:v", str(frames), "-an", "-c:v", "ffv1", "-level", "3",
        "-pix_fmt", "yuv444p", str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"bounded source creation failed: {result.stderr[-2000:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--profile", choices=("validated", "grid4-gpu-candidate"), default="validated")
    parser.add_argument("--multiplier", type=int, choices=(2, 3, 4), default=4)
    parser.add_argument("--cycles", type=int, default=15)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--community-runtime", type=Path, default=DEFAULT_COMMUNITY)
    parser.add_argument("--official-runtime-dir", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cycles < 2 or args.frames < 3:
        parser.error("cycles must be >=2 and frames >=3")

    worker = (args.worker or (DEFAULT_GRID4 if args.profile == "grid4-gpu-candidate" else DEFAULT_C55)).resolve()
    community = args.community_runtime.resolve()
    official = args.official_runtime_dir.resolve()
    for label, path in (("worker", worker), ("community runtime", community)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} missing: {path}")
    if not official.is_dir():
        raise FileNotFoundError(f"official runtime directory missing: {official}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    hashes: list[str] = []

    with tempfile.TemporaryDirectory(prefix="nve-mfg-recreate-") as temporary:
        temp = Path(temporary)
        bounded = temp / "source.mkv"
        _bounded_clip(args.input.resolve(), bounded, args.frames)
        for cycle in range(args.cycles):
            sink = temp / f"cycle-{cycle:02d}.mp4"
            command = [
                sys.executable, str(VIDEO),
                "--input", str(bounded),
                "--output", str(sink),
                "--worker", str(worker),
                "--community-runtime", str(community),
                "--official-runtime-dir", str(official),
                "--multiplier", str(args.multiplier),
                "--nvof-profile", args.profile,
                "--terminal-frame-policy", "duplicate",
                "--no-audio", "--no-scene-cut-detection",
                "--no-encode-control", "--quiet-worker-log",
            ]
            run = subprocess.run(command, capture_output=True, text=True, check=False)
            manifest = sink.with_suffix(".dlssg-manifest.json")
            if run.returncode or not manifest.is_file():
                raise RuntimeError(
                    f"cycle {cycle} failed rc={run.returncode}: "
                    f"{(run.stderr or run.stdout)[-3000:]}"
                )
            report = json.loads(manifest.read_text(encoding="utf-8"))
            digest = report.get("no_encode_sink_sha256")
            if report.get("status") != "PASS" or not digest:
                raise RuntimeError(f"cycle {cycle} did not produce a PASS sink hash")
            if report.get("interpolation_disabled_frame_ids"):
                raise RuntimeError(f"cycle {cycle} disabled interpolation")
            lifecycle = report.get("lifecycle_timing_seconds") or {}
            if lifecycle.get("device_removal_results"):
                raise RuntimeError(f"cycle {cycle} reported device removal")
            if int(lifecycle.get("dlssg_create_feature_count", 0)) != 1:
                raise RuntimeError(f"cycle {cycle} expected exactly one feature creation")
            hashes.append(str(digest))
            records.append({
                "cycle": cycle,
                "sink_sha256": digest,
                "input_frames": report.get("input_frames"),
                "output_frames": report.get("output_frames"),
                "generated_frames": report.get("generated_frames"),
                "end_to_end_fps": report.get("end_to_end_fps"),
                "worker_create_features": lifecycle.get("dlssg_create_feature_count"),
                "worker_evaluates": lifecycle.get("evaluate_count"),
                "worker_exit_code": lifecycle.get("worker_exit_code"),
                "device_removal_results": lifecycle.get("device_removal_results", []),
            })
            print(f"cycle {cycle + 1}/{args.cycles}: {digest}")

    unique = sorted(set(hashes))
    result = {
        "schema_version": 1,
        "status": "PASS" if len(unique) == 1 else "FAIL",
        "profile": args.profile,
        "multiplier": args.multiplier,
        "cycles": args.cycles,
        "frames": args.frames,
        "worker": str(worker),
        "community_runtime": str(community),
        "unique_sink_hashes": unique,
        "records": records,
        "classification": (
            "fresh-process feature recreation is deterministic"
            if len(unique) == 1
            else "fresh-process feature recreation changed output"
        ),
        "scope": (
            "This proves this project's process-isolated recreation contract; "
            "it does not claim that an in-process proxy feature recreation is safe."
        ),
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if len(unique) != 1:
        raise RuntimeError(f"recreation soak produced {len(unique)} distinct sink hashes")
    print(f"DLSSG_RECREATION_SOAK_PASS report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
