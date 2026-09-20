"""Hardware A/B harness for DLSS5 quality/performance experiments.

This tool is intentionally outside pytest. It decodes a bounded real-video
window once, runs a small matrix through the approved v3 Feature-18 backend,
records per-stage timings and temporal-residual stability, and writes review
videos plus a JSON report. It never changes the validated default settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
import subprocess
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5 import DLSS5Backend  # noqa: E402
from src.backends.dlss5_quality import resolve_working_scale  # noqa: E402
from src.core.media_info import probe  # noqa: E402
from src.core.process_utils import tool  # noqa: E402


def _read_exact(stream, size: int) -> bytes:
    data = bytearray(size)
    view = memoryview(data)
    offset = 0
    while offset < size:
        count = stream.readinto(view[offset:])
        if not count:
            break
        offset += count
    if offset == 0:
        return b""
    if offset != size:
        raise RuntimeError(f"truncated source frame: {offset} of {size} bytes")
    return bytes(data)


def decode_window(path: Path, *, start: float, frames: int) -> tuple[list[np.ndarray], float]:
    ffmpeg = tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    info = probe(str(path))
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    command = [ffmpeg, "-v", "error"]
    if start:
        command += ["-ss", str(max(0.0, start))]
    command += ["-i", str(path), "-frames:v", str(frames), "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    frame_bytes = width * height * 4
    decoded: list[np.ndarray] = []
    while len(decoded) < frames:
        raw = _read_exact(process.stdout, frame_bytes)
        if not raw:
            break
        decoded.append(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4).copy())
    process.wait(timeout=60)
    if process.returncode:
        details = (process.stderr.read() if process.stderr else b"").decode(errors="replace")
        raise RuntimeError(details[-2000:])
    if len(decoded) < 2:
        raise RuntimeError("quality benchmark needs at least two decoded frames")
    return decoded, fps


def _warp_previous_residual(
    previous_source: np.ndarray,
    current_source: np.ndarray,
    previous_residual: np.ndarray,
) -> np.ndarray:
    height, width = current_source.shape[:2]
    flow_width = max(32, width // 4)
    flow_height = max(32, height // 4)
    curr = cv2.resize(current_source[..., :3], (flow_width, flow_height), interpolation=cv2.INTER_AREA)
    prev = cv2.resize(previous_source[..., :3], (flow_width, flow_height), interpolation=cv2.INTER_AREA)
    flow = cv2.calcOpticalFlowFarneback(
        cv2.cvtColor(curr, cv2.COLOR_RGB2GRAY),
        cv2.cvtColor(prev, cv2.COLOR_RGB2GRAY),
        None,
        0.5,
        3,
        15,
        3,
        5,
        1.1,
        0,
    )
    flow = cv2.resize(flow, (width, height), interpolation=cv2.INTER_LINEAR)
    flow[..., 0] *= width / flow_width
    flow[..., 1] *= height / flow_height
    x, y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    return cv2.remap(
        previous_residual,
        x + flow[..., 0],
        y + flow[..., 1],
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def quality_metrics(source: list[np.ndarray], output: list[np.ndarray]) -> dict[str, float | None]:
    if len(source) != len(output):
        raise ValueError("source/output frame counts differ")
    effect = []
    temporal = []
    for index, (src, out) in enumerate(zip(source, output)):
        src_rgb = src[..., :3].astype(np.float32)
        out_rgb = out[..., :3].astype(np.float32)
        residual = out_rgb - src_rgb
        effect.append(float(np.abs(residual).mean()))
        if index:
            prev_src = source[index - 1]
            prev_residual = output[index - 1][..., :3].astype(np.float32) - prev_src[..., :3].astype(np.float32)
            warped = _warp_previous_residual(prev_src, src, prev_residual)
            temporal.append(float(np.abs(residual - warped).mean()))
    return {
        "effect_mae": mean(effect) if effect else None,
        "motion_compensated_residual_flicker_mae": mean(temporal) if temporal else None,
    }


def _write_review(path: Path, frames: list[np.ndarray], fps: float) -> None:
    ffmpeg = tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    height, width = frames[0].shape[:2]
    process = subprocess.Popen(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    for frame in frames:
        process.stdin.write(np.ascontiguousarray(frame[..., :3]).tobytes())
    process.stdin.close()
    process.wait(timeout=120)
    if process.returncode:
        details = (process.stderr.read() if process.stderr else b"").decode(errors="replace")
        raise RuntimeError(f"review encode failed: {details[-2000:]}")


def _slug(value: object) -> str:
    return str(value).replace(".", "p").replace("/", "-").replace(" ", "-")


def run_case(
    backend: DLSS5Backend,
    source: list[np.ndarray],
    *,
    working_scale: float | str,
    shimmer: float,
    color_strength: float,
    tone_preservation: float,
    recompose_backend: str,
) -> tuple[list[np.ndarray], dict]:
    height, width = source[0].shape[:2]
    telemetry: dict = {}
    options = backend.options(upscaling_mode=1.0, motion_mode="optical_flow")
    rendered = backend.process_frames(
        source,
        width=width,
        height=height,
        frame_count=len(source),
        options=options,
        nr_working_scale=working_scale,
        telemetry=telemetry,
        recompose_backend=recompose_backend,
        shimmer_suppression=shimmer,
        color_strength=color_strength,
        tone_preservation=tone_preservation,
    )
    started = time.perf_counter()
    outputs = [frame.copy() for frame, _ in rendered]
    wall = time.perf_counter() - started
    metadata = telemetry.get("frames", [])
    resolved = telemetry.get("nr_working_scale_resolved")
    return outputs, {
        "working_scale_requested": working_scale,
        "working_scale_resolved": resolved,
        "working_resolution": [
            int(round(width * float(resolved))) if resolved else width,
            int(round(height * float(resolved))) if resolved else height,
        ],
        "shimmer_suppression": shimmer,
        "color_strength": color_strength,
        "tone_preservation": tone_preservation,
        "recompose_backend": telemetry.get("recompose_backend_used", "bypassed"),
        "wall_seconds": wall,
        "fps": len(outputs) / max(wall, 1e-9),
        "processing_loop_mean_ms": mean(float(item.get("processing_loop_ms", 0.0)) for item in metadata) if metadata else None,
        "feature_submit_mean_ms": mean(float(item.get("feature_submit_ms", 0.0)) for item in metadata) if metadata else None,
        "quality_compose_mean_ms": mean(float(item.get("quality_compose_ms", 0.0)) for item in metadata) if metadata else 0.0,
        "quality_flow_mean_ms": mean(float(item.get("quality_temporal_flow_ms", 0.0)) for item in metadata) if metadata else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runtime" / "audit" / "dlss5-quality")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--working-scales", default="1.0,auto,0.875,0.75,0.6666666667,0.5")
    parser.add_argument("--temporal-scale", default="0.75")
    parser.add_argument("--shimmer-levels", default="0.25,0.5,0.75")
    parser.add_argument("--recompose-backend", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--no-reviews", action="store_true")
    args = parser.parse_args()
    if args.frames < 2:
        parser.error("--frames must be at least 2")

    source_path = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source, fps = decode_window(source_path, start=args.start, frames=args.frames)
    height, width = source[0].shape[:2]
    backend = DLSS5Backend()
    if not backend.available:
        raise RuntimeError(f"DLSS5 v3 backend is not ready: {backend.reason}")

    cases: list[dict] = []
    definitions: list[tuple[str, float | str, float, float, float]] = []
    for token in args.working_scales.split(","):
        token = token.strip()
        scale: float | str = "auto" if token.lower() == "auto" else float(token)
        if scale != "auto":
            resolve_working_scale(scale, width, height)
        definitions.append((f"scale-{_slug(scale)}", scale, 0.0, 1.0, 0.0))
    temporal_scale = float(args.temporal_scale)
    for token in args.shimmer_levels.split(","):
        value = float(token)
        definitions.append((f"shimmer-{_slug(value)}", temporal_scale, value, 1.0, 0.0))
    definitions.append(("detail-only", temporal_scale, 0.5, 0.0, 1.0))

    for name, scale, shimmer, color_strength, tone_preservation in definitions:
        outputs, result = run_case(
            backend,
            source,
            working_scale=scale,
            shimmer=shimmer,
            color_strength=color_strength,
            tone_preservation=tone_preservation,
            recompose_backend=args.recompose_backend,
        )
        result["name"] = name
        result.update(quality_metrics(source, outputs))
        digest = hashlib.sha256()
        for frame in outputs:
            digest.update(memoryview(np.ascontiguousarray(frame)))
        result["raw_output_sha256"] = digest.hexdigest().upper()
        if not args.no_reviews:
            review = output_dir / f"{name}.mp4"
            _write_review(review, outputs, fps)
            result["review"] = str(review)
        cases.append(result)
        print(
            f"{name}: {result['fps']:.2f} FPS; "
            f"effect={result['effect_mae']:.3f}; "
            f"temporal={result['motion_compensated_residual_flicker_mae']:.3f}"
        )

    report = {
        "schema_version": 1,
        "input": str(source_path),
        "source_geometry": [width, height],
        "source_fps": fps,
        "start_seconds": args.start,
        "frames": len(source),
        "cases": cases,
        "note": "No case changes application defaults; review quality before promoting any experimental setting.",
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"DLSS5_QUALITY_MATRIX_PASS report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
