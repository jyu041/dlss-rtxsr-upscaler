"""Unified user-facing DLSS 5 backend selection.

The v10 application path is preferred whenever its explicit preflight is ready.
The validated v3 backend remains an internal compatibility fallback while the
v10 migration is still being proven. The UI should expose only this facade.
"""

from __future__ import annotations

from .base import Backend, BackendStatus
from .dlss5 import DLSS5Backend
from .dlss5_v10_app import DLSS5V10ExperimentalBackend


class DLSS5UnifiedBackend(Backend):
    """Select the preferred DLSS 5 implementation without exposing versions."""

    def __init__(self) -> None:
        self.v10 = DLSS5V10ExperimentalBackend()
        self.legacy = DLSS5Backend()

    def _preferred_status(self) -> BackendStatus:
        status = self.v10.status()
        if status.available or status.state != "PREFLIGHT REQUIRED":
            return status
        try:
            from tools.provision_dlss5_v10 import refresh_preflight_from_cache

            if refresh_preflight_from_cache():
                return self.v10.status()
        except Exception:
            pass
        return status

    def runtime(self) -> tuple[str, Backend]:
        v10_status = self._preferred_status()
        if v10_status.available:
            return "v10", self.v10
        legacy_status = self.legacy.status()
        if legacy_status.available:
            return "v3-fallback", self.legacy
        raise RuntimeError(
            "DLSS 5 is unavailable. "
            f"Primary runtime: {v10_status.state} — {v10_status.reason}; "
            f"compatibility runtime: {legacy_status.state} — {legacy_status.reason}"
        )

    def status(self) -> BackendStatus:
        try:
            v10_status = self._preferred_status()
        except Exception as exc:
            v10_status = BackendStatus("DLSS 5", False, "UNAVAILABLE", str(exc))
        if v10_status.available:
            return BackendStatus(
                "DLSS 5",
                True,
                "READY",
                "preferred Neural Rendering runtime is ready",
            )

        try:
            legacy_status = self.legacy.status()
        except Exception as exc:
            legacy_status = BackendStatus("DLSS 5", False, "UNAVAILABLE", str(exc))
        if legacy_status.available:
            return BackendStatus(
                "DLSS 5",
                True,
                "READY (COMPATIBILITY)",
                (
                    "preferred runtime is not ready; using the validated "
                    "compatibility backend internally"
                ),
            )

        return BackendStatus(
            "DLSS 5",
            False,
            "UNAVAILABLE",
            (
                f"preferred runtime: {v10_status.state} — {v10_status.reason}; "
                f"compatibility runtime: {legacy_status.state} — {legacy_status.reason}"
            ),
        )

    def preferred_ready(self) -> bool:
        try:
            return self._preferred_status().available
        except Exception:
            return False

    def close(self) -> None:
        for backend in (self.v10, self.legacy):
            try:
                backend.close()
            except Exception:
                pass
