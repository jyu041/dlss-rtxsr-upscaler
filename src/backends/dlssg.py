"""Configuration adapter for offline DLSS-G 2X frame interpolation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .base import Backend, BackendStatus

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


class DLSSGBackend(Backend):
    """A distinct interpolation backend; it is not DLSS SR or RTX VSR."""

    def __init__(
        self,
        worker: str | Path | None = None,
        community_runtime: str | Path | None = None,
        official_runtime_dir: str | Path | None = None,
        runtime_profile: str | None = None,
    ):
        profile = runtime_profile or os.environ.get("DLSSG_RUNTIME_PROFILE", "legacy")
        configured_runtime = community_runtime or os.environ.get("DLSSG_COMMUNITY_RUNTIME")
        if profile not in {"legacy", "candidate-0.3.1"}:
            raise ValueError(f"Unknown DLSS-G runtime profile: {profile}")
        if configured_runtime is None and profile == "candidate-0.3.1":
            configured_runtime = MANAGED_CANDIDATE_RUNTIME
        self.configuration = DlssgConfiguration(
            Path(worker or os.environ.get("DLSSG_WORKER_EXE", DEFAULT_WORKER)).expanduser().resolve(),
            Path(configured_runtime or MANAGED_COMMUNITY_RUNTIME).expanduser().resolve(),
            Path(official_runtime_dir or os.environ.get("DLSSG_OFFICIAL_RUNTIME_DIR", MANAGED_OFFICIAL_RUNTIME_DIR)).expanduser().resolve(),
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
