"""Ignored, machine-bound compatibility attestations for managed DLSS-G."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .dlssg_profiles import C55_WORKER_SHA256, profile
from .dlssg_official_runtime import policy_satisfied
from .paths import ROOT
from src.runtime_manager.core import sha256_file


SCHEMA = "dlssg-compatibility-attestation-v2"
IMPLEMENTATION = "phase5c-dlssg-candidate-compatibility-v1"
ATTESTATION_PATH = ROOT / "runtime" / "dlssg" / "compatibility-attestation.json"


def machine_context() -> dict[str, str]:
    gpu = "unknown"
    driver = "unknown"
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,uuid", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
            gpu = parts[0] if parts else gpu
            driver = parts[1] if len(parts) > 1 else driver
            uuid = parts[2] if len(parts) > 2 else "unknown"
        else:
            uuid = "unknown"
    except (OSError, subprocess.TimeoutExpired):
        uuid = "unknown"
    return {"gpu": gpu, "gpu_uuid": uuid, "driver": driver, "os": platform.platform()}


def current(*, runtime_path: Path, ini_path: Path, official_identity: str = "unknown", worker_path: Path | None = None) -> dict[str, object]:
    candidate = profile("candidate-0.3.1")
    return {
        "schema": SCHEMA,
        "app_version": IMPLEMENTATION,
        "worker_sha256": sha256_file(worker_path) if worker_path and worker_path.is_file() else C55_WORKER_SHA256,
        "candidate_version": candidate.name,
        "candidate_source_commit": candidate.source_commit,
        "candidate_runtime_sha256": sha256_file(runtime_path) if runtime_path.is_file() else None,
        "candidate_ini_sha256": sha256_file(ini_path) if ini_path.is_file() else None,
        "official_runtime_identity": official_identity,
        "implementation": IMPLEMENTATION,
        "tested_multipliers": [],
        "test_result": "NOT_RUN",
        "validated_at": None,
        **machine_context(),
    }


def is_current(data: dict[str, object], expected: dict[str, object]) -> bool:
    keys = ("schema", "app_version", "implementation", "candidate_version", "candidate_source_commit", "worker_sha256", "candidate_runtime_sha256", "candidate_ini_sha256", "official_runtime_identity", "gpu_uuid", "gpu", "driver", "os")
    return (all(data.get(key) == expected.get(key) for key in keys)
            and data.get("worker_sha256") == C55_WORKER_SHA256
            and policy_satisfied(str(data.get("official_runtime_identity", "")))
            and data.get("test_result") == "PASS"
            and data.get("motion_paths") == {"external": "PASS", "nvof": "PASS"}
            and data.get("tested_multipliers") == [2, 3, 4])


def load(path: Path = ATTESTATION_PATH) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_result(path: Path, result: dict[str, object], *, multipliers: list[int], official_identity: str) -> None:
    result = dict(result)
    result.update({"official_runtime_identity": official_identity, "tested_multipliers": multipliers, "test_result": "PASS", "validated_at": datetime.now(timezone.utc).isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
