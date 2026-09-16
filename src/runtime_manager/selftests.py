"""Project-owned runtime self-test registry.

The registry is source-controlled code; manifest metadata cannot supply an
arbitrary command to execute. Native compatibility remains a separate gate.
"""

from __future__ import annotations

from pathlib import Path

from src.core.dlssg_attestation import current, is_current, load
from src.core.dlssg_profiles import profile
from src.core.dlssg_readiness import sha256_file


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
    "dlssg-sm86-0.3.1-candidate": _candidate_dlssg,
}


def selftest_for(runtime_id: str):
    return SELFTESTS.get(runtime_id)
