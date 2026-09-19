"""Run a bounded 32-frame DLSS5 v10 scene-cut/reset experiment.

The same source-derived 256x256 frames are evaluated in three isolated native
sessions: no cut reset, scene-aware reset, and reset-every-frame control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_metrics import comparison_metrics, effect_metrics, effect_observed  # noqa: E402
from src.backends.dlss5_v10_client import (  # noqa: E402
    SCENE_CUT_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends.dlss5_v10_protocol import FrameRequest  # noqa: E402
from src.backends.dlss5_v10_security import validate_preflight_report  # noqa: E402
from src.video.dlssg import scene_cut_metrics  # noqa: E402
from tools.validate_dlss5_v10_bounded import (  # noqa: E402
    assert_no_host_descendants,
    install_temporary_firewall_block,
    remove_temporary_firewall_block,
    validate_feature_result,
)
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
DEFAULT_OUTPUT = ROOT / "runtime" / "audit" / "dlss5-v10-scene-cut-hardware.json"
SCENE_FRAME_COUNT = 32
DEFAULT_START_FRAME = 0


def detect_scene_cuts(frames: list[np.ndarray]) -> list[dict[str, Any]]:
    cuts: list[dict[str, Any]] = []
    for index in range(1, len(frames)):
        metrics = scene_cut_metrics(
            frames[index - 1].tobytes(),
            frames[index].tobytes(),
            256,
            256,
        )
        if bool(metrics["is_cut"]):
            cuts.append({"index": index, **metrics})
    return cuts


def validate_scene_hello(hello: dict[str, object], mode: str) -> None:
    expected = {
        "input": [256, 256],
        "processing_scale": 1.0,
        "max_frames": SCENE_FRAME_COUNT,
    }
    if hello.get("bounded_contract") != expected:
        raise RuntimeError(
            f"scene-cut v10 {mode} host contract mismatch: expected {expected}, "
            f"got {hello.get('bounded_contract')!r}"
        )
    if hello.get("scene_cut_mode") != mode:
        raise RuntimeError(
            f"scene-cut v10 HELLO mode mismatch: expected {mode!r}, "
            f"got {hello.get('scene_cut_mode')!r}"
        )


def _run_scene_session(
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
    output_hashes: set[str] = set()
    output_hash_sources: dict[str, str] = {}
    measurable_effect_frame_ids: list[int] = []
    byte_identical_to_input_frame_ids: list[int] = []
    try:
        hello = client.start_native_scene_cut_experimental(
            runtime,
            preflight,
            acknowledgement=SCENE_CUT_EXPERIMENT_ACK,
            mode=mode,
        )
        result["hello"] = hello
        validate_scene_hello(hello, mode)
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
                    f"scene-cut v10 {mode} frame {index} CUDA result "
                    f"{output.cuda_result}, expected 0"
                )
            if output.timestamp != index:
                raise RuntimeError(
                    f"scene-cut v10 {mode} frame {index} timestamp "
                    f"{output.timestamp}, expected {index}"
                )
            expected_scene_reset = 1 if reset else 0
            if output.scene_reset != expected_scene_reset:
                raise RuntimeError(
                    f"scene-cut v10 {mode} frame {index} scene_reset="
                    f"{output.scene_reset}, expected {expected_scene_reset}"
                )

            rendered = np.frombuffer(output.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
            metrics = effect_metrics(source, rendered)
            input_hash = hashlib.sha256(source.tobytes()).hexdigest().upper()
            output_hash = hashlib.sha256(output.rgba).hexdigest().upper()
            observed = effect_observed(metrics)
            if observed:
                measurable_effect_frame_ids.append(index)
            if input_hash == output_hash:
                byte_identical_to_input_frame_ids.append(index)
            previous_input_hash = output_hash_sources.get(output_hash)
            if previous_input_hash is not None and previous_input_hash != input_hash:
                raise RuntimeError(
                    f"scene-cut v10 {mode} frame {index} repeated an output hash "
                    "previously produced for a different input"
                )
            output_hash_sources.setdefault(output_hash, input_hash)
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
                    "effect_observed": observed,
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                }
            )
            result["process_tree_checks"].append(
                assert_no_host_descendants(client.pid, f"{mode}_after_frame_{index}")
            )

        result["unique_output_hashes"] = len(output_hashes)
        result["measurable_effect_frame_ids"] = measurable_effect_frame_ids
        result["byte_identical_to_input_frame_ids"] = byte_identical_to_input_frame_ids
        result["close"] = client.close()
        if result["close"] != "CLOSED":
            raise RuntimeError(
                f"scene-cut v10 {mode} host did not close cleanly: {result['close']}"
            )
        result["status"] = "PASS"
        return result, rendered_frames
    except BaseException:
        try:
            result["abort"] = client.abort()
        except Exception as abort_exc:
            result["abort_error"] = str(abort_exc)
        raise


def _save_cut_reviews(
    review_dir: Path,
    sources: list[np.ndarray],
    no_cut: list[np.ndarray],
    scene_aware: list[np.ndarray],
    reset_control: list[np.ndarray],
    cut_ids: list[int],
) -> list[str]:
    review_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for cut_id in cut_ids[:3]:
        panel = np.concatenate(
            [
                sources[cut_id][..., :3],
                no_cut[cut_id][..., :3],
                scene_aware[cut_id][..., :3],
                reset_control[cut_id][..., :3],
            ],
            axis=1,
        )
        path = review_dir / f"cut-{cut_id:02d}-source-noreset-sceneaware-reset.png"
        Image.fromarray(panel).save(path)
        saved.append(str(path.resolve()))
    return saved


def _cut_window_metrics(
    sources: list[np.ndarray],
    outputs: list[np.ndarray],
    cut_ids: list[int],
    radius: int = 3,
) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    for cut_id in cut_ids:
        lo = max(0, cut_id - 1)
        hi = min(len(sources), cut_id + radius + 1)
        if hi - lo < 2:
            continue
        metrics = _pair_temporal_metrics(sources[lo:hi], outputs[lo:hi])
        windows.append(
            {
                "cut_frame": cut_id,
                "window_start": lo,
                "window_end_exclusive": hi,
                "temporal_metrics": metrics,
            }
        )
    return {"radius_after_cut": radius, "windows": windows}


def run_scene_cut_gate(
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
        count=SCENE_FRAME_COUNT,
    )
    cuts = detect_scene_cuts(frames)
    cut_ids = [int(item["index"]) for item in cuts]

    report: dict[str, Any] = {
        "schema": 1,
        "status": "STARTED",
        "native_executed": False,
        "normal_backend_changed": False,
        "runtime": str(runtime.resolve()),
        "preflight": str(preflight.resolve()),
        "preflight_age_seconds": preflight_evidence.get("preflight_age_seconds"),
        "defender": preflight_evidence.get("malware_scan"),
        "python": str(Path(sys.executable).resolve()),
        "gpu_ordinal": gpu_ordinal,
        "dimensions": [256, 256],
        "processing_scale": 1.0,
        "frame_count": SCENE_FRAME_COUNT,
        "source": source,
        "scene_cuts": cuts,
        "scene_cut_frame_ids": cut_ids,
    }
    if not cuts:
        report["status"] = "FAIL"
        report["error"] = (
            "no scene cut detected in bounded source window; choose a different "
            "StartFrame rather than treating a no-cut window as scene-cut evidence"
        )
        return report

    python = Path(sys.executable).resolve()
    rule_name = f"NVE DLSS5 v10 scene-cut test {__import__('os').getpid()}"
    report["firewall_rule"] = rule_name
    firewall_installed = False
    started = time.perf_counter()
    try:
        install_temporary_firewall_block(python, rule_name)
        firewall_installed = True
        report["firewall_installed"] = True
        report["native_execution_attempted"] = True

        no_cut_report, no_cut_frames = _run_scene_session(
            "no-cut-reset",
            frames,
            {0},
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        scene_reset_ids = {0, *cut_ids}
        scene_report, scene_frames = _run_scene_session(
            "scene-aware",
            frames,
            scene_reset_ids,
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        reset_report, reset_frames = _run_scene_session(
            "reset-control",
            frames,
            set(range(SCENE_FRAME_COUNT)),
            runtime,
            preflight,
            gpu_ordinal=gpu_ordinal,
        )
        report["native_executed"] = True
        report["no_cut_reset"] = no_cut_report
        report["scene_aware"] = scene_report
        report["reset_control"] = reset_report

        initial_no_cut = comparison_metrics(no_cut_frames[0], reset_frames[0])
        initial_scene = comparison_metrics(scene_frames[0], reset_frames[0])
        report["initial_reset_parity"] = {
            "no_cut_vs_reset": initial_no_cut,
            "scene_aware_vs_reset": initial_scene,
        }
        if not initial_no_cut["identical"] or not initial_scene["identical"]:
            raise RuntimeError(
                "scene-cut v10 fresh frame-0 reset output is not deterministic across sessions"
            )

        cut_comparisons: list[dict[str, Any]] = []
        all_scene_resets_match_control = True
        carryover_ids: list[int] = []
        for cut_id in cut_ids:
            scene_vs_control = comparison_metrics(
                scene_frames[cut_id], reset_frames[cut_id]
            )
            no_cut_vs_control = comparison_metrics(
                no_cut_frames[cut_id], reset_frames[cut_id]
            )
            scene_vs_no_cut = comparison_metrics(
                scene_frames[cut_id], no_cut_frames[cut_id]
            )
            if not scene_vs_control["identical"]:
                all_scene_resets_match_control = False
            if not no_cut_vs_control["identical"]:
                carryover_ids.append(cut_id)
            cut_comparisons.append(
                {
                    "cut_frame": cut_id,
                    "scene_aware_vs_reset_control": scene_vs_control,
                    "no_cut_reset_vs_reset_control": no_cut_vs_control,
                    "scene_aware_vs_no_cut_reset": scene_vs_no_cut,
                }
            )

        report["cut_frame_comparisons"] = cut_comparisons
        report["scene_reset_matches_reset_control"] = all_scene_resets_match_control
        report["carryover_observed_at_cut_frame_ids"] = carryover_ids
        if not all_scene_resets_match_control:
            raise RuntimeError(
                "scene-aware reset did not reproduce reset-control output on every "
                "detected cut frame"
            )

        report["temporal_metrics"] = {
            "no_cut_reset": _pair_temporal_metrics(frames, no_cut_frames),
            "scene_aware": _pair_temporal_metrics(frames, scene_frames),
            "reset_control": _pair_temporal_metrics(frames, reset_frames),
        }
        report["cut_window_metrics"] = {
            "no_cut_reset": _cut_window_metrics(frames, no_cut_frames, cut_ids),
            "scene_aware": _cut_window_metrics(frames, scene_frames, cut_ids),
            "reset_control": _cut_window_metrics(frames, reset_frames, cut_ids),
        }
        report["review_images"] = _save_cut_reviews(
            review_dir,
            frames,
            no_cut_frames,
            scene_frames,
            reset_frames,
            cut_ids,
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
                    "scene-cut v10 firewall cleanup failed; remove the temporary rule manually",
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
    if not args.execute or args.ack != SCENE_CUT_EXPERIMENT_ACK:
        print(
            "BLOCKED: bounded scene-cut v10 execution requires --execute "
            f"--ack {SCENE_CUT_EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2
    output = args.output.expanduser().resolve()
    review_dir = (
        args.review_dir.expanduser().resolve()
        if args.review_dir
        else output.with_suffix("").with_name(output.stem + "-review")
    )
    report = run_scene_cut_gate(
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
