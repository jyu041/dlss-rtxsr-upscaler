"""Bounded C55 DLSS-G runtime validation with a timeout per multiplier.

The normal setup validates the preserved legacy direct-host profile.  The newer
0.3.1 proxy generation remains available only as an explicit candidate profile.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

try:
    import psutil
except ImportError:  # pragma: no cover - the application already declares psutil
    psutil = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlssg_worker import (
    DlssgWorker,
    MOTION_MODE_EXTERNAL_R16G16_FLOAT,
    MOTION_MODE_NVIDIA_OPTICAL_FLOW,
    PIXEL_FORMAT_RGBA8_UNORM,
    mfg_group_complete,
)
from src.core.dlssg_attestation import ATTESTATION_PATH, current, write_result
from src.core.dlssg_official_runtime import identity, policy_satisfied
from src.core.dlssg_profiles import C55_WORKER_SHA256, managed_runtime_paths, profile
from src.core.dlssg_readiness import sha256_file

DEFAULT_WORKER = ROOT / "native" / "dlssg_sm86_offline" / "bin" / "dlssg_sm86_offline.exe"
PER_RUN_TIMEOUT = 30


def validate_reset(result) -> None:
    if not result.reset_only or result.generated_count != 0 or result.outputs:
        raise RuntimeError("protocol-v4 reset/bootstrap must return exactly zero outputs")


def validate_group(result, multiplier: int, width: int, height: int) -> None:
    expected_count = multiplier - 1
    if result.generated_count != expected_count or len(result.outputs) != expected_count:
        raise RuntimeError(
            f"{multiplier}X group incomplete: count={result.generated_count}, "
            f"outputs={len(result.outputs)}, expected={expected_count}"
        )
    if not mfg_group_complete(multiplier, tuple(range(1, result.generated_count + 1))):
        raise RuntimeError(f"{multiplier}X generated-index group is incomplete")
    if (
        result.disable_interpolation != 0
        or result.width != width
        or result.height != height
        or result.pixel_format != PIXEL_FORMAT_RGBA8_UNORM
    ):
        raise RuntimeError("invalid disable flag, dimensions, or pixel format")
    if any(len(output) != width * height * 4 or not output for output in result.outputs):
        raise RuntimeError("invalid generated output byte count")


def _frame(width: int, height: int, frame_id: int) -> bytes:
    return bytes(
        ((x * 7 + y * 13 + frame_id * 29) ^ ((x + frame_id) & 7)) & 255
        for y in range(height)
        for x in range(width)
        for _ in range(4)
    )


def _child(
    worker: Path,
    runtime: Path,
    official: Path,
    runtime_profile: str,
    multiplier: int,
    motion_mode: int,
) -> int:
    width = height = 64
    frames = [_frame(width, height, frame_id) for frame_id in range(3)]
    reset_motion = bytes(width * height * 4)
    motion = b"".join(struct.pack("<ee", 1.0, 0.0) for _ in range(width * height))
    expected = profile(runtime_profile)
    with DlssgWorker(
        worker,
        runtime,
        official,
        expected_community_sha256=expected.runtime_sha256,
        strict_runtime_hash=True,
        diagnostic_callback=lambda line: print(f"WORKER {line}", file=sys.stderr, flush=True),
        diagnostic_mode=True,
    ) as client:
        client.create(width, height, multiplier=multiplier, motion_mode=motion_mode)
        reset = client.process(
            0,
            frames[0],
            reset_motion if motion_mode == MOTION_MODE_EXTERNAL_R16G16_FLOAT else None,
            reset=True,
        )
        validate_reset(reset)
        results = []
        for frame_id in range(3):
            result = client.process(
                frame_id + 1,
                frames[frame_id],
                motion if motion_mode == MOTION_MODE_EXTERNAL_R16G16_FLOAT else None,
            )
            validate_group(result, multiplier, width, height)
            results.append(
                {
                    "generated_count": result.generated_count,
                    "output_bytes": [len(output) for output in result.outputs],
                }
            )
    print(
        json.dumps(
            {
                "profile": runtime_profile,
                "multiplier": multiplier,
                "motion_mode": motion_mode,
                "reset": {"generated_count": 0},
                "frames": results,
            }
        ),
        flush=True,
    )
    return 0


def _terminate_owned_tree(process: subprocess.Popen[str]) -> None:
    child_pids = []
    if psutil is not None:
        try:
            child_pids = [child.pid for child in psutil.Process(process.pid).children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            child_pids = []
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        for pid in child_pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"owned validator process {process.pid} did not exit after cleanup") from exc
    if psutil is not None:
        lingering = []
        for pid in child_pids:
            try:
                if psutil.pid_exists(pid):
                    lingering.append(pid)
            except OSError:
                pass
        if lingering:
            raise RuntimeError(f"owned validator descendants remain after cleanup: {lingering}")


def _run_one(args: argparse.Namespace, multiplier: int, motion_mode: int) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--profile",
        args.profile,
        "--worker",
        str(args.worker),
        "--runtime",
        str(args.runtime),
        "--official",
        str(args.official),
        "--multiplier",
        str(multiplier),
        "--motion-mode",
        str(motion_mode),
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )
    lines: list[str] = []
    while process.poll() is None:
        if time.monotonic() - started > args.timeout:
            _terminate_owned_tree(process)
            raise TimeoutError(f"{multiplier}X {args.profile} validation exceeded {args.timeout}s")
        print(f"HEARTBEAT profile={args.profile} multiplier={multiplier} elapsed={int(time.monotonic()-started)}s", flush=True)
        time.sleep(1)
    if process.stdout:
        lines.extend(line.rstrip() for line in process.communicate(timeout=5)[0].splitlines())
    if process.returncode != 0:
        _terminate_owned_tree(process)
        raise RuntimeError(
            f"{multiplier}X {args.profile} validation failed with exit {process.returncode}: "
            f"{' | '.join(lines[-8:])}"
        )
    return {"multiplier": multiplier, "output": lines[-1] if lines else ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("legacy", "candidate-0.3.1"), default="candidate-0.3.1")
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=PER_RUN_TIMEOUT)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--multiplier", type=int)
    parser.add_argument("--motion-mode", type=int, default=MOTION_MODE_EXTERNAL_R16G16_FLOAT)
    args = parser.parse_args()
    if args.runtime is None:
        args.runtime = managed_runtime_paths(ROOT, args.profile)[0]
    args.worker = args.worker.resolve()
    args.runtime = args.runtime.resolve()
    args.official = args.official.resolve()

    if args.child:
        return _child(
            args.worker,
            args.runtime,
            args.official,
            args.profile,
            args.multiplier,
            args.motion_mode,
        )

    expected = profile(args.profile)
    actual_worker = sha256_file(args.worker) if args.worker.is_file() else None
    official_id = identity(args.official)
    if actual_worker != C55_WORKER_SHA256:
        raise SystemExit(f"BLOCKED: worker identity is {actual_worker}, expected {C55_WORKER_SHA256}")
    if sha256_file(args.runtime) != expected.runtime_sha256:
        raise SystemExit(f"BLOCKED: {args.profile} runtime identity does not match the pinned profile")
    ini = args.runtime.with_name("dlssg_sm86.ini")
    if expected.ini_sha256 and sha256_file(ini) != expected.ini_sha256:
        raise SystemExit(f"BLOCKED: {args.profile} INI identity does not match the pinned profile")
    if not policy_satisfied(official_id):
        raise SystemExit("BLOCKED: required pinned NVIDIA 310.9.1 provider identity is not present")

    results = []
    for multiplier in expected.multipliers:
        paths = {}
        for label, motion_mode in (
            ("external", MOTION_MODE_EXTERNAL_R16G16_FLOAT),
            ("nvof", MOTION_MODE_NVIDIA_OPTICAL_FLOW),
        ):
            print(f"START profile={args.profile} multiplier={multiplier} path={label}", flush=True)
            paths[label] = _run_one(args, multiplier, motion_mode)
            print(f"PASS profile={args.profile} multiplier={multiplier} path={label}", flush=True)
        results.append({"multiplier": multiplier, "paths": paths})

    attestation = None
    if args.profile == "candidate-0.3.1":
        report = current(
            runtime_path=args.runtime,
            ini_path=ini,
            official_identity=official_id,
            worker_path=args.worker,
        )
        report["motion_paths"] = {"external": "PASS", "nvof": "PASS"}
        write_result(
            ATTESTATION_PATH,
            report,
            multipliers=list(expected.multipliers),
            official_identity=official_id,
        )
        attestation = str(ATTESTATION_PATH)

    print(
        json.dumps(
            {
                "status": "PASS",
                "profile": args.profile,
                "results": results,
                "attestation": attestation,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
