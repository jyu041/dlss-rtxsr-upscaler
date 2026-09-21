"""Project-owned runtime self-test registry.

The registry is source-controlled code; manifest metadata cannot supply an
arbitrary command to execute. Native compatibility remains a separate gate.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from src.core.dlssg_attestation import current, is_current, load
from src.core.dlssg_profiles import C55_WORKER_SHA256, profile
from src.core.dlssg_readiness import sha256_file


DLSS_SR_HOST_SHA256 = "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB"
DLSS_SR_RUNTIME_SHA256 = "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983"
GRID4_WORKER_SHA256 = "E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881"
GRID4_WORKER_SIZE = 613376
GRID4_SOURCE_COMMIT = "76702915f5c55423786d6fdd92e69ef1f55bbfa5"


def _project_c55_worker(path: Path) -> None:
    worker = path / "dlssg_sm86_offline.exe"
    if not worker.is_file() or sha256_file(worker) != C55_WORKER_SHA256:
        raise RuntimeError("public project C55 worker identity mismatch")


def _project_dlss_sr(path: Path) -> None:
    host = path / "dlss_sr_host.exe"
    runtime = path / "nvngx_dlss.dll"
    if not host.is_file() or sha256_file(host) != DLSS_SR_HOST_SHA256:
        raise RuntimeError("public project DLSS SR host identity mismatch")
    if not runtime.is_file() or sha256_file(runtime) != DLSS_SR_RUNTIME_SHA256:
        raise RuntimeError("public project DLSS SR runtime identity mismatch")


def _project_grid4_worker(path: Path) -> None:
    worker = path / "dlssg_sm86_offline.exe"
    provenance_path = path / "BUILD-PROVENANCE.json"
    notices = (path / "LICENSE-NVIDIA-RTX-SDK.txt", path / "THIRD_PARTY_NOTICES.md")
    if not worker.is_file() or worker.stat().st_size != GRID4_WORKER_SIZE or sha256_file(worker) != GRID4_WORKER_SHA256:
        raise RuntimeError("public project grid4 worker identity mismatch")
    if not provenance_path.is_file() or any(not item.is_file() for item in notices):
        raise RuntimeError("public project grid4 provenance/notices are incomplete")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
    if provenance.get("source_commit") != GRID4_SOURCE_COMMIT:
        raise RuntimeError("public project grid4 source provenance mismatch")
    if provenance.get("worker", {}).get("sha256") != GRID4_WORKER_SHA256:
        raise RuntimeError("public project grid4 provenance worker identity mismatch")
    try:
        result = subprocess.run(
            [str(worker), "--selftest"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"public project grid4 worker selftest could not run: {exc}") from exc
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 or "SELFTEST_COMPLETE" not in output:
        raise RuntimeError(f"public project grid4 worker selftest failed with exit code {result.returncode}")


def _candidate_dlssg(path: Path) -> None:
    expected = profile("candidate-0.3.1")
    runtime = path / "version.dll"
    ini = path / "dlssg_sm86.ini"
    if sha256_file(runtime) != expected.runtime_sha256 or runtime.stat().st_size != expected.runtime_size:
        raise RuntimeError("candidate runtime files are not exactly verified")
    if sha256_file(ini) != expected.ini_sha256 or ini.stat().st_size != expected.ini_size:
        raise RuntimeError("candidate INI is not exactly verified")
    expected_attestation = current(runtime_path=runtime, ini_path=ini)
    if not (attestation := load()) or not is_current(attestation, expected_attestation):
        raise RuntimeError("C55 compatibility test required; verified files are not backend-ready")


SELFTESTS = {
    "project-c55-worker-beta2": _project_c55_worker,
    "project-grid4-worker-v1": _project_grid4_worker,
    "project-dlss-sr-beta2": _project_dlss_sr,
    "dlssg-sm86-0.3.1-candidate": _candidate_dlssg,
}


def selftest_for(runtime_id: str):
    return SELFTESTS.get(runtime_id)
