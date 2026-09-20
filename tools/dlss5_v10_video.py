"""Render video through the experimental application-facing DLSS5 v10 backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_v10_client import APP_EXPERIMENT_ACK  # noqa: E402
from src.backends.dlss5_v10_app import DLSS5V10ExperimentalBackend  # noqa: E402
from src.video.dlss5_v10 import render_dlss5_v10  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--style", choices=("Default", "Natural", "Cinematic"), default="Natural")
    parser.add_argument("--intensity", type=float, default=0.60)
    parser.add_argument("--local-tone", type=float, default=0.40)
    parser.add_argument("--local-structure", type=float, default=0.40)
    parser.add_argument("--skin-structure", type=float, default=0.15)
    parser.add_argument("--automatic-mask", action="store_true")
    parser.add_argument("--nr-passes", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--color-strength", type=float, default=1.0)
    parser.add_argument("--tone-preservation", type=float, default=0.0)
    parser.add_argument("--face-skin-protection", type=float, default=0.0)
    parser.add_argument("--grain-preservation", type=float, default=0.0)
    parser.add_argument("--shimmer-suppression", type=float, default=0.70)
    parser.add_argument("--prefer-nvof", action="store_true")
    parser.add_argument("--codec", choices=("H.264", "HEVC"), default="H.264")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute or args.ack != APP_EXPERIMENT_ACK:
        print(
            "BLOCKED: experimental application v10 video execution requires "
            f"--execute --ack {APP_EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2
    if args.start < 0:
        print("start must be non-negative", file=sys.stderr)
        return 2
    if args.duration is not None and args.duration <= 0:
        print("duration must be positive", file=sys.stderr)
        return 2

    backend = DLSS5V10ExperimentalBackend()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        stats = render_dlss5_v10(
            args.input.expanduser().resolve(),
            output,
            backend,
            scale=1.0,
            style=args.style,
            intensity=args.intensity,
            local_tone=args.local_tone,
            local_structure=args.local_structure,
            skin_structure=args.skin_structure,
            automatic_mask=args.automatic_mask,
            nr_passes=args.nr_passes,
            color_strength=args.color_strength,
            tone_preservation=args.tone_preservation,
            face_skin_protection=args.face_skin_protection,
            grain_preservation=args.grain_preservation,
            shimmer_suppression=args.shimmer_suppression,
            prefer_nvof=args.prefer_nvof,
            start=args.start,
            duration=args.duration,
            codec=args.codec,
        )
    except (OSError, ValueError, RuntimeError, InterruptedError) as exc:
        print(f"DLSS5 v10 experimental application render failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2, default=str))
    print(f"DLSS5_V10_APP_VIDEO_PASS output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
