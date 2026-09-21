"""Capture and score a same-source NVOF grid-1 versus grid-4 MFG quality A/B.

Research-only.  This tool runs the isolated instrumented worker twice against
identical high-frame-rate source anchors.  Intermediate real source frames are
withheld as ground truth, then compared with the generated frames.

The normal application pipeline and production C55 worker are not modified.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Iterator

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import (  # noqa: E402
    DlssgWorker,
    MOTION_MODE_NVIDIA_OPTICAL_FLOW,
)
from src.core.mfg_quality import temporal_delta_metrics, withheld_groups  # noqa: E402
from tools.score_mfg_withheld import score_manifest  # noqa: E402

INSTRUMENTED_ROOT = (
    ROOT / "native" / "dlssg_sm86_offline" / "bin-instrumented"
).resolve()
DEFAULT_WORKER = INSTRUMENTED_ROOT / "dlssg_sm86_offline.exe"
DEFAULT_RUNTIME = (ROOT / "runtime" / "dlssg" / "legacy" / "version.dll").resolve()
DEFAULT_OFFICIAL = (ROOT / "runtime" / "dlssg" / "official").resolve()
DEFAULT_OUTPUT = (ROOT / "runtime" / "quality" / "mfg-grid-ab").resolve()

PRODUCTION_C55_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
LEGACY_RUNTIME_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
OFFICIAL_PROVIDER_SHA256 = "FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82"
ALLOWED_GEOMETRIES = {(640, 480), (1280, 720), (1920, 1080)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def validate_identities(worker: Path, runtime: Path, official: Path) -> dict[str, str]:
    worker = worker.resolve()
    runtime = runtime.resolve()
    official = official.resolve()
    provider = official / "nvngx_dlssg.dll"

    if not worker.is_file():
        raise RuntimeError(f"instrumented worker is missing: {worker}")
    try:
        worker.relative_to(INSTRUMENTED_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"worker must be under {INSTRUMENTED_ROOT}") from exc

    worker_sha = sha256_file(worker)
    if worker_sha == PRODUCTION_C55_SHA256:
        raise RuntimeError("quality capture refuses the pinned production C55 worker")
    if not runtime.is_file() or sha256_file(runtime) != LEGACY_RUNTIME_SHA256:
        raise RuntimeError("legacy community runtime identity is missing or changed")
    if not provider.is_file() or sha256_file(provider) != OFFICIAL_PROVIDER_SHA256:
        raise RuntimeError("pinned NVIDIA provider identity is missing or changed")
    return {
        "worker_sha256": worker_sha,
        "community_runtime_sha256": LEGACY_RUNTIME_SHA256,
        "official_provider_sha256": OFFICIAL_PROVIDER_SHA256,
    }


def decode_source(
    path: Path,
    required_frames: int,
    *,
    start_frame: int = 0,
) -> tuple[list[np.ndarray], float]:
    frames: list[np.ndarray] = []
    with av.open(str(path), metadata_errors="replace") as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or stream.base_rate or 0)
        for decoded_index, frame in enumerate(container.decode(stream)):
            if decoded_index < start_frame:
                continue
            frames.append(frame.to_ndarray(format="rgba"))
            if len(frames) >= required_frames:
                break
    if len(frames) < required_frames:
        raise RuntimeError(
            f"source segment starting at frame {start_frame} yielded only "
            f"{len(frames)} decoded frames; need at least {required_frames}"
        )
    if fps <= 0:
        raise RuntimeError("source frame rate is unavailable")
    shape = frames[0].shape
    if any(frame.shape != shape for frame in frames):
        raise RuntimeError("source changes geometry during the requested capture")
    height, width = shape[:2]
    if (width, height) not in ALLOWED_GEOMETRIES:
        raise RuntimeError(
            f"quality A/B is currently bounded to 640x480, 1280x720, or 1920x1080, got {width}x{height}"
        )
    return frames, fps


@contextmanager
def nvof_grid_environment(grid: int) -> Iterator[None]:
    keys = {
        "DLSSG_NVOF_DIRECTION": "forward",
        "DLSSG_NVOF_GPU_FLOW": "1",
        "DLSSG_NVOF_OUTPUT_GRID": str(grid),
    }
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _save_rgba(path: Path, rgba: np.ndarray) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba).save(path)


def _manifest_relative(path: Path, manifest_dir: Path) -> str:
    return Path(os.path.relpath(path.resolve(), manifest_dir.resolve())).as_posix()


def _save_rgba_bytes(path: Path, payload: bytes, width: int, height: int) -> None:
    expected = width * height * 4
    if len(payload) != expected:
        raise RuntimeError(f"generated frame is {len(payload)} bytes; expected {expected}")
    rgba = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    _save_rgba(path, rgba)


def _load_rgba(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def require_grid_selected(client: DlssgWorker, grid: int, timeout: float = 2.0) -> None:
    marker = f"NVOF_OUTPUT_GRID_SELECTED={grid} "
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(marker in line for line in client.diagnostics):
            return
        time.sleep(0.01)
    tail = " | ".join(client.diagnostics[-20:])
    raise RuntimeError(
        f"worker did not confirm requested NVOF output grid {grid}; diagnostics: {tail}"
    )


def capture_grid(
    *,
    grid: int,
    frames: list[np.ndarray],
    multiplier: int,
    groups: int,
    worker: Path,
    runtime: Path,
    official: Path,
    output_root: Path,
) -> Path:
    height, width = frames[0].shape[:2]
    plan = withheld_groups(len(frames), multiplier)[:groups]
    if len(plan) != groups:
        raise RuntimeError(f"withheld plan produced {len(plan)} groups; expected {groups}")

    references = output_root / "references"
    manifest_root = output_root / f"grid{grid}"
    generated_root = manifest_root / "generated"
    samples: list[dict[str, object]] = []

    # Write references once. Both grid modes point at this same immutable set.
    for item in plan:
        group = int(item["group"])
        for generated_index, source_index in enumerate(item["withheld"], start=1):
            ref = references / f"g{group:03d}_i{generated_index}.png"
            if not ref.exists():
                _save_rgba(ref, frames[int(source_index)])

    with nvof_grid_environment(grid):
        with DlssgWorker(
            worker.resolve(),
            runtime.resolve(),
            official.resolve(),
            expected_community_sha256=LEGACY_RUNTIME_SHA256,
            strict_runtime_hash=True,
            diagnostic_mode=False,
        ) as client:
            client.create(
                width,
                height,
                multiplier=multiplier,
                motion_mode=MOTION_MODE_NVIDIA_OPTICAL_FLOW,
            )
            require_grid_selected(client, grid)
            bootstrap = client.process(0, frames[0].tobytes(), reset=True)
            if not bootstrap.reset_only or bootstrap.outputs:
                raise RuntimeError("quality capture bootstrap unexpectedly generated output")

            for item in plan:
                group = int(item["group"])
                right_anchor = int(item["right_anchor"])
                result = client.process(group + 1, frames[right_anchor].tobytes())
                if result.generated_count != multiplier - 1:
                    raise RuntimeError(
                        f"group {group} generated {result.generated_count}; expected {multiplier - 1}"
                    )
                for generated_index, payload in enumerate(result.outputs, start=1):
                    ref = references / f"g{group:03d}_i{generated_index}.png"
                    generated = generated_root / f"g{group:03d}_i{generated_index}.png"
                    _save_rgba_bytes(generated, payload, width, height)
                    samples.append(
                        {
                            "group": group,
                            "generated_index": generated_index,
                            "reference": _manifest_relative(ref, manifest_root),
                            "generated": _manifest_relative(generated, manifest_root),
                        }
                    )

    manifest = manifest_root / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "multiplier": multiplier,
                "nvof_output_grid": grid,
                "samples": samples,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def _quality_delta(grid1: dict[str, object], grid4: dict[str, object]) -> dict[str, float | None]:
    left = grid1["summary"]["overall"]
    right = grid4["summary"]["overall"]

    def delta(key: str) -> float | None:
        a = left.get(key)
        b = right.get(key)
        if a is None or b is None:
            return None
        return float(b) - float(a)

    return {
        "grid4_minus_grid1_mean_mae": delta("mean_mae"),
        "grid4_minus_grid1_mean_rmse": delta("mean_rmse"),
        "grid4_minus_grid1_mean_psnr_db": delta("mean_psnr_db"),
        "grid4_minus_grid1_mean_ssim_rgb": delta("mean_ssim_rgb"),
        "grid4_minus_grid1_mean_edge_mae": delta("mean_edge_mae"),
    }


def _paired_quality(grid1: dict[str, object], grid4: dict[str, object]) -> dict[str, object]:
    left = {
        (int(row["group"]), int(row["generated_index"])): row
        for row in grid1["samples"]
    }
    right = {
        (int(row["group"]), int(row["generated_index"])): row
        for row in grid4["samples"]
    }
    if set(left) != set(right):
        raise RuntimeError("grid quality reports do not contain identical sample keys")

    rows: list[dict[str, object]] = []
    lower_is_better = ("mae", "rmse", "edge_mae")
    higher_is_better = ("psnr_db", "ssim_rgb")
    wins = {metric: {"grid1": 0, "grid4": 0, "tie": 0, "comparable": 0}
            for metric in (*lower_is_better, *higher_is_better)}

    for key in sorted(left):
        a = left[key]
        b = right[key]
        delta: dict[str, float | None] = {}
        for metric in (*lower_is_better, *higher_is_better):
            av = a.get(metric)
            bv = b.get(metric)
            if av is None or bv is None:
                delta[metric] = None
                continue
            avf, bvf = float(av), float(bv)
            delta[metric] = bvf - avf
            bucket = wins[metric]
            bucket["comparable"] += 1
            if abs(avf - bvf) <= 1e-12:
                bucket["tie"] += 1
            elif metric in lower_is_better:
                bucket["grid1" if avf < bvf else "grid4"] += 1
            else:
                bucket["grid1" if avf > bvf else "grid4"] += 1
        rows.append(
            {
                "group": key[0],
                "generated_index": key[1],
                "grid4_minus_grid1": delta,
            }
        )
    return {"samples": rows, "wins": wins}


def evidence_root(
    base_output: Path,
    input_path: Path,
    input_sha: str,
    multiplier: int,
    start_frame: int,
) -> Path:
    source_tag = f"{input_path.stem[:32]}-{input_sha[:12]}"
    return (
        base_output.expanduser().resolve()
        / source_tag
        / f"{multiplier}x"
        / f"start-{start_frame:08d}"
    )


def _review_candidates(
    grid1: dict[str, object],
    grid4: dict[str, object],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    left = {
        (int(row["group"]), int(row["generated_index"])): row
        for row in grid1["samples"]
    }
    right = {
        (int(row["group"]), int(row["generated_index"])): row
        for row in grid4["samples"]
    }
    if set(left) != set(right):
        raise RuntimeError("grid quality reports do not contain identical sample keys")

    ranked = []
    for key in sorted(left):
        a, b = left[key], right[key]
        edge_delta = None
        if a.get("edge_mae") is not None and b.get("edge_mae") is not None:
            edge_delta = float(b["edge_mae"]) - float(a["edge_mae"])
        ssim_delta = float(b["ssim_rgb"]) - float(a["ssim_rgb"])
        mae_delta = float(b["mae"]) - float(a["mae"])
        ranked.append(
            {
                "group": key[0],
                "generated_index": key[1],
                "reference": b["reference"],
                "grid1_generated": a["generated"],
                "grid4_generated": b["generated"],
                "grid4_minus_grid1_edge_mae": edge_delta,
                "grid4_minus_grid1_ssim_rgb": ssim_delta,
                "grid4_minus_grid1_mae": mae_delta,
            }
        )

    # Prefer reference-edge regressions, then global SSIM/MAE regressions.
    def severity(row: dict[str, object]) -> tuple[float, float, float]:
        edge = row["grid4_minus_grid1_edge_mae"]
        return (
            float(edge) if edge is not None else float("-inf"),
            -float(row["grid4_minus_grid1_ssim_rgb"]),
            float(row["grid4_minus_grid1_mae"]),
        )

    ranked.sort(key=severity, reverse=True)
    return ranked[:limit]


def _temporal_report(
    frames: list[np.ndarray],
    report: dict[str, object],
    *,
    multiplier: int,
    groups: int,
) -> dict[str, object]:
    generated_by_source: dict[int, np.ndarray] = {}
    for row in report["samples"]:
        group = int(row["group"])
        generated_index = int(row["generated_index"])
        source_index = group * multiplier + generated_index
        generated_by_source[source_index] = _load_rgba(Path(str(row["generated"])))

    last_index = groups * multiplier
    candidate_frames: list[np.ndarray] = []
    for source_index in range(last_index + 1):
        if source_index % multiplier == 0:
            candidate_frames.append(frames[source_index])
        else:
            candidate = generated_by_source.get(source_index)
            if candidate is None:
                raise RuntimeError(
                    f"missing generated temporal frame for source index {source_index}"
                )
            candidate_frames.append(candidate)

    rows = []
    for source_index in range(1, last_index + 1):
        metrics = temporal_delta_metrics(
            frames[source_index - 1],
            frames[source_index],
            candidate_frames[source_index - 1],
            candidate_frames[source_index],
        )
        rows.append({"source_index": source_index, **metrics})

    mae_values = np.asarray([row["temporal_delta_mae"] for row in rows], dtype=np.float64)
    rmse_values = np.asarray([row["temporal_delta_rmse"] for row in rows], dtype=np.float64)
    return {
        "count": len(rows),
        "mean_temporal_delta_mae": float(np.mean(mae_values)),
        "p95_temporal_delta_mae": float(np.percentile(mae_values, 95)),
        "max_temporal_delta_mae": float(np.max(mae_values)),
        "mean_temporal_delta_rmse": float(np.mean(rmse_values)),
        "transitions": rows,
    }


def _write_review_pack(
    output_root: Path,
    candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    from PIL import Image, ImageDraw

    review_root = output_root / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, object]] = []
    for rank, candidate in enumerate(candidates, start=1):
        reference = Image.open(candidate["reference"]).convert("RGB")
        grid1 = Image.open(candidate["grid1_generated"]).convert("RGB")
        grid4 = Image.open(candidate["grid4_generated"]).convert("RGB")
        if not (reference.size == grid1.size == grid4.size):
            raise RuntimeError("review candidate images do not share geometry")

        width, height = reference.size
        canvas = Image.new("RGB", (width * 3, height + 42))
        draw = ImageDraw.Draw(canvas)
        canvas.paste(reference, (0, 42))
        canvas.paste(grid1, (width, 42))
        canvas.paste(grid4, (width * 2, 42))
        draw.text((12, 12), "REFERENCE", fill="white")
        draw.text((width + 12, 12), "GRID 1", fill="white")
        draw.text((width * 2 + 12, 12), "GRID 4", fill="white")

        name = (
            f"{rank:02d}-g{int(candidate['group']):03d}"
            f"-i{int(candidate['generated_index'])}.jpg"
        )
        path = review_root / name
        canvas.save(path, quality=94, subsampling=0)
        written.append(
            {
                **candidate,
                "rank": rank,
                "review_image": path.relative_to(output_root).as_posix(),
            }
        )
        reference.close()
        grid1.close()
        grid4.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--multiplier", type=int, choices=(2, 4), required=True)
    parser.add_argument("--groups", type=int, default=8)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.groups <= 24:
        raise SystemExit("--groups must be between 1 and 24")
    if not 0 <= args.start_frame <= 1_000_000:
        raise SystemExit("--start-frame must be between 0 and 1000000")

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"input not found: {input_path}")

    required_frames = args.groups * args.multiplier + 1
    frames, fps = decode_source(
        input_path, required_frames, start_frame=args.start_frame
    )
    height, width = frames[0].shape[:2]
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "PREFLIGHT_PASS",
                    "input": str(input_path),
                    "input_fps": fps,
                    "width": width,
                    "height": height,
                    "multiplier": args.multiplier,
                    "groups": args.groups,
                    "start_frame": args.start_frame,
                    "required_frames": required_frames,
                    "anchor_fps": fps / args.multiplier,
                    "source_frame_interval_ms": 1000.0 / fps,
                    "anchor_interval_ms": 1000.0 * args.multiplier / fps,
                },
                indent=2,
            )
        )
        return 0

    identities = validate_identities(args.worker, args.runtime, args.official)
    input_sha = sha256_file(input_path)
    output_root = evidence_root(
        args.output_dir,
        input_path,
        input_sha,
        args.multiplier,
        args.start_frame,
    )
    output_root.mkdir(parents=True, exist_ok=True)

    reports: dict[str, dict[str, object]] = {}
    for grid in (1, 4):
        print(f"CAPTURE_START grid={grid}", flush=True)
        manifest = capture_grid(
            grid=grid,
            frames=frames,
            multiplier=args.multiplier,
            groups=args.groups,
            worker=args.worker,
            runtime=args.runtime,
            official=args.official,
            output_root=output_root,
        )
        report = score_manifest(manifest)
        report_path = output_root / f"grid{grid}" / "report.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        reports[f"grid{grid}"] = report
        print(f"CAPTURE_PASS grid={grid} report={report_path}", flush=True)

    temporal = {
        "grid1": _temporal_report(
            frames, reports["grid1"], multiplier=args.multiplier, groups=args.groups
        ),
        "grid4": _temporal_report(
            frames, reports["grid4"], multiplier=args.multiplier, groups=args.groups
        ),
    }
    temporal["grid4_minus_grid1_mean_temporal_delta_mae"] = (
        temporal["grid4"]["mean_temporal_delta_mae"]
        - temporal["grid1"]["mean_temporal_delta_mae"]
    )
    review_candidates = _review_candidates(reports["grid1"], reports["grid4"])
    review_pack = _write_review_pack(output_root, review_candidates)

    combined = {
        "schema_version": 2,
        "status": "PASS",
        "purpose": "quality evidence only; no promotion decision",
        "input": str(input_path),
        "input_sha256": input_sha,
        "input_fps": fps,
        "width": width,
        "height": height,
        "multiplier": args.multiplier,
        "groups": args.groups,
        "start_frame": args.start_frame,
        "end_frame_inclusive": args.start_frame + required_frames - 1,
        "evidence_root": str(output_root),
        "source_frame_interval_ms": 1000.0 / fps,
        "anchor_fps": fps / args.multiplier,
        "anchor_interval_ms": 1000.0 * args.multiplier / fps,
        "temporal_sampling_note": (
            "anchor cadence is below 25 fps; interpret this as a coarse-temporal "
            "stress test rather than a 30-fps-anchor production proxy"
            if fps / args.multiplier < 25.0
            else "anchor cadence is at least 25 fps"
        ),
        **identities,
        "grid1_summary": reports["grid1"]["summary"],
        "grid4_summary": reports["grid4"]["summary"],
        "quality_delta": _quality_delta(reports["grid1"], reports["grid4"]),
        "paired_quality": _paired_quality(reports["grid1"], reports["grid4"]),
        "temporal_quality": temporal,
        "review_candidates": review_pack,
    }
    combined_path = output_root / "grid-ab-quality-report.json"
    combined_path.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(combined, indent=2))
    print(f"QUALITY_AB_PASS evidence={combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
