"""Persistent internal-NVOF + offline DLSS-G 2X integration test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import (  # noqa: E402
    DlssgWorker,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--community-runtime", type=Path, required=True)
    parser.add_argument("--official-runtime-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=ROOT / "runtime" / "dlssg_nvof_persistent.json")
    args = parser.parse_args()
    width = height = 256
    client = DlssgWorker(
        args.worker.resolve(),
        args.community_runtime.resolve(),
        args.official_runtime_dir.resolve(),
        diagnostic_callback=lambda line: print(line, file=sys.stderr, flush=True),
    )
    records: list[dict[str, object]] = []
    hashes: set[str] = set()
    try:
        client.start()
        client.create(width, height, motion_mode=MOTION_MODE_NVIDIA_OPTICAL_FLOW)
        frame_id = 0
        for sequence, count, origin, delta in ((1, 12, 32, 4), (2, 4, 176, -4)):
            if sequence == 2:
                client.reset_history()
            for index in range(count):
                color = frame(width, height, origin + index * delta)
                result = client.process(frame_id, color, reset=index == 0)
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
                    assert result.generated_count == 1 and result.disable_interpolation == 0
                    assert len(result.output) == width * height * 4
                    assert any(result.output) and len(set(result.output)) > 1
                    assert result.output != color
                    digest = hashlib.sha256(result.output).hexdigest().upper()
                    assert digest not in hashes, f"stale generated output {digest}"
                    hashes.add(digest)
                    record["sha256"] = digest
                records.append(record)
                frame_id += 1
    finally:
        client.close()
    generated = sum(1 for record in records if "sha256" in record)
    assert len(records) == 16 and generated == 14 and len(hashes) == 14
    manifest = {
        "status": "PASS",
        "motion_mode": "NVIDIA_OPTICAL_FLOW_INTERNAL",
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
