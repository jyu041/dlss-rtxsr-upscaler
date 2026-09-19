"""Run a bounded 128-frame DLSS5 v10 scene-aware real-video soak A/B.

The same source-derived frames are processed in a scene-aware temporal session
and an all-reset control. Hard cuts are detected from the source and explicitly
reset in the scene-aware session. Motion-compensated temporal measurements are
diagnostic evidence only and do not decide PASS/FAIL.
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
    SCENE_SOAK_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends.dlss5_v10_protocol import FrameRequest  # noqa: E402
from src.backends.dlss5_v10_security import validate_preflight_report  # noqa: E402
from tools.validate_dlss5_v10_bounded import (  # noqa: E402
    assert_no_host_descendants,
    install_temporary_firewall_block,
    remove_temporary_firewall_block,
    validate_feature_result,
)
from tools.validate_dlss5_v10_scene_cut import detect_scene_cuts  # noqa: E402
from tools.validate_dlss5_v10_video_ab import (  # noqa: E402
    _create_request,
    _pair_temporal_metrics,
    _validate_create,
    decode_video_frames,
)


DEFAULT_RUNTIME = (
    ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
    / "bin" / "runtime" / "dlssnr"
)
DEFAULT_PREFLIGHT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"
DEFAULT_OUTPUT = ROOT / "runtime" / "audit" / "dlss5-v10-scene-soak-hardware.json"
SOAK_FRAME_COUNT = 128
DEFAULT_START_FRAME = 0


def validate_soak_hello(hello: dict[str, object], mode: str) -> None:
    expected = {
        "input": [256, 256],
        "processing_scale": 1.0,
        "max_frames": SOAK_FRAME_COUNT,
    }
    if hello.get("bounded_contract") != expected:
        raise RuntimeError(
            f"scene-aware soak v10 {mode} host contract mismatch: expected "
            f"{expected}, got {hello.get('bounded_contract')!r}"
        )
    expected_mode = f"{mode}-soak"
    if hello.get("scene_cut_mode") != expected_mode:
        raise RuntimeError(
            f"scene-aware soak v10 HELLO mode mismatch: expected "
            f"{expected_mode!r}, got {hello.get('scene_cut_mode')!r}"
        )


def _run_soak_session(
    mode: str,
    frames: list[np.ndarray],
    reset_ids: set[int],
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
        "reset_frame_ids": sorted(reset_ids),
        "process_tree_checks": [],
        "frames": [],
    }
    rendered_frames: list[np.ndarray] = []
    output_hash_sources: dict[str, str] = {}
    measurable_effect_frame_ids: list[int] = []
    byte_identical_to_input_frame_ids: list[int] = []
    try:
        hello = client.start_native_scene_soak_experimental(
            runtime,
            preflight,
            acknowledgement=SCENE_SOAK_EXPERIMENT_ACK,
            mode=mode,
        )
        result["hello"] = hello
        validate_soak_hello(hello, mode)
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
            reset = index in reset_ids
            started = time.perf_counter()
            output = client.process_frame(
                FrameRequest(timestamp=index, reset=reset, rgba=source.tobytes())
            )
            elapsed = time.perf_counter() - started
            validate_feature_result(output)
            if output.cuda_result != 0:
                raise RuntimeError(
                    f"scene-aware soak v10 {mode} frame {index} CUDA result "
                    f"{output.cuda_result}, expected 0"
                )
            if output.timestamp != index:
                raise RuntimeError(
                    f"scene-aware soak v10 {mode} frame {index} timestamp "
                    f"{output.timestamp}, expected {index}"
                )
            expected_scene_reset = 1 if reset else 0
            if output.scene_reset != expected_scene_reset:
                raise RuntimeError(
                    f"scene-aware soak v10 {mode} frame {index} scene_reset="
                    f"{output.scene_reset}, expected {expected_scene_reset}"
                )

            rendered = (
                np.frombuffer(output.rgba, dtype=np.uint8)
                .reshape(256, 256, 4)
                .copy()
            )
            metrics = effect_metrics(source, rendered)
            observed = effect_observed(metrics)
            if observed:
                measurable_effect_frame_ids.append(index)

            input_hash = hashlib.sha256(source.tobytes()).hexdigest().upper()
            output_hash = hashlib.sha256(output.rgba).hexdigest().upper()
            if input_hash == output_hash:
                byte_identical_to_input_frame_ids.append(index)

            previous_input_hash = output_hash_sources.get(output_hash)
            if previous_input_hash is not None and previous_input_hash != input_hash:
                raise RuntimeError(
                    f"scene-aware soak v10 {mode} frame {index} repeated an output "
                    "hash previously produced for a different input"
                )
            output_hash_sources.setdefault(output_hash, input_hash)

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
                    "effect_observed": observed,
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                }
            )
            result["process_tree_checks"].append(
                assert_no_host_descendants(client.pid, f"{mode}_after_frame_{index}")
            )

        result["unique_output_hashes"] = len(output_hash_sources)
        result["measurable_effect_frame_ids"] = measurable_effect_frame_ids
        result["byte_identical_to_input_frame_ids"] = (
            byte_identical_to_input_frame_ids
        )
        roundtrips = np.asarray(
            [float(item["roundtrip_seconds"]) for item in result["frames"]],
            dtype=np.float64,
        )
        result["roundtrip_seconds"] = {
            "mean": float(np.mean(roundtrips)),
            "median": float(np.median(roundtrips)),
            "p95": float(np.percentile(roundtrips, 95)),
            "max": float(np.max(roundtrips)),
        }

        result["close"] = client.close()
        if result["close"] != "CLOSED":
            raise RuntimeError(
                f"scene-aware soak v10 {mode} host did not close cleanly: "
                f"{result['close']}"
            )
        result["status"] = "PASS"
        return result, rendered_frames
    except BaseException:
        try:
            result["abort"] = client.abort()
        except Exception as abort_exc:
            result["abort_error"] = str(abort_exc)
        raise


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "max": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "p95": float(np.percentile(array, 95)),
        "max": float(np.max(array)),
    }


def motion_compensated_temporal_metrics(
    sources: list[np.ndarray],
    outputs: list[np.ndarray],
    *,
    cut_ids: set[int],
) -> dict[str, Any]:
    """Warp previous enhancement residual into the current frame.

    Flow is estimated only from source luma and cut transitions are excluded.
    The source-warp error is retained as a confidence diagnostic because optical
    flow itself can be imperfect.
    """
    residual_flicker: list[float] = []
    source_alignment: list[float] = []
    pair_evidence: list[dict[str, Any]] = []
    height, width = sources[0].shape[:2]
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )

    for index in range(1, len(sources)):
        if index in cut_ids:
            continue

        prev_source = sources[index - 1][..., :3]
        curr_source = sources[index][..., :3]
        prev_output = outputs[index - 1][..., :3]
        curr_output = outputs[index][..., :3]

        prev_gray = cv2.cvtColor(prev_source, cv2.COLOR_RGB2GRAY)
        curr_gray = cv2.cvtColor(curr_source, cv2.COLOR_RGB2GRAY)

        # Backward flow gives, for each current-frame pixel, the displacement to
        # its corresponding location in the previous source frame.
        backward_flow = cv2.calcOpticalFlowFarneback(
            curr_gray,
            prev_gray,
            None,
            0.5,
            3,
            15,
            3,
            5,
            1.2,
            0,
        )
        map_x = grid_x + backward_flow[..., 0].astype(np.float32)
        map_y = grid_y + backward_flow[..., 1].astype(np.float32)
        valid = (
            (map_x >= 0.0)
            & (map_x <= width - 1)
            & (map_y >= 0.0)
            & (map_y <= height - 1)
        )
        if not np.any(valid):
            continue

        warped_prev_source = cv2.remap(
            prev_source.astype(np.float32),
            map_x,
            map_y,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
        prev_residual = (
            prev_output.astype(np.float32) - prev_source.astype(np.float32)
        )
        curr_residual = (
            curr_output.astype(np.float32) - curr_source.astype(np.float32)
        )
        warped_prev_residual = cv2.remap(
            prev_residual,
            map_x,
            map_y,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )

        source_error = np.abs(
            curr_source.astype(np.float32) - warped_prev_source
        )
        residual_error = np.abs(curr_residual - warped_prev_residual)
        source_mae = float(np.mean(source_error[valid]))
        residual_mae = float(np.mean(residual_error[valid]))
        source_alignment.append(source_mae)
        residual_flicker.append(residual_mae)
        pair_evidence.append(
            {
                "current_frame": index,
                "source_alignment_mae": source_mae,
                "enhancement_residual_flicker_mae": residual_mae,
                "valid_pixel_ratio": float(np.mean(valid)),
            }
        )

    return {
        "excluded_cut_frame_ids": sorted(cut_ids),
        "source_alignment_mae": _summary(source_alignment),
        "enhancement_residual_flicker_mae": _summary(residual_flicker),
        "pairs": pair_evidence,
    }


def _save_review_images(
    review_dir: Path,
    sources: list[np.ndarray],
    scene_aware: list[np.ndarray],
    reset_control: list[np.ndarray],
    cut_ids: list[int],
    comparisons: list[dict[str, Any]],
) -> list[str]:
    review_dir.mkdir(parents=True, exist_ok=True)
    selected: list[tuple[str, int]] = [("cut", index) for index in cut_ids[:3]]

    ranked = sorted(
        (
            (float(item["mae"]), index)
            for index, item in enumerate(comparisons)
            if index != 0 and index not in set(cut_ids)
        ),
        reverse=True,
    )
    for _mae, index in ranked[:5]:
        selected.append(("diff", index))

    saved: list[str] = []
    seen: set[int] = set()
    for kind, index in selected:
        if index in seen:
            continue
        seen.add(index)
        panel = np.concatenate(
            [
                sources[index][..., :3],
                scene_aware[index][..., :3],
                reset_control[index][..., :3],
            ],
            axis=1,
        )
        path = review_dir / (
            f"{kind}-{index:03d}-source-sceneaware-reset.png"
        )
        Image.fromarray(panel).save(path)
        saved.append(str(path.resolve()))
    return saved


def run_scene_soak(
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
        count=SOAK_FRAME_COUNT,
    )
    cuts = detect_scene_cuts(frames)
    cut_ids = [int(item["index"]) for item in cuts]
    if not cut_ids:
        return {
            "schema": 1,
            "status": "FAIL",
            "native_executed": False,
            "normal_backend_changed": False,
            "source": source,
            "scene_cuts": cuts,
            "scene_cut_frame_ids": cut_ids,
            "error": (
                "no scene cut detected in 128-frame soak window; choose a "
                "different StartFrame"
            ),
        }

    python = Path(sys.executable).resolve()
    rule_name = f"NVE DLSS5 v10 scene soak {__import__('os').getpid()}"
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
        "frame_count": SOAK_FRAME_COUNT,
        "source": source,
        "scene_cuts": cuts,
        "scene_cut_frame_ids": cut_ids,
        "firewall_rule": rule_name,
    }

    try:
        install_temporary_firewall_block(python, rule_name)
        firewall_installed = True
        report["firewall_installed"] = True
        report["native_execution_attempted"] = True

        scene_reset_ids = {0, *cut_ids}
        scene_report, scene_frames = _run_soak_session(
            "scene-aware",
            frames,
            scene_reset_ids,
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        reset_report, reset_frames = _run_soak_session(
            "reset-control",
            frames,
            set(range(SOAK_FRAME_COUNT)),
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        report["native_executed"] = True
        report["scene_aware"] = scene_report
        report["reset_control"] = reset_report

        comparisons = [
            comparison_metrics(scene_frames[index], reset_frames[index])
            for index in range(SOAK_FRAME_COUNT)
        ]
        report["scene_aware_vs_reset"] = comparisons

        required_reset_ids = [0, *cut_ids]
        reset_parity = {
            str(index): comparisons[index] for index in required_reset_ids
        }
        report["reset_frame_parity"] = reset_parity
        if any(not item["identical"] for item in reset_parity.values()):
            raise RuntimeError(
                "scene-aware soak reset frame did not reproduce reset-control output"
            )

        state_influence_ids = [
            index
            for index, item in enumerate(comparisons)
            if index not in scene_reset_ids and not item["identical"]
        ]
        report["state_influence_frame_ids"] = state_influence_ids
        report["state_influence_observed"] = bool(state_influence_ids)
        if not state_influence_ids:
            raise RuntimeError(
                "scene-aware soak did not show temporal-state influence on any "
                "non-reset frame"
            )

        report["unwarped_temporal_metrics"] = {
            "scene_aware": _pair_temporal_metrics(frames, scene_frames),
            "reset_control": _pair_temporal_metrics(frames, reset_frames),
        }
        scene_motion = motion_compensated_temporal_metrics(
            frames,
            scene_frames,
            cut_ids=set(cut_ids),
        )
        reset_motion = motion_compensated_temporal_metrics(
            frames,
            reset_frames,
            cut_ids=set(cut_ids),
        )
        report["motion_compensated_temporal_metrics"] = {
            "scene_aware": scene_motion,
            "reset_control": reset_motion,
            "scene_aware_minus_reset_mean": (
                None
                if scene_motion["enhancement_residual_flicker_mae"]["mean"] is None
                or reset_motion["enhancement_residual_flicker_mae"]["mean"] is None
                else float(
                    scene_motion["enhancement_residual_flicker_mae"]["mean"]
                    - reset_motion["enhancement_residual_flicker_mae"]["mean"]
                )
            ),
        }

        report["review_images"] = _save_review_images(
            review_dir,
            frames,
            scene_frames,
            reset_frames,
            cut_ids,
            comparisons,
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
                    "scene-aware soak firewall cleanup failed; remove the "
                    "temporary rule manually",
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
    if not args.execute or args.ack != SCENE_SOAK_EXPERIMENT_ACK:
        print(
            "BLOCKED: bounded scene-aware soak requires --execute "
            f"--ack {SCENE_SOAK_EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2

    output = args.output.expanduser().resolve()
    review_dir = (
        args.review_dir.expanduser().resolve()
        if args.review_dir
        else output.with_suffix("").with_name(output.stem + "-review")
    )
    report = run_scene_soak(
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
