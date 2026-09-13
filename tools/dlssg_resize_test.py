"""Validate in-process feature/resource/NVOF recreation across dimensions."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import DlssgWorker, MOTION_MODE_NVIDIA_OPTICAL_FLOW  # noqa: E402


def frame(width: int, height: int, offset: int) -> bytes:
    data = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            at = (y * width + x) * 4
            data[at:at + 4] = bytes(((x + offset) & 255, (y * 2) & 255, (x ^ y) & 255, 255))
    return bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--community-runtime", type=Path, required=True)
    parser.add_argument("--official-runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    client = DlssgWorker(args.worker.resolve(), args.community_runtime.resolve(), args.official_runtime_dir.resolve(),
                         diagnostic_callback=lambda line: print(line, file=sys.stderr, flush=True))
    generated = 0
    try:
        client.start()
        frame_id = 0
        for width, height in ((256, 256), (320, 180)):
            client.create(width, height, motion_mode=MOTION_MODE_NVIDIA_OPTICAL_FLOW)
            for index in range(3):
                result = client.process(frame_id, frame(width, height, index * 4), reset=index == 0)
                if index == 0:
                    assert result.reset_only
                else:
                    assert result.generated_count == 1 and result.output and not result.disable_interpolation
                    generated += 1
                frame_id += 1
    finally:
        client.close()
    assert generated == 4
    print("RESIZE_TEST_PASS generated=4 createCount=2 dimensions=256x256,320x180")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
