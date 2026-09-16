"""Configuration adapter for offline DLSS-G 2X frame interpolation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .base import Backend, BackendStatus
from src.core.dlssg_profiles import profile as get_profile
from src.core.dlssg_attestation import current as current_attestation, is_current, load as load_attestation
from src.core.dlssg_official_runtime import identity as official_runtime_identity, policy_satisfied
from src.core.dlssg_readiness import sha256_file

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKER = ROOT / "native" / "dlssg_sm86_offline" / "bin" / "dlssg_sm86_offline.exe"
MANAGED_COMMUNITY_RUNTIME = ROOT / "runtime" / "dlssg" / "legacy" / "version.dll"
MANAGED_CANDIDATE_RUNTIME = ROOT / "runtime" / "dlssg" / "candidate-0.3.1" / "version.dll"
MANAGED_OFFICIAL_RUNTIME_DIR = ROOT / "runtime" / "dlssg" / "official"


@dataclass(frozen=True)
class DlssgConfiguration:
    worker: Path
    community_runtime: Path
    official_runtime_dir: Path
    runtime_profile: str
    expected_runtime_sha256: str


class DLSSGBackend(Backend):
    """A distinct interpolation backend; it is not DLSS SR or RTX VSR."""

    def __init__(
        self,
        worker: str | Path | None = None,
        community_runtime: str | Path | None = None,
        official_runtime_dir: str | Path | None = None,
        runtime_profile: str | None = None,
    ):
        profile_name = runtime_profile or os.environ.get("DLSSG_RUNTIME_PROFILE", "legacy")
        configured_runtime = community_runtime or os.environ.get("DLSSG_COMMUNITY_RUNTIME")
        if profile_name not in {"legacy", "candidate-0.3.1"}:
            raise ValueError(f"Unknown DLSS-G runtime profile: {profile_name}")
        if configured_runtime is None and profile_name == "candidate-0.3.1":
            configured_runtime = MANAGED_CANDIDATE_RUNTIME
        self.configuration = DlssgConfiguration(
            Path(worker or os.environ.get("DLSSG_WORKER_EXE", DEFAULT_WORKER)).expanduser().resolve(),
            Path(configured_runtime or MANAGED_COMMUNITY_RUNTIME).expanduser().resolve(),
            Path(official_runtime_dir or os.environ.get("DLSSG_OFFICIAL_RUNTIME_DIR", MANAGED_OFFICIAL_RUNTIME_DIR)).expanduser().resolve(),
            profile_name,
            get_profile(profile_name).runtime_sha256,
        )

    def status(self) -> BackendStatus:
        config = self.configuration
        missing = []
        if not config.worker.is_file():
            missing.append(f"worker: {config.worker}")
        if not config.community_runtime.is_file():
            missing.append(f"external community runtime: {config.community_runtime}")
        if not config.official_runtime_dir.is_dir():
            missing.append(f"official runtime directory: {config.official_runtime_dir}")
        if missing:
            return BackendStatus("DLSS-G 2X/3X/4X", False, "NOT CONFIGURED", "; ".join(missing))
        actual = sha256_file(config.community_runtime)
        if actual != config.expected_runtime_sha256:
            return BackendStatus("DLSS-G 2X/3X/4X", False, "IDENTITY MISMATCH", f"{config.runtime_profile} runtime SHA-256 mismatch")
        if config.runtime_profile == "candidate-0.3.1":
            ini = config.community_runtime.with_name("dlssg_sm86.ini")
            if sha256_file(ini) != get_profile(config.runtime_profile).ini_sha256:
                return BackendStatus("DLSS-G 2X/3X/4X", False, "IDENTITY MISMATCH", "candidate INI SHA-256 mismatch")
        worker_hash = sha256_file(config.worker)
        if worker_hash != "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916":
            return BackendStatus("DLSS-G 2X/3X/4X", False, "IDENTITY MISMATCH", "worker SHA-256 is not the verified C55 identity")
        if config.runtime_profile == "candidate-0.3.1":
            official_identity = official_runtime_identity(config.official_runtime_dir)
            if not policy_satisfied(official_identity):
                return BackendStatus("DLSS-G 2X/3X/4X", False, "COMPATIBILITY TEST REQUIRED", "official provider is absent or does not match the pinned NVIDIA 310.9.1 policy")
            expected = current_attestation(runtime_path=config.community_runtime, ini_path=config.community_runtime.with_name("dlssg_sm86.ini"), official_identity=official_identity, worker_path=config.worker)
            attestation = load_attestation()
            if not attestation or not is_current(attestation, expected):
                return BackendStatus("DLSS-G 2X/3X/4X", False, "COMPATIBILITY TEST REQUIRED", "Candidate files are verified, but C55 compatibility has not passed the 2X/3X/4X synthetic test")
        return BackendStatus(
            "DLSS-G 2X/3X/4X",
            True,
            "VALIDATED",
            "Offline 2X Frame Generation and 3X/4X Multi Frame Generation using NVIDIA Optical Flow and external Ampere DLSS-G runtime",
        )

    def require_configuration(self) -> DlssgConfiguration:
        status = self.status()
        if not status.available:
            raise RuntimeError(f"DLSS-G backend unavailable: {status.reason}")
        return self.configuration

    def close(self) -> None:
        return None
