"""CLI for real-video offline DLSS-G frame generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backends.dlssg import DLSSGBackend  # noqa: E402
from src.video.dlssg import render_dlssg  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 2X, 3X, or 4X video frames with NVOF + offline Ampere DLSS-G")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--community-runtime", type=Path, required=True)
    parser.add_argument("--official-runtime-dir", type=Path, required=True)
    parser.add_argument("--codec", default="h264_nvenc", choices=("h264_nvenc", "libx264"))
    parser.add_argument("--multiplier", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--terminal-frame-policy", default="duplicate", choices=("duplicate", "short"))
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--no-scene-cut-detection", action="store_true")
    parser.add_argument("--diagnostic-count", type=int, default=8)
    parser.add_argument("--quiet-worker-log", action="store_true")
    parser.add_argument("--diagnostics", action="store_true", help="Enable slow per-generated-frame validation and visual artifacts")
    args = parser.parse_args()
    backend = DLSSGBackend(args.worker, args.community_runtime, args.official_runtime_dir)
    result = render_dlssg(
        args.input,
        args.output,
        backend,
        codec=args.codec,
        preserve_audio=not args.no_audio,
        terminal_frame_policy=args.terminal_frame_policy,
        artifact_dir=args.artifact_dir,
        scene_cut_detection=not args.no_scene_cut_detection,
        diagnostic_count=args.diagnostic_count,
        diagnostic_callback=None if args.quiet_worker_log else lambda line: print(line, file=sys.stderr, flush=True),
        multiplier=args.multiplier,
        diagnostics=args.diagnostics,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
