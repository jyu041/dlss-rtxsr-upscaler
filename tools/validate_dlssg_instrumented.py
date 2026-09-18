"""Bounded validation wrapper for a locally built instrumented DLSS-G worker.

This tool is deliberately separate from validate_dlssg_candidate.py so the
production C55 worker identity gate stays strict.  It accepts only an executable
under native/dlssg_sm86_offline/bin-instrumented, pins the validated legacy
community runtime and NVIDIA provider identities, runs the GPU-free selftest,
and then launches the existing bounded 256x256 child validator matrix.

Running this tool performs GPU work. Importing it does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.dlssg_gpu_timing import summarize_gpu_timestamps

INSTRUMENTED_ROOT = (
    ROOT / "native" / "dlssg_sm86_offline" / "bin-instrumented"
).resolve()
LEGACY_RUNTIME = (ROOT / "runtime" / "dlssg" / "legacy" / "version.dll").resolve()
OFFICIAL_RUNTIME = (ROOT / "runtime" / "dlssg" / "official").resolve()
C55_WORKER_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
LEGACY_RUNTIME_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
OFFICIAL_PROVIDER_SHA256 = "FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82"
SELFTEST_TIMEOUT = 15
CELL_TIMEOUT = 60


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def require_instrumented_worker(path: Path) -> str:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise RuntimeError(f"instrumented worker is missing: {resolved}")
    try:
        resolved.relative_to(INSTRUMENTED_ROOT)
    except ValueError as exc:
        raise RuntimeError(
            f"instrumented worker must be under {INSTRUMENTED_ROOT}"
        ) from exc
    digest = sha256_file(resolved)
    if digest == C55_WORKER_SHA256:
        raise RuntimeError(
            "instrumented validation refuses the pinned production C55 binary; "
            "build this branch into bin-instrumented first"
        )
    return digest


def require_runtime_identity(runtime: Path, official: Path) -> dict[str, str]:
    runtime = runtime.expanduser().resolve()
    official = official.expanduser().resolve()
    provider = official / "nvngx_dlssg.dll"
    if not runtime.is_file() or sha256_file(runtime) != LEGACY_RUNTIME_SHA256:
        raise RuntimeError("validated legacy community runtime identity is missing or changed")
    if not provider.is_file() or sha256_file(provider) != OFFICIAL_PROVIDER_SHA256:
        raise RuntimeError("pinned NVIDIA DLSS-G provider identity is missing or changed")
    return {
        "community_runtime_sha256": sha256_file(runtime),
        "official_provider_sha256": sha256_file(provider),
    }


def run_selftest(worker: Path, timeout: int = SELFTEST_TIMEOUT) -> dict[str, object]:
    completed = subprocess.run(
        [str(worker), "--selftest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0 or "SELFTEST_COMPLETE" not in output:
        raise RuntimeError(
            f"instrumented worker selftest failed with exit {completed.returncode}: {output[-2000:]}"
        )
    return {"exit_code": completed.returncode, "output_tail": output.splitlines()[-20:]}


def _run_cell(
    worker: Path,
    runtime: Path,
    official: Path,
    multiplier: int,
    motion_mode: int,
    timeout: int,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "validate_dlssg_candidate.py"),
        "--child",
        "--profile",
        "legacy",
        "--worker",
        str(worker),
        "--runtime",
        str(runtime),
        "--official",
        str(official),
        "--multiplier",
        str(multiplier),
        "--motion-mode",
        str(motion_mode),
        "--instrumented-timing",
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "DLSSG_GPU_TIMESTAMPS": "1",
            "DLSSG_NVOF_DIRECTION": "forward",
            "DLSSG_NVOF_GPU_FLOW": "1",
        },
    )
    elapsed = time.monotonic() - started
    merged = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{multiplier}X motion_mode={motion_mode} failed with exit "
            f"{completed.returncode}: {merged[-4000:]}"
        )

    timestamp_lines = [
        line.removeprefix("WORKER ")
        for line in merged.splitlines()
        if "GPU_TIMESTAMP " in line
    ]
    timestamp_summary = summarize_gpu_timestamps(timestamp_lines)
    required_stages = {"input_upload", "dlssg_evaluate", "output_copy", "group_total"}
    if motion_mode == 2:
        required_stages.update({"nvof_bracket", "nvof_conversion"})
    observed_stages = set(timestamp_summary["stages_ms"])
    missing_stages = sorted(required_stages - observed_stages)
    if missing_stages:
        raise RuntimeError(
            f"{multiplier}X motion_mode={motion_mode} is missing GPU timestamp stages: "
            + ", ".join(missing_stages)
        )
    return {
        "multiplier": multiplier,
        "motion_mode": motion_mode,
        "elapsed_seconds": elapsed,
        "gpu_timestamps": timestamp_summary,
        "gpu_timestamp_lines": timestamp_lines,
        "output_tail": merged.splitlines()[-30:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--worker",
        type=Path,
        default=INSTRUMENTED_ROOT / "dlssg_sm86_offline.exe",
    )
    parser.add_argument("--runtime", type=Path, default=LEGACY_RUNTIME)
    parser.add_argument("--official", type=Path, default=OFFICIAL_RUNTIME)
    parser.add_argument("--timeout", type=int, default=CELL_TIMEOUT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    worker = args.worker.expanduser().resolve()
    runtime = args.runtime.expanduser().resolve()
    official = args.official.expanduser().resolve()

    worker_sha = require_instrumented_worker(worker)
    identities = require_runtime_identity(runtime, official)
    selftest = run_selftest(worker)

    results = []
    for multiplier in (2, 3, 4):
        for label, motion_mode in (("external", 1), ("nvof", 2)):
            print(f"START multiplier={multiplier} path={label}", flush=True)
            result = _run_cell(
                worker, runtime, official, multiplier, motion_mode, args.timeout
            )
            result["path"] = label
            results.append(result)
            print(f"PASS multiplier={multiplier} path={label}", flush=True)

    report = {
        "schema_version": 1,
        "status": "PASS",
        "worker": str(worker),
        "worker_sha256": worker_sha,
        "production_c55_sha256": C55_WORKER_SHA256,
        **identities,
        "selftest": selftest,
        "validation_geometry": [256, 256],
        "results": results,
    }
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
