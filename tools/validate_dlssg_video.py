"""Validate encoded 2X frame order, timing, audio, and non-duplicate midpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import av
import numpy as np

from src.video.dlssg import probe_video  # noqa: E402


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
    parser.add_argument("--render-manifest", type=Path)
    args = parser.parse_args()
    real, input_fps, input_duration, input_audio = decode(args.input)
    output, output_fps, output_duration, output_audio = decode(args.output)
    input_info = probe_video(args.input)
    output_info = probe_video(args.output)
    render_manifest = (
        json.loads(args.render_manifest.read_text(encoding="utf-8"))
        if args.render_manifest and args.render_manifest.exists() else {}
    )
    cut_pairs = {int(item["pair"]) for item in render_manifest.get("scene_cuts", [])}
    assert len(output) == 2 * len(real)
    assert abs(output_fps - 2 * input_fps) < 1e-6
    assert abs(output_duration - input_duration) <= 1 / max(input_fps, 1)
    if input_audio:
        assert output_audio
        assert abs(float(output_info["audio_duration"]) - float(input_info["audio_duration"])) <= 0.1
    color_metadata_preserved = all(
        int(input_info[key]) <= 0 or int(output_info[key]) == int(input_info[key])
        for key in ("color_range", "color_space", "color_primaries", "color_transfer")
    )
    assert color_metadata_preserved
    real_mad = [mad(output[index * 2], frame) for index, frame in enumerate(real)]
    generated = []
    for index in range(len(real) - 1):
        candidate = output[index * 2 + 1]
        previous_mad = mad(candidate, real[index])
        current_mad = mad(candidate, real[index + 1])
        pair_mad = mad(real[index], real[index + 1])
        pair_id = index + 1
        if pair_id in cut_pairs:
            assert previous_mad < 3.0
            kind = "SCENE_CUT_HOLD"
        else:
            assert previous_mad > 0 and current_mad > 0
            kind = "GENERATED"
        generated.append({"pair": pair_id, "kind": kind, "mad_previous": previous_mad,
                          "mad_current": current_mad, "mad_real_pair": pair_mad})
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
        "input_audio_duration": input_info["audio_duration"],
        "output_audio_duration": output_info["audio_duration"],
        "color_metadata_preserved": color_metadata_preserved,
        "input_color_metadata": {
            key: input_info[key] for key in ("color_range", "color_space", "color_primaries", "color_transfer")
        },
        "output_color_metadata": {
            key: output_info[key] for key in ("color_range", "color_space", "color_primaries", "color_transfer")
        },
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
