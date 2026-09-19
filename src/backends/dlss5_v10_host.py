"""Non-executing isolated-host scaffold for DLSS5 v10.

Only --contract-selftest is implemented. --serve is intentionally blocked so
no v10 DLL can be loaded during this milestone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .dlss5_v10_contract import (
    BRIDGE_ABI_VERSION,
    EXPECTED_STRUCT_SIZES,
    REQUIRED_EXPORTS,
    validate_static_contract,
)
from .dlss5_v10_protocol import (
    CLOSE,
    CREATE,
    ERROR,
    FRAME,
    HELLO,
    MAGIC,
    OUTPUT,
    PROTOCOL_VERSION,
    CreateRequest,
    FrameRequest,
    OutputEvidence,
    SessionGuard,
    V10ProtocolError,
    decode_json,
    encode_json,
    encode_message,
    read_message,
)
from .dlss5_v10_static import V10_EXPECTED_FILES


EXPERIMENT_ACK = "BOUNDED_256_ONE_FRAME"
TEMPORAL_EXPERIMENT_ACK = "BOUNDED_256_THREE_FRAME"
VIDEO_AB_EXPERIMENT_ACK = "BOUNDED_256_VIDEO_AB_16"
SCENE_CUT_EXPERIMENT_ACK = "BOUNDED_256_SCENE_CUT_32"


SIMULATED_NATIVE_RESULT = -2147483648


def protocol_selftest_server() -> int:
    guard = SessionGuard()
    create: CreateRequest | None = None
    stdout = sys.stdout.buffer
    stdin = sys.stdin.buffer
    stdout.write(
        encode_json(
            HELLO,
            0,
            {
                "protocol_version": PROTOCOL_VERSION,
                "native_loaded": False,
                "execution_allowed": False,
                "mode": "protocol-selftest",
            },
        )
    )
    stdout.flush()

    try:
        while True:
            command, request_id, payload = read_message(stdin)
            if command == CREATE:
                guard.accept_create(request_id)
                create = CreateRequest.from_wire(decode_json(payload))
                stdout.write(
                    encode_json(
                        CREATE,
                        request_id,
                        {
                            "status": "CREATED",
                            "native_loaded": False,
                            "output_size": list(create.output_size),
                        },
                    )
                )
                stdout.flush()
                continue

            if command == FRAME:
                guard.accept_frame(request_id)
                if create is None:
                    raise V10ProtocolError("FRAME requires CREATE")
                frame = FrameRequest.decode(
                    payload, create.input_width, create.input_height
                )
                output_width, output_height = create.output_size
                if (output_width, output_height) != (
                    create.input_width,
                    create.input_height,
                ):
                    raise V10ProtocolError(
                        "protocol selftest FRAME supports 1.0x geometry only"
                    )
                evidence = OutputEvidence(
                    width=output_width,
                    height=output_height,
                    timestamp=frame.timestamp,
                    ngx_create_result=SIMULATED_NATIVE_RESULT,
                    ngx_evaluate_result=SIMULATED_NATIVE_RESULT,
                    cuda_result=SIMULATED_NATIVE_RESULT,
                    scene_reset=int(frame.reset),
                    scene_score=0.0,
                    upload_bytes=len(frame.rgba),
                    download_bytes=len(frame.rgba),
                    rgba=frame.rgba,
                )
                stdout.write(encode_message(OUTPUT, request_id, evidence.encode()))
                stdout.flush()
                continue

            if command == CLOSE:
                guard.accept_close(request_id)
                stdout.write(
                    encode_json(
                        CLOSE,
                        request_id,
                        {"status": "CLOSED", "native_loaded": False},
                    )
                )
                stdout.flush()
                return 0

            raise V10ProtocolError(f"command {command} is invalid for host input")
    except (EOFError, V10ProtocolError, ValueError) as exc:
        guard.poison(str(exc))
        try:
            stdout.write(
                encode_json(
                    ERROR,
                    guard.next_request_id,
                    {
                        "error": str(exc),
                        "poisoned": True,
                        "native_loaded": False,
                    },
                )
            )
            stdout.flush()
        except Exception:
            pass
        return 2


def experimental_native_server(
    runtime_dir: Path,
    preflight_report: Path,
    *,
    expected_ack: str = EXPERIMENT_ACK,
    max_frames: int = 1,
    temporal_sequence: bool = False,
    reset_every_frame: bool = False,
    video_ab_mode: str | None = None,
    require_first_reset: bool = False,
    scene_cut_mode: str | None = None,
) -> int:
    if __import__("os").environ.get("NVE_DLSS5_V10_NATIVE") != expected_ack:
        print(
            "BLOCKED: experimental native v10 host requires the exact bounded-test acknowledgement",
            file=sys.stderr,
        )
        return 77
    if max_frames not in (1, 3, 16, 32):
        raise ValueError("experimental native v10 max_frames must be 1, 3, 16, or 32")
    if temporal_sequence and reset_every_frame:
        raise ValueError("experimental native v10 reset policies are mutually exclusive")
    if video_ab_mode not in (None, "persistent", "reset-control"):
        raise ValueError("invalid v10 video A/B mode")
    if scene_cut_mode not in (None, "no-cut-reset", "scene-aware", "reset-control"):
        raise ValueError("invalid v10 scene-cut mode")

    from .dlss5_v10_native import V10NativeSession, load_bridge
    from .dlss5_v10_security import validate_preflight_report

    runtime_dir = runtime_dir.expanduser().resolve()
    preflight_report = preflight_report.expanduser().resolve()
    validate_preflight_report(runtime_dir, preflight_report)

    guard = SessionGuard()
    native_session = None
    frame_count = 0
    stdout = sys.stdout.buffer
    stdin = sys.stdin.buffer
    hello = {
        "protocol_version": PROTOCOL_VERSION,
        "native_loaded": False,
        "experimental_native_mode": True,
        "normal_backend_enabled": False,
        "bounded_contract": {
            "input": [256, 256],
            "processing_scale": 1.0,
            "max_frames": max_frames,
        },
    }
    if video_ab_mode is not None:
        hello["video_ab_mode"] = video_ab_mode
    if scene_cut_mode is not None:
        hello["scene_cut_mode"] = scene_cut_mode
    stdout.write(encode_json(HELLO, 0, hello))
    stdout.flush()

    try:
        while True:
            command, request_id, payload = read_message(stdin)
            if command == CREATE:
                guard.accept_create(request_id)
                create = CreateRequest.from_wire(decode_json(payload))
                if (
                    create.input_width != 256
                    or create.input_height != 256
                    or create.processing_scale != 1.0
                    or create.output_size != (256, 256)
                ):
                    raise V10ProtocolError(
                        "bounded native v10 CREATE requires exactly 256x256 at 1.0x"
                    )
                bound = load_bridge(
                    runtime_dir,
                    allow_native_load=True,
                )
                native_session = V10NativeSession(bound, runtime_dir, create)
                initialized = native_session.initialize()
                stdout.write(
                    encode_json(
                        CREATE,
                        request_id,
                        {
                            "status": "CREATED",
                            "native_loaded": True,
                            "experimental_native_mode": True,
                            "output_size": [256, 256],
                            "initialization": initialized,
                        },
                    )
                )
                stdout.flush()
                continue

            if command == FRAME:
                guard.accept_frame(request_id)
                if native_session is None:
                    raise V10ProtocolError("FRAME requires successful native CREATE")
                if frame_count >= max_frames:
                    raise V10ProtocolError(
                        f"bounded native v10 host permits exactly {max_frames} FRAME request(s)"
                    )
                frame = FrameRequest.decode(payload, 256, 256)
                if temporal_sequence:
                    if frame_count == 0 and not frame.reset:
                        raise V10ProtocolError(
                            "temporal v10 sequence requires reset=True on the first FRAME"
                        )
                    if frame_count > 0 and frame.reset:
                        raise V10ProtocolError(
                            "temporal v10 sequence requires reset=False after the first FRAME"
                        )
                if require_first_reset and frame_count == 0 and not frame.reset:
                    raise V10ProtocolError(
                        "bounded native v10 sequence requires reset=True on the first FRAME"
                    )
                if reset_every_frame and not frame.reset:
                    raise V10ProtocolError(
                        "reset-control v10 sequence requires reset=True on every FRAME"
                    )
                output = native_session.process_frame(frame)
                frame_count += 1
                stdout.write(encode_message(OUTPUT, request_id, output.encode()))
                stdout.flush()
                continue

            if command == CLOSE:
                guard.accept_close(request_id)
                close_status = (
                    native_session.close()
                    if native_session is not None
                    else "CLOSED_WITHOUT_NATIVE_SESSION"
                )
                stdout.write(
                    encode_json(
                        CLOSE,
                        request_id,
                        {
                            "status": "CLOSED",
                            "native_loaded": native_session is not None,
                            "session_close": close_status,
                            "ngx_shutdown_called": False,
                            "module_unload_called": False,
                        },
                    )
                )
                stdout.flush()
                return 0

            raise V10ProtocolError(f"command {command} is invalid for native host input")
    except (EOFError, V10ProtocolError, ValueError, RuntimeError) as exc:
        guard.poison(str(exc))
        if native_session is not None:
            try:
                native_session.close()
            except Exception:
                pass
        try:
            stdout.write(
                encode_json(
                    ERROR,
                    guard.next_request_id,
                    {
                        "error": str(exc),
                        "poisoned": True,
                        "experimental_native_mode": True,
                    },
                )
            )
            stdout.flush()
        except Exception:
            pass
        return 2


def contract_report() -> dict[str, object]:
    validate_static_contract()
    return {
        "status": "PASS",
        "native_loaded": False,
        "execution_allowed": False,
        "protocol_magic": MAGIC.decode("ascii"),
        "protocol_version": PROTOCOL_VERSION,
        "bridge_abi_version": BRIDGE_ABI_VERSION,
        "struct_sizes": EXPECTED_STRUCT_SIZES,
        "required_exports": list(REQUIRED_EXPORTS),
        "expected_files": V10_EXPECTED_FILES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-selftest", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--protocol-selftest-server", action="store_true")
    parser.add_argument("--experimental-native-serve", action="store_true")
    parser.add_argument("--experimental-native-temporal-serve", action="store_true")
    parser.add_argument("--experimental-native-video-persistent-serve", action="store_true")
    parser.add_argument("--experimental-native-video-reset-serve", action="store_true")
    parser.add_argument("--experimental-native-scene-no-reset-serve", action="store_true")
    parser.add_argument("--experimental-native-scene-aware-serve", action="store_true")
    parser.add_argument("--experimental-native-scene-reset-serve", action="store_true")
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--preflight-report", type=Path)
    args = parser.parse_args(argv)

    if args.contract_selftest:
        print(json.dumps(contract_report(), indent=2, sort_keys=True))
        return 0

    if args.protocol_selftest_server:
        return protocol_selftest_server()

    if args.experimental_native_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error("--experimental-native-serve requires --runtime-dir and --preflight-report")
        return experimental_native_server(args.runtime_dir, args.preflight_report)

    if args.experimental_native_temporal_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-temporal-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=TEMPORAL_EXPERIMENT_ACK,
            max_frames=3,
            temporal_sequence=True,
        )

    if args.experimental_native_video_persistent_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-video-persistent-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=VIDEO_AB_EXPERIMENT_ACK,
            max_frames=16,
            temporal_sequence=True,
            video_ab_mode="persistent",
        )

    if args.experimental_native_video_reset_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-video-reset-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=VIDEO_AB_EXPERIMENT_ACK,
            max_frames=16,
            reset_every_frame=True,
            video_ab_mode="reset-control",
        )

    if args.experimental_native_scene_no_reset_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-scene-no-reset-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=SCENE_CUT_EXPERIMENT_ACK,
            max_frames=32,
            temporal_sequence=True,
            scene_cut_mode="no-cut-reset",
        )

    if args.experimental_native_scene_aware_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-scene-aware-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=SCENE_CUT_EXPERIMENT_ACK,
            max_frames=32,
            require_first_reset=True,
            scene_cut_mode="scene-aware",
        )

    if args.experimental_native_scene_reset_serve:
        if args.runtime_dir is None or args.preflight_report is None:
            parser.error(
                "--experimental-native-scene-reset-serve requires --runtime-dir and --preflight-report"
            )
        return experimental_native_server(
            args.runtime_dir,
            args.preflight_report,
            expected_ack=SCENE_CUT_EXPERIMENT_ACK,
            max_frames=32,
            reset_every_frame=True,
            scene_cut_mode="reset-control",
        )

    if args.serve:
        print(
            "BLOCKED: DLSS5 v10 host execution is not implemented at the "
            "static-adapter milestone.",
            file=sys.stderr,
        )
        return 78

    parser.error("choose --contract-selftest or --protocol-selftest-server")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
