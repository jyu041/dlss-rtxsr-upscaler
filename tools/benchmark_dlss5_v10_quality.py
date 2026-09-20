"""Bounded real-video A/B matrix for the isolated DLSS5 v10 application path.

Requires the normal v10 preflight to have passed. The tool does not weaken any
security gate. It varies only controls already represented in the versioned v10
CREATE protocol and records review videos, quality metrics, and stage timings.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_v10_app import DLSS5V10ExperimentalBackend  # noqa: E402
from src.video.dlss5_v10 import render_dlss5_v10  # noqa: E402
from tools.benchmark_dlss5_quality import decode_window, quality_metrics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runtime" / "audit" / "dlss5-v10-quality")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--include-nvof", action="store_true")
    args = parser.parse_args()
    if args.start < 0 or args.duration <= 0:
        parser.error("start must be non-negative and duration positive")

    source_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    backend = DLSS5V10ExperimentalBackend()
    status = backend.status()
    if not status.available:
        raise RuntimeError(f"v10 application backend is not ready: {status.state}: {status.reason}")

    # Decode a source reference window once. Render outputs are trimmed to the
    # same decoded count before quality metrics are calculated.
    source_probe, fps = decode_window(
        source_path,
        start=args.start,
        frames=max(2, int(round(args.duration * 120))),
    )
    expected = max(2, int(round(args.duration * fps)))
    source_frames = source_probe[:expected]

    cases = [
        {"name": "baseline-current", "nr_passes": 1, "shimmer_suppression": 0.70, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "shimmer-off", "nr_passes": 1, "shimmer_suppression": 0.0, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "shimmer-0p35", "nr_passes": 1, "shimmer_suppression": 0.35, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "shimmer-1p0", "nr_passes": 1, "shimmer_suppression": 1.0, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "passes-2", "nr_passes": 2, "shimmer_suppression": 0.70, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "passes-3", "nr_passes": 3, "shimmer_suppression": 0.70, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "passes-4", "nr_passes": 4, "shimmer_suppression": 0.70, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": False},
        {"name": "detail-tone-preserved", "nr_passes": 1, "shimmer_suppression": 0.70, "color_strength": 0.0, "tone_preservation": 1.0, "prefer_nvof": False},
    ]
    if args.include_nvof:
        cases.append({"name": "prefer-nvof", "nr_passes": 1, "shimmer_suppression": 0.70, "color_strength": 1.0, "tone_preservation": 0.0, "prefer_nvof": True})

    results: list[dict] = []
    for case in cases:
        destination = output_dir / f"{case['name']}.mp4"
        stats = render_dlss5_v10(
            source_path,
            destination,
            backend,
            scale=1.0,
            style="Natural",
            intensity=0.60,
            local_tone=0.40,
            local_structure=0.40,
            skin_structure=0.15,
            automatic_mask=False,
            nr_passes=int(case["nr_passes"]),
            color_strength=float(case["color_strength"]),
            tone_preservation=float(case["tone_preservation"]),
            face_skin_protection=0.0,
            grain_preservation=0.0,
            shimmer_suppression=float(case["shimmer_suppression"]),
            prefer_nvof=bool(case["prefer_nvof"]),
            start=args.start,
            duration=args.duration,
            codec="H.264",
        )
        output_frames, _ = decode_window(destination, start=0.0, frames=len(source_frames))
        count = min(len(source_frames), len(output_frames))
        if count < 2:
            raise RuntimeError(f"{case['name']} produced insufficient review frames")
        metrics = quality_metrics(source_frames[:count], output_frames[:count])
        row = {
            **case,
            "output": str(destination),
            "frames_compared": count,
            "fps": stats.get("fps"),
            "scene_resets": stats.get("scene_resets"),
            "performance": stats.get("performance"),
            "quality_controls": stats.get("quality_controls"),
            **metrics,
        }
        results.append(row)
        print(
            f"{case['name']}: fps={float(stats.get('fps', 0)):.2f} "
            f"effect={float(metrics['effect_mae'] or 0):.3f} "
            f"temporal={float(metrics['motion_compensated_residual_flicker_mae'] or 0):.3f}"
        )

    report = {
        "schema_version": 1,
        "status": "PASS",
        "input": str(source_path),
        "start_seconds": args.start,
        "duration_seconds": args.duration,
        "source_fps": fps,
        "cases": results,
        "promotion_policy": (
            "No quality setting is promoted from this report alone. Review the "
            "videos and metrics on the RTX 3070 Ti before changing UI defaults."
        ),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"DLSS5_V10_QUALITY_MATRIX_PASS report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
