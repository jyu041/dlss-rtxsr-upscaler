"""Run a bounded 16-frame real-video DLSS5 v10 temporal A/B experiment.

The same source-derived 256x256 RGBA8 frames are evaluated twice:
A) one persistent native Feature-18 session (reset on frame 0 only), and
B) a reset-every-frame control. The normal application backend remains disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_metrics import (  # noqa: E402
    comparison_metrics,
    effect_metrics,
    effect_observed,
)
from src.backends.dlss5_v10_client import (  # noqa: E402
    VIDEO_AB_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends.dlss5_v10_protocol import CreateRequest, FrameRequest  # noqa: E402
from src.backends.dlss5_v10_security import validate_preflight_report  # noqa: E402
from tools.validate_dlss5_v10_bounded import (  # noqa: E402
    assert_no_host_descendants,
    install_temporary_firewall_block,
    remove_temporary_firewall_block,
    validate_feature_result,
)


DEFAULT_RUNTIME = (
    ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
    / "bin" / "runtime" / "dlssnr"
)
DEFAULT_PREFLIGHT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"
DEFAULT_OUTPUT = ROOT / "runtime" / "audit" / "dlss5-v10-video-ab-hardware.json"
VIDEO_FRAME_COUNT = 16
DEFAULT_START_FRAME = 30


def preprocess_video_frame(frame_bgr: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    frame = np.asarray(frame_bgr, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("real-video v10 input frame must be BGR8")
    height, width = frame.shape[:2]
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    crop = frame[top:top + side, left:left + side]
    resized = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_AREA)
    rgba = cv2.cvtColor(resized, cv2.COLOR_BGR2RGBA)
    return rgba, {
        "left": int(left),
        "top": int(top),
        "width": int(side),
        "height": int(side),
    }


def decode_video_frames(
    input_path: Path,
    *,
    start_frame: int,
    count: int = VIDEO_FRAME_COUNT,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    if start_frame < 0:
        raise ValueError("start_frame must be non-negative")
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"could not open real-video input: {input_path}")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0 or fps <= 0:
            raise RuntimeError(
                f"invalid source metadata width={width} height={height} fps={fps}"
            )
        if total > 0 and start_frame + count > total:
            raise RuntimeError(
                f"real-video A/B requires frames {start_frame}.."
                f"{start_frame + count - 1}, source reports {total} total frames"
            )
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frames: list[np.ndarray] = []
        crop_box: dict[str, int] | None = None
        for offset in range(count):
            ok, frame_bgr = capture.read()
            if not ok or frame_bgr is None:
                raise RuntimeError(
                    f"failed to decode source frame {start_frame + offset}"
                )
            rgba, current_crop = preprocess_video_frame(frame_bgr)
            if crop_box is None:
                crop_box = current_crop
            frames.append(rgba)
        return frames, {
            "path": str(input_path.resolve()),
            "width": width,
            "height": height,
            "fps": fps,
            "reported_total_frames": total,
            "start_frame": start_frame,
            "frame_count": count,
            "preprocess": {
                "method": "center-square-crop-then-area-resize",
                "crop_box": crop_box,
                "output": [256, 256],
                "pixel_format": "rgba8",
            },
        }
    finally:
        capture.release()


def _create_request(gpu_ordinal: int) -> CreateRequest:
    return CreateRequest(
        256,
        256,
        gpu_ordinal=gpu_ordinal,
        processing_scale=1.0,
        style=0,
        intensity=1.0,
        nr_passes=1,
        local_tone=1.0,
        local_structure=1.0,
        skin_structure=-1.0,
        color_strength=1.0,
        tone_preservation=0.0,
        face_skin_protection=0.0,
        grain_preservation=0.0,
        shimmer_suppression=0.70,
        automatic_mask=False,
        prefer_nvof=False,
    )


def validate_video_hello(hello: dict[str, object], mode: str) -> None:
    expected = {
        "input": [256, 256],
        "processing_scale": 1.0,
        "max_frames": VIDEO_FRAME_COUNT,
    }
    if hello.get("bounded_contract") != expected:
        raise RuntimeError(
            f"real-video v10 {mode} host contract mismatch: "
            f"expected {expected}, got {hello.get('bounded_contract')!r}"
        )
    if hello.get("video_ab_mode") != mode:
        raise RuntimeError(
            f"real-video v10 HELLO mode mismatch: expected {mode!r}, "
            f"got {hello.get('video_ab_mode')!r}"
        )


def _validate_create(create: dict[str, object], gpu_ordinal: int, mode: str) -> None:
    if create.get("native_loaded") is not True:
        raise RuntimeError(f"real-video v10 {mode} CREATE did not load native runtime")
    if create.get("output_size") != [256, 256]:
        raise RuntimeError(
            f"real-video v10 {mode} CREATE output_size mismatch: "
            f"{create.get('output_size')!r}"
        )
    initialization = create.get("initialization", {})
    if not isinstance(initialization, dict):
        raise RuntimeError(f"real-video v10 {mode} initialization evidence is invalid")
    if initialization.get("bridge_abi_version") != 6:
        raise RuntimeError(f"real-video v10 {mode} requires bridge ABI 6")
    if initialization.get("gpu_ordinal") != gpu_ordinal:
        raise RuntimeError(
            f"real-video v10 {mode} GPU ordinal mismatch requested={gpu_ordinal} "
            f"initialized={initialization.get('gpu_ordinal')!r}"
        )
    gpu_name = str(initialization.get("gpu_name", ""))
    if "RTX 3070" not in gpu_name:
        raise RuntimeError(
            f"real-video v10 {mode} requires RTX 3070/3070 Ti, got {gpu_name!r}"
        )


def _run_session(
    mode: str,
    frames: list[np.ndarray],
    runtime: Path,
    preflight: Path,
    *,
    gpu_ordinal: int,
) -> tuple[dict[str, Any], list[np.ndarray]]:
    client = V10ProtocolClient(
        python=Path(sys.executable).resolve(),
        start_timeout=15.0,
        frame_timeout=45.0,
        close_grace=1.0,
    )
    result: dict[str, Any] = {
        "mode": mode,
        "status": "STARTED",
        "process_tree_checks": [],
        "frames": [],
    }
    rendered_frames: list[np.ndarray] = []
    output_hashes: set[str] = set()
    try:
        hello = client.start_native_video_ab_experimental(
            runtime,
            preflight,
            acknowledgement=VIDEO_AB_EXPERIMENT_ACK,
            mode=mode,
        )
        result["hello"] = hello
        validate_video_hello(hello, mode)
        result["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, f"{mode}_after_hello")
        )

        create = client.create(_create_request(gpu_ordinal))
        result["create"] = create
        _validate_create(create, gpu_ordinal, mode)
        result["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, f"{mode}_after_create")
        )

        for index, source in enumerate(frames):
            reset = True if mode == "reset-control" else index == 0
            started = time.perf_counter()
            output = client.process_frame(
                FrameRequest(timestamp=index, reset=reset, rgba=source.tobytes())
            )
            elapsed = time.perf_counter() - started
            validate_feature_result(output)
            if output.cuda_result != 0:
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} CUDA result "
                    f"{output.cuda_result}, expected 0"
                )
            if output.timestamp != index:
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} timestamp "
                    f"{output.timestamp}, expected {index}"
                )
            expected_scene_reset = 1 if reset else 0
            if output.scene_reset != expected_scene_reset:
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} scene_reset="
                    f"{output.scene_reset}, expected {expected_scene_reset}"
                )

            rendered = np.frombuffer(output.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
            metrics = effect_metrics(source, rendered)
            if not effect_observed(metrics):
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} did not show a "
                    "measurable Neural Rendering effect"
                )
            input_hash = hashlib.sha256(source.tobytes()).hexdigest().upper()
            output_hash = hashlib.sha256(output.rgba).hexdigest().upper()
            if input_hash == output_hash:
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} is byte-identical to input"
                )
            if output_hash in output_hashes:
                raise RuntimeError(
                    f"real-video v10 {mode} frame {index} repeated an earlier output hash"
                )
            output_hashes.add(output_hash)
            rendered_frames.append(rendered)
            result["frames"].append(
                {
                    "index": index,
                    "reset": reset,
                    "roundtrip_seconds": elapsed,
                    "ngx_create_result": output.ngx_create_result,
                    "ngx_evaluate_result": output.ngx_evaluate_result,
                    "cuda_result": output.cuda_result,
                    "scene_reset": output.scene_reset,
                    "scene_score": output.scene_score,
                    "effect_metrics": metrics,
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                }
            )
            result["process_tree_checks"].append(
                assert_no_host_descendants(client.pid, f"{mode}_after_frame_{index}")
            )

        result["unique_output_hashes"] = len(output_hashes)
        result["close"] = client.close()
        if result["close"] != "CLOSED":
            raise RuntimeError(
                f"real-video v10 {mode} host did not close cleanly: {result['close']}"
            )
        result["status"] = "PASS"
        return result, rendered_frames
    except BaseException:
        try:
            result["abort"] = client.abort()
        except Exception as abort_exc:
            result["abort_error"] = str(abort_exc)
        raise


def _pair_temporal_metrics(
    sources: list[np.ndarray],
    outputs: list[np.ndarray],
) -> dict[str, Any]:
    delta_mae: list[float] = []
    delta_rmse: list[float] = []
    residual_flicker_mae: list[float] = []
    for index in range(1, len(sources)):
        source_prev = sources[index - 1][..., :3].astype(np.float32)
        source_now = sources[index][..., :3].astype(np.float32)
        output_prev = outputs[index - 1][..., :3].astype(np.float32)
        output_now = outputs[index][..., :3].astype(np.float32)

        source_delta = source_now - source_prev
        output_delta = output_now - output_prev
        delta_error = output_delta - source_delta
        delta_mae.append(float(np.mean(np.abs(delta_error))))
        delta_rmse.append(float(np.sqrt(np.mean(np.square(delta_error)))))

        residual_prev = output_prev - source_prev
        residual_now = output_now - source_now
        residual_flicker_mae.append(
            float(np.mean(np.abs(residual_now - residual_prev)))
        )

    def summary(values: list[float]) -> dict[str, float]:
        array = np.asarray(values, dtype=np.float64)
        return {
            "mean": float(np.mean(array)),
            "median": float(np.median(array)),
            "max": float(np.max(array)),
        }

    return {
        "source_delta_error_mae": summary(delta_mae),
        "source_delta_error_rmse": summary(delta_rmse),
        "enhancement_residual_flicker_mae": summary(residual_flicker_mae),
    }


def _save_review_images(
    review_dir: Path,
    sources: list[np.ndarray],
    persistent: list[np.ndarray],
    reset_control: list[np.ndarray],
) -> list[str]:
    review_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for index in (0, len(sources) // 2, len(sources) - 1):
        triptych = np.concatenate(
            [
                sources[index][..., :3],
                persistent[index][..., :3],
                reset_control[index][..., :3],
            ],
            axis=1,
        )
        path = review_dir / f"frame-{index:02d}-source-persistent-reset.png"
        Image.fromarray(triptych).save(path)
        saved.append(str(path.resolve()))
    return saved


def run_video_ab(
    input_path: Path,
    runtime: Path,
    preflight: Path,
    *,
    gpu_ordinal: int,
    start_frame: int,
    review_dir: Path,
) -> dict[str, Any]:
    preflight_evidence = validate_preflight_report(runtime, preflight)
    frames, source = decode_video_frames(
        input_path,
        start_frame=start_frame,
        count=VIDEO_FRAME_COUNT,
    )
    python = Path(sys.executable).resolve()
    rule_name = f"NVE DLSS5 v10 real-video AB {__import__('os').getpid()}"
    firewall_installed = False
    started = time.perf_counter()

    report: dict[str, Any] = {
        "schema": 1,
        "status": "STARTED",
        "native_executed": False,
        "normal_backend_changed": False,
        "runtime": str(runtime.resolve()),
        "preflight": str(preflight.resolve()),
        "preflight_age_seconds": preflight_evidence.get("preflight_age_seconds"),
        "defender": preflight_evidence.get("malware_scan"),
        "python": str(python),
        "gpu_ordinal": gpu_ordinal,
        "dimensions": [256, 256],
        "processing_scale": 1.0,
        "frame_count": VIDEO_FRAME_COUNT,
        "source": source,
        "firewall_rule": rule_name,
    }

    try:
        install_temporary_firewall_block(python, rule_name)
        firewall_installed = True
        report["firewall_installed"] = True

        persistent_report, persistent_frames = _run_session(
            "persistent",
            frames,
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        reset_report, reset_frames = _run_session(
            "reset-control",
            frames,
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        report["native_executed"] = True
        report["persistent"] = persistent_report
        report["reset_control"] = reset_report

        comparisons = [
            comparison_metrics(persistent_frames[index], reset_frames[index])
            for index in range(VIDEO_FRAME_COUNT)
        ]
        report["persistent_vs_reset"] = comparisons
        report["frame0_identical"] = bool(comparisons[0]["identical"])
        nonfirst_changed = [
            index
            for index, metrics in enumerate(comparisons[1:], start=1)
            if not metrics["identical"]
        ]
        report["state_influence_frame_ids"] = nonfirst_changed
        report["state_influence_observed"] = bool(nonfirst_changed)
        if not report["frame0_identical"]:
            raise RuntimeError(
                "real-video v10 A/B baseline frame 0 differed between fresh reset sessions"
            )
        if not report["state_influence_observed"]:
            raise RuntimeError(
                "real-video v10 persistent outputs were byte-identical to reset control "
                "for every non-initial frame"
            )

        persistent_temporal = _pair_temporal_metrics(frames, persistent_frames)
        reset_temporal = _pair_temporal_metrics(frames, reset_frames)
        report["temporal_metrics"] = {
            "persistent": persistent_temporal,
            "reset_control": reset_temporal,
            "persistent_minus_reset": {
                "source_delta_error_mae_mean": (
                    persistent_temporal["source_delta_error_mae"]["mean"]
                    - reset_temporal["source_delta_error_mae"]["mean"]
                ),
                "source_delta_error_rmse_mean": (
                    persistent_temporal["source_delta_error_rmse"]["mean"]
                    - reset_temporal["source_delta_error_rmse"]["mean"]
                ),
                "enhancement_residual_flicker_mae_mean": (
                    persistent_temporal["enhancement_residual_flicker_mae"]["mean"]
                    - reset_temporal["enhancement_residual_flicker_mae"]["mean"]
                ),
            },
        }
        report["review_images"] = _save_review_images(
            review_dir,
            frames,
            persistent_frames,
            reset_frames,
        )
        report["status"] = "PASS"
        return report
    except BaseException as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
        return report
    finally:
        report["total_seconds"] = time.perf_counter() - started
        if firewall_installed:
            try:
                remove_temporary_firewall_block(rule_name)
                report["firewall_removed"] = True
            except Exception as exc:
                report["firewall_removed"] = False
                report["firewall_remove_error"] = str(exc)
                report["status"] = "FAIL"
                report.setdefault(
                    "error",
                    "real-video v10 A/B firewall cleanup failed; remove the temporary rule manually",
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review-dir", type=Path)
    parser.add_argument("--gpu-ordinal", type=int, default=0)
    parser.add_argument("--start-frame", type=int, default=DEFAULT_START_FRAME)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute or args.ack != VIDEO_AB_EXPERIMENT_ACK:
        print(
            "BLOCKED: bounded real-video v10 A/B execution requires --execute "
            f"--ack {VIDEO_AB_EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2
    output = args.output.expanduser().resolve()
    review_dir = (
        args.review_dir.expanduser().resolve()
        if args.review_dir
        else output.with_suffix("").with_name(output.stem + "-review")
    )
    report = run_video_ab(
        args.input.expanduser().resolve(),
        args.runtime.expanduser().resolve(),
        args.preflight.expanduser().resolve(),
        gpu_ordinal=args.gpu_ordinal,
        start_frame=args.start_frame,
        review_dir=review_dir,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
