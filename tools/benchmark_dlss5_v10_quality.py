"""Bounded real-video A/B matrix for the isolated DLSS5 v10 application path.

Requires the normal v10 preflight to have passed. The tool does not weaken any
security gate. It varies native v10 controls plus the application-level shared
working-resolution/recomposition/temporal layer and records review videos,
quality metrics, and stage timings.
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
from src.core.media_info import probe  # noqa: E402
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
    source_info = probe(str(source_path))
    fps = float(source_info["fps"])
    expected = max(2, int(round(args.duration * fps)))
    source_frames, _ = decode_window(
        source_path,
        start=args.start,
        frames=expected,
    )

    common = {
        "nr_passes": 1,
        "shimmer_suppression": 0.70,
        "color_strength": 1.0,
        "tone_preservation": 0.0,
        "prefer_nvof": False,
        "nr_working_scale": 1.0,
        "recompose_backend": "auto",
        "temporal_stabilization": 0.0,
    }
    cases = [
        {"name": "baseline-current", **common},
        {"name": "shimmer-off", **common, "shimmer_suppression": 0.0},
        {"name": "shimmer-0p35", **common, "shimmer_suppression": 0.35},
        {"name": "shimmer-1p0", **common, "shimmer_suppression": 1.0},
        {"name": "passes-2", **common, "nr_passes": 2},
        {"name": "passes-3", **common, "nr_passes": 3},
        {"name": "passes-4", **common, "nr_passes": 4},
        {"name": "detail-tone-preserved", **common, "color_strength": 0.0, "tone_preservation": 1.0},
        {"name": "working-0p75", **common, "nr_working_scale": 0.75},
        {"name": "working-0p666", **common, "nr_working_scale": 2.0 / 3.0},
        {"name": "working-0p75-temporal-0p5", **common, "nr_working_scale": 0.75, "temporal_stabilization": 0.5},
        {"name": "passes-4-working-0p75", **common, "nr_passes": 4, "nr_working_scale": 0.75},
    ]
    if args.include_nvof:
        cases.append({"name": "prefer-nvof", **common, "prefer_nvof": True})

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
            nr_working_scale=case["nr_working_scale"],
            recompose_backend=str(case["recompose_backend"]),
            temporal_stabilization=float(case["temporal_stabilization"]),
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
            "end_to_end_fps": stats.get("fps"),
            "processing_fps": stats.get("processing_fps"),
            "scene_resets": stats.get("scene_resets"),
            "working_dimensions": stats.get("working_dimensions"),
            "nr_working_scale_resolved": stats.get("nr_working_scale_resolved"),
            "recompose_backend_used": stats.get("recompose_backend_used"),
            "temporal_stabilization": stats.get("temporal_stabilization"),
            "performance": stats.get("performance"),
            "quality_controls": stats.get("quality_controls"),
            **metrics,
        }
        results.append(row)
        print(
            f"{case['name']}: processing_fps={float(stats.get('processing_fps', 0)):.2f} "
            f"e2e_fps={float(stats.get('fps', 0)):.2f} "
            f"effect={float(metrics['effect_mae'] or 0):.3f} "
            f"temporal={float(metrics['motion_compensated_residual_flicker_mae'] or 0):.3f} "
            f"work={stats.get('nr_working_scale_resolved')} "
            f"recompose={stats.get('recompose_backend_used')}"
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
