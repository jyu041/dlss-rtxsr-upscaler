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
from src.core.mfg_quality import withheld_groups  # noqa: E402
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
ALLOWED_GEOMETRIES = {(1280, 720), (1920, 1080)}


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


def decode_source(path: Path, required_frames: int) -> tuple[list[np.ndarray], float]:
    frames: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or stream.base_rate or 0)
        for frame in container.decode(stream):
            frames.append(frame.to_ndarray(format="rgba"))
            if len(frames) >= required_frames:
                break
    if len(frames) < required_frames:
        raise RuntimeError(
            f"source has only {len(frames)} decoded frames; need at least {required_frames}"
        )
    if fps <= 0:
        raise RuntimeError("source frame rate is unavailable")
    shape = frames[0].shape
    if any(frame.shape != shape for frame in frames):
        raise RuntimeError("source changes geometry during the requested capture")
    height, width = shape[:2]
    if (width, height) not in ALLOWED_GEOMETRIES:
        raise RuntimeError(
            f"quality A/B is currently bounded to 1280x720 or 1920x1080, got {width}x{height}"
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
    Image.fromarray(rgba, mode="RGBA").save(path)


def _save_rgba_bytes(path: Path, payload: bytes, width: int, height: int) -> None:
    expected = width * height * 4
    if len(payload) != expected:
        raise RuntimeError(f"generated frame is {len(payload)} bytes; expected {expected}")
    rgba = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 4)
    _save_rgba(path, rgba)


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
    generated_root = output_root / f"grid{grid}" / "generated"
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
                            "reference": ref.relative_to(output_root).as_posix(),
                            "generated": generated.relative_to(output_root).as_posix(),
                        }
                    )

    manifest = output_root / f"grid{grid}" / "manifest.json"
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--multiplier", type=int, choices=(2, 4), required=True)
    parser.add_argument("--groups", type=int, default=8)
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not 1 <= args.groups <= 24:
        raise SystemExit("--groups must be between 1 and 24")

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"input not found: {input_path}")

    identities = validate_identities(args.worker, args.runtime, args.official)
    required_frames = args.groups * args.multiplier + 1
    frames, fps = decode_source(input_path, required_frames)
    output_root = args.output_dir.expanduser().resolve()
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

    height, width = frames[0].shape[:2]
    combined = {
        "schema_version": 2,
        "status": "PASS",
        "purpose": "quality evidence only; no promotion decision",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "input_fps": fps,
        "width": width,
        "height": height,
        "multiplier": args.multiplier,
        "groups": args.groups,
        **identities,
        "grid1_summary": reports["grid1"]["summary"],
        "grid4_summary": reports["grid4"]["summary"],
        "quality_delta": _quality_delta(reports["grid1"], reports["grid4"]),
        "paired_quality": _paired_quality(reports["grid1"], reports["grid4"]),
    }
    combined_path = output_root / "grid-ab-quality-report.json"
    combined_path.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(combined, indent=2))
    print(f"QUALITY_AB_PASS evidence={combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
