"""Validate encoded 2X frame order, timing, audio, and non-duplicate midpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import av
import numpy as np


def decode(path: Path) -> tuple[list[np.ndarray], float, float, bool]:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frames = [frame.to_ndarray(format="rgba") for frame in container.decode(stream)]
        fps = float(stream.average_rate or stream.base_rate or 0)
        duration = float(container.duration or 0) / av.time_base
        return frames, fps, duration, bool(container.streams.audio)


def mad(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    real, input_fps, input_duration, input_audio = decode(args.input)
    output, output_fps, output_duration, output_audio = decode(args.output)
    assert len(output) == 2 * len(real)
    assert abs(output_fps - 2 * input_fps) < 1e-6
    assert abs(output_duration - input_duration) <= 1 / max(input_fps, 1)
    if input_audio:
        assert output_audio
    real_mad = [mad(output[index * 2], frame) for index, frame in enumerate(real)]
    generated = []
    for index in range(len(real) - 1):
        candidate = output[index * 2 + 1]
        previous_mad = mad(candidate, real[index])
        current_mad = mad(candidate, real[index + 1])
        pair_mad = mad(real[index], real[index + 1])
        assert previous_mad > 0 and current_mad > 0
        generated.append({"pair": index, "mad_previous": previous_mad, "mad_current": current_mad,
                          "mad_real_pair": pair_mad})
    terminal_mad = mad(output[-1], real[-1])
    result = {
        "status": "PASS",
        "input_frames": len(real),
        "output_frames": len(output),
        "input_fps": input_fps,
        "output_fps": output_fps,
        "input_duration": input_duration,
        "output_duration": output_duration,
        "audio_preserved": not input_audio or output_audio,
        "real_slot_mad_mean": sum(real_mad) / len(real_mad),
        "terminal_duplicate_mad": terminal_mad,
        "generated": generated,
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
