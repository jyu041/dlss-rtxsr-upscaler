"""Project-owned runtime self-test registry.

The registry is source-controlled code; manifest metadata cannot supply an
arbitrary command to execute. Native compatibility remains a separate gate.
"""

from __future__ import annotations

from pathlib import Path

from src.core.dlssg_attestation import current, is_current, load
from src.core.dlssg_profiles import C55_WORKER_SHA256, profile
from src.core.dlssg_readiness import sha256_file


DLSS_SR_HOST_SHA256 = "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB"
DLSS_SR_RUNTIME_SHA256 = "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983"


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
    "project-dlss-sr-beta2": _project_dlss_sr,
    "dlssg-sm86-0.3.1-candidate": _candidate_dlssg,
}


def selftest_for(runtime_id: str):
    return SELFTESTS.get(runtime_id)
