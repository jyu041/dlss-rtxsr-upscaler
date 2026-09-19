"""Run a bounded three-frame DLSS5 v10 temporal compatibility experiment.

This remains separate from normal setup/start. It requires a fresh Defender-
gated preflight report, an exact acknowledgement token, a temporary outbound
firewall block for the exact Python interpreter, and is fixed to three
256x256 / 1.0x frames: reset=True, then two reset=False frames.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_metrics import effect_metrics, effect_observed  # noqa: E402
from src.backends.dlss5_v10_client import (  # noqa: E402
    TEMPORAL_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends.dlss5_v10_protocol import CreateRequest, FrameRequest  # noqa: E402
from src.backends.dlss5_v10_security import validate_preflight_report  # noqa: E402
from tools.validate_dlss5_v10_bounded import (  # noqa: E402
    assert_no_host_descendants,
    install_temporary_firewall_block,
    remove_temporary_firewall_block,
    synthetic_frame,
    validate_feature_result,
)


DEFAULT_RUNTIME = (
    ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
    / "bin" / "runtime" / "dlssnr"
)
DEFAULT_PREFLIGHT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"
DEFAULT_OUTPUT = ROOT / "runtime" / "audit" / "dlss5-v10-temporal-hardware.json"
TEMPORAL_FRAME_COUNT = 3


def validate_temporal_hello(hello: dict[str, object]) -> None:
    expected = {
        "input": [256, 256],
        "processing_scale": 1.0,
        "max_frames": TEMPORAL_FRAME_COUNT,
    }
    contract = hello.get("bounded_contract")
    if contract != expected:
        raise RuntimeError(
            f"bounded temporal v10 host contract mismatch: expected {expected}, got {contract!r}"
        )


def synthetic_temporal_frames() -> list[np.ndarray]:
    base = synthetic_frame()
    frames: list[np.ndarray] = []
    for index in range(TEMPORAL_FRAME_COUNT):
        frame = base.copy()
        left = 40 + index * 12
        top = 184
        frame[top:top + 28, left:left + 36, :3] = np.array(
            [40 + index * 20, 220, 90], dtype=np.uint8
        )
        frames.append(frame)
    return frames


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


def run_temporal(
    runtime: Path,
    preflight: Path,
    *,
    gpu_ordinal: int,
) -> dict[str, object]:
    preflight_evidence = validate_preflight_report(runtime, preflight)
    python = Path(sys.executable).resolve()
    rule_name = f"NVE DLSS5 v10 temporal test {__import__('os').getpid()}"
    firewall_installed = False
    client = V10ProtocolClient(
        python=python,
        start_timeout=15.0,
        frame_timeout=45.0,
        close_grace=1.0,
    )
    started = time.perf_counter()

    report: dict[str, object] = {
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
        "frame_count": TEMPORAL_FRAME_COUNT,
        "reset_pattern": [True, False, False],
        "firewall_rule": rule_name,
        "process_tree_checks": [],
        "frames": [],
    }

    try:
        install_temporary_firewall_block(python, rule_name)
        firewall_installed = True
        report["firewall_installed"] = True

        hello = client.start_native_temporal_experimental(
            runtime,
            preflight,
            acknowledgement=TEMPORAL_EXPERIMENT_ACK,
        )
        report["hello"] = hello
        validate_temporal_hello(hello)
        report["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, "after_hello")
        )

        create = client.create(_create_request(gpu_ordinal))
        report["create"] = create
        report["native_executed"] = bool(create.get("native_loaded") is True)
        if create.get("output_size") != [256, 256]:
            raise RuntimeError(
                f"bounded temporal v10 CREATE output_size mismatch: "
                f"{create.get('output_size')!r}"
            )

        initialization = create.get("initialization", {})
        gpu_name = str(initialization.get("gpu_name", ""))
        if initialization.get("bridge_abi_version") != 6:
            raise RuntimeError(
                "bounded temporal v10 milestone requires bridge ABI 6"
            )
        if initialization.get("gpu_ordinal") != gpu_ordinal:
            raise RuntimeError(
                f"bounded temporal v10 GPU ordinal mismatch requested={gpu_ordinal} "
                f"initialized={initialization.get('gpu_ordinal')!r}"
            )
        if "RTX 3070" not in gpu_name:
            raise RuntimeError(
                f"bounded temporal v10 milestone requires the RTX 3070/3070 Ti path, "
                f"got {gpu_name!r}"
            )
        report["process_tree_checks"].append(
            assert_no_host_descendants(client.pid, "after_create")
        )

        frames = synthetic_temporal_frames()
        output_hashes: list[str] = []
        for index, source in enumerate(frames):
            reset = index == 0
            frame_started = time.perf_counter()
            output = client.process_frame(
                FrameRequest(timestamp=index, reset=reset, rgba=source.tobytes())
            )
            elapsed = time.perf_counter() - frame_started
            validate_feature_result(output)
            if output.cuda_result != 0:
                raise RuntimeError(
                    f"temporal frame {index} CUDA result was {output.cuda_result}, expected 0"
                )
            if output.timestamp != index:
                raise RuntimeError(
                    f"temporal frame {index} timestamp mismatch: {output.timestamp}"
                )
            expected_scene_reset = 1 if reset else 0
            if output.scene_reset != expected_scene_reset:
                raise RuntimeError(
                    f"temporal frame {index} scene_reset={output.scene_reset}, "
                    f"expected {expected_scene_reset}"
                )

            rendered = np.frombuffer(output.rgba, dtype=np.uint8).reshape(256, 256, 4)
            metrics = effect_metrics(source, rendered)
            observed = effect_observed(metrics)
            if not observed:
                raise RuntimeError(
                    f"temporal frame {index} did not produce a measurable Neural Rendering effect"
                )

            input_hash = hashlib.sha256(source.tobytes()).hexdigest().upper()
            output_hash = hashlib.sha256(output.rgba).hexdigest().upper()
            if input_hash == output_hash:
                raise RuntimeError(
                    f"temporal frame {index} output is byte-identical to input"
                )
            if output_hash in output_hashes:
                raise RuntimeError(
                    f"temporal frame {index} repeated a previous output hash"
                )
            output_hashes.append(output_hash)

            report["frames"].append(
                {
                    "index": index,
                    "reset": reset,
                    "roundtrip_seconds": elapsed,
                    "ngx_create_result": output.ngx_create_result,
                    "ngx_evaluate_result": output.ngx_evaluate_result,
                    "cuda_result": output.cuda_result,
                    "scene_reset": output.scene_reset,
                    "scene_score": output.scene_score,
                    "upload_bytes": output.upload_bytes,
                    "download_bytes": output.download_bytes,
                    "effect_metrics": metrics,
                    "nr_effect_observed": observed,
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                }
            )
            report["process_tree_checks"].append(
                assert_no_host_descendants(client.pid, f"after_frame_{index}")
            )

        report["unique_output_hashes"] = len(set(output_hashes))
        report["close"] = client.close()
        if report["close"] != "CLOSED":
            raise RuntimeError(
                f"bounded temporal v10 host did not close cleanly: {report['close']}"
            )
        report["status"] = "PASS"
        return report
    except BaseException as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
        try:
            report["abort"] = client.abort()
        except Exception as abort_exc:
            report["abort_error"] = str(abort_exc)
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
                    "bounded temporal v10 firewall cleanup failed; remove the temporary rule manually",
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gpu-ordinal", type=int, default=0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute or args.ack != TEMPORAL_EXPERIMENT_ACK:
        print(
            "BLOCKED: bounded temporal v10 native execution requires --execute "
            f"--ack {TEMPORAL_EXPERIMENT_ACK}",
            file=sys.stderr,
        )
        return 2
    report = run_temporal(
        args.runtime.expanduser().resolve(),
        args.preflight.expanduser().resolve(),
        gpu_ordinal=args.gpu_ordinal,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
