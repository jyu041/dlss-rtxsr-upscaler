"""Bounded, explicit C55 candidate validation with a timeout per multiplier."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

from src.backends.dlssg_worker import DlssgWorker, MOTION_MODE_EXTERNAL_R16G16_FLOAT
from src.core.dlssg_attestation import ATTESTATION_PATH, current, write_result
from src.core.dlssg_official_runtime import identity
from src.core.dlssg_profiles import C55_WORKER_SHA256, profile
from src.core.dlssg_readiness import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKER = ROOT / "native" / "dlssg_sm86_offline" / "bin" / "dlssg_sm86_offline.exe"
DEFAULT_RUNTIME = ROOT / "runtime" / "dlssg" / "candidate-0.3.1" / "version.dll"
PER_RUN_TIMEOUT = 30


def _child(worker: Path, runtime: Path, official: Path, multiplier: int) -> int:
    width = height = 32
    color = bytes((i * 17 + multiplier) % 256 for i in range(width * height * 4))
    motion = b"".join(struct.pack("<ee", 0.0, 0.0) for _ in range(width * height))
    with DlssgWorker(worker, runtime, official, expected_community_sha256=profile("candidate-0.3.1").runtime_sha256, strict_runtime_hash=True) as client:
        client.create(width, height, multiplier=multiplier, motion_mode=MOTION_MODE_EXTERNAL_R16G16_FLOAT)
        counts = []
        for frame_id in range(3):
            result = client.process(frame_id, color, motion, reset=frame_id == 0)
            counts.append(result.generated_count)
        if any(count <= 0 for count in counts[1:]):
            raise RuntimeError(f"{multiplier}X produced no generated frame")
    print(json.dumps({"multiplier": multiplier, "generated_counts": counts}), flush=True)
    return 0


def _run_one(args: argparse.Namespace, multiplier: int) -> dict[str, object]:
    command = [sys.executable, str(Path(__file__).resolve()), "--child", "--worker", str(args.worker), "--runtime", str(args.runtime), "--official", str(args.official), "--multiplier", str(multiplier)]
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    lines: list[str] = []
    while process.poll() is None:
        if time.monotonic() - started > args.timeout:
            process.kill()
            process.wait(timeout=5)
            raise TimeoutError(f"{multiplier}X candidate validation exceeded {args.timeout}s")
        print(f"HEARTBEAT multiplier={multiplier} elapsed={int(time.monotonic()-started)}s", flush=True)
        time.sleep(1)
    if process.stdout:
        lines.extend(line.rstrip() for line in process.communicate(timeout=5)[0].splitlines())
    if process.returncode != 0:
        raise RuntimeError(f"{multiplier}X validation failed with exit {process.returncode}: {' | '.join(lines[-5:])}")
    return {"multiplier": multiplier, "output": lines[-1] if lines else ""}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, default=DEFAULT_WORKER)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=PER_RUN_TIMEOUT)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--multiplier", type=int)
    args = parser.parse_args()
    if args.child:
        return _child(args.worker, args.runtime, args.official, args.multiplier)
    expected = profile("candidate-0.3.1")
    actual_worker = sha256_file(args.worker) if args.worker.is_file() else None
    official_id = identity(args.official)
    if actual_worker != C55_WORKER_SHA256:
        raise SystemExit(f"BLOCKED: worker identity is {actual_worker}, expected {C55_WORKER_SHA256}")
    if sha256_file(args.runtime) != expected.runtime_sha256 or official_id.startswith("missing"):
        raise SystemExit("BLOCKED: exact candidate files and required official NGX provider identity are not both present")
    results = []
    for multiplier in (2, 3, 4):
        print(f"START multiplier={multiplier}", flush=True)
        results.append(_run_one(args, multiplier))
        print(f"PASS multiplier={multiplier}", flush=True)
    report = current(runtime_path=args.runtime, ini_path=args.runtime.with_name("dlssg_sm86.ini"), official_identity=official_id, worker_path=args.worker)
    write_result(ATTESTATION_PATH, report, multipliers=[2, 3, 4], official_identity=official_id)
    print(json.dumps({"status": "PASS", "results": results, "attestation": str(ATTESTATION_PATH)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
