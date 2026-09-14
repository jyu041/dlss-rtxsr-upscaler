"""Persistent internal-NVOF + offline DLSS-G 2X integration test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import struct

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import (  # noqa: E402
    DlssgWorker,
    MOTION_MODE_EXTERNAL_R16G16_FLOAT,
    MOTION_MODE_NVIDIA_OPTICAL_FLOW,
)


def frame(width: int, height: int, square_x: int, square_y: int = 96) -> bytes:
    output = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            square = square_x <= x < square_x + 64 and square_y <= y < square_y + 64
            offset = (y * width + x) * 4
            local_x = x - square_x
            output[offset + 0] = 160 + ((local_x + y) & 63) if square else 16 + (x & 31)
            output[offset + 1] = 176 + ((local_x * 3 + y) & 63) if square else 24 + (y & 31)
            output[offset + 2] = 64 + ((local_x ^ y) & 63) if square else 32 + ((x ^ y) & 31)
            output[offset + 3] = 255
    return bytes(output)


def bright_centroid(payload: bytes, width: int, height: int) -> tuple[float, float]:
    """Estimate the moving test square's centroid for temporal-order checks."""
    weighted_x = weighted_y = weight_total = 0.0
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 4
            red, green = payload[offset], payload[offset + 1]
            weight = max(0, red - 80) + max(0, green - 96)
            weighted_x += x * weight
            weighted_y += y * weight
            weight_total += weight
    if not weight_total:
        raise AssertionError("generated output has no trackable bright subject")
    return weighted_x / weight_total, weighted_y / weight_total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--community-runtime", type=Path, required=True)
    parser.add_argument("--official-runtime-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "runtime" / "dlssg_nvof_persistent.json")
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--quiet-worker-log", action="store_true")
    parser.add_argument("--multiplier", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--motion-mode", choices=("nvof", "external"), default="nvof")
    args = parser.parse_args()
    width, height = args.width, args.height
    if width < 64 or height < 64:
        raise ValueError("width and height must each be at least 64")
    client = DlssgWorker(
        args.worker.resolve(),
        args.community_runtime.resolve(),
        args.official_runtime_dir.resolve(),
        diagnostic_callback=None if args.quiet_worker_log else lambda line: print(line, file=sys.stderr, flush=True),
    )
    records: list[dict[str, object]] = []
    hashes: set[str] = set()
    try:
        client.start()
        motion_mode = MOTION_MODE_NVIDIA_OPTICAL_FLOW if args.motion_mode == "nvof" else MOTION_MODE_EXTERNAL_R16G16_FLOAT
        client.create(width, height, multiplier=args.multiplier, motion_mode=motion_mode)
        frame_id = 0
        for sequence, count, origin, delta in ((1, 12, 32, 4), (2, 4, 176, -4)):
            if sequence == 2:
                client.reset_history()
            for index in range(count):
                color = frame(width, height, origin + index * delta)
                motion = None if args.motion_mode == "nvof" else (
                    bytes(width * height * 4) if index == 0 else struct.pack("<ee", -4.0, 0.0) * (width * height)
                )
                result = client.process(frame_id, color, motion, reset=index == 0)
                record: dict[str, object] = {
                    "frame_id": frame_id,
                    "sequence": sequence,
                    "reset_only": result.reset_only,
                    "disable": result.disable_interpolation,
                    "timings_ms": {
                        "nvof_upload": result.nvof_upload_ms,
                        "nvof_execute": result.nvof_execute_ms,
                        "flow_conversion": result.flow_conversion_ms,
                        "dlssg_upload": result.upload_ms,
                        "dlssg_evaluate_cpu": result.evaluate_cpu_ms,
                        "dlssg_gpu_wait": result.gpu_wait_ms,
                        "readback": result.readback_ms,
                        "total": result.total_process_ms,
                    },
                }
                if index == 0:
                    assert result.reset_only and not result.output
                else:
                    expected_count = args.multiplier - 1
                    assert result.generated_count == expected_count and result.disable_interpolation == 0
                    assert len(result.outputs) == expected_count
                    digests = []
                    centroids = []
                    for output in result.outputs:
                        assert len(output) == width * height * 4
                        assert any(output) and len(set(output)) > 1
                        assert output != color
                        digest = hashlib.sha256(output).hexdigest().upper()
                        assert digest not in hashes, f"stale generated output {digest}"
                        hashes.add(digest); digests.append(digest)
                        centroids.append(bright_centroid(output, width, height))
                    assert len(set(result.outputs)) == expected_count
                    direction = 1 if delta > 0 else -1
                    assert all((right[0] - left[0]) * direction > 0 for left, right in zip(centroids, centroids[1:]))
                    record["sha256"] = digests
                    record["centroids"] = centroids
                    record["generated_count"] = expected_count
                records.append(record)
                frame_id += 1
    finally:
        client.close()
    generated = sum(len(record.get("sha256", [])) for record in records)
    assert len(records) == 16 and generated == 14 * (args.multiplier - 1) and len(hashes) == generated
    manifest = {
        "status": "PASS",
        "motion_mode": "NVIDIA_OPTICAL_FLOW_INTERNAL" if args.motion_mode == "nvof" else "EXTERNAL_R16G16_FLOAT",
        "multiplier": args.multiplier,
        "input_frames": len(records),
        "generated_outputs": generated,
        "unique_generated_hashes": len(hashes),
        "resets": 2,
        "frames": records,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(args.manifest), "generated": generated}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
