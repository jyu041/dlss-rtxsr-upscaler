"""Configuration adapter for offline DLSS-G 2X frame interpolation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .base import Backend, BackendStatus

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKER = ROOT / "native" / "dlssg_sm86_offline" / "bin" / "dlssg_sm86_offline.exe"


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
    ):
        self.configuration = DlssgConfiguration(
            Path(worker or os.environ.get("DLSSG_WORKER_EXE", DEFAULT_WORKER)).expanduser().resolve(),
            Path(community_runtime or os.environ.get("DLSSG_COMMUNITY_RUNTIME", "version.dll")).expanduser().resolve(),
            Path(official_runtime_dir or os.environ.get("DLSSG_OFFICIAL_RUNTIME_DIR", "runtime/dlssg")).expanduser().resolve(),
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
            return BackendStatus("DLSS Frame Generation 2X", False, "NOT CONFIGURED", "; ".join(missing))
        return BackendStatus(
            "DLSS Frame Generation 2X",
            True,
            "EXPERIMENTAL READY",
            "Offline frame interpolation using NVIDIA Optical Flow and external Ampere DLSS-G runtime",
        )

    def require_configuration(self) -> DlssgConfiguration:
        status = self.status()
        if not status.available:
            raise RuntimeError(f"DLSS-G backend unavailable: {status.reason}")
        return self.configuration

    def close(self) -> None:
        return None
