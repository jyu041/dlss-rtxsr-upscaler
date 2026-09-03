"""Gated adapter for the separate native D3D12 NGX DLSS SR host."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .base import Backend, BackendStatus

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "runtime" / "dlss-sr-host" / "dlss_sr_host.exe"
RESULT = ROOT / "runtime" / "dlss-sr-host" / "selftest" / "result.json"
APPROVED_DLL_SHA256 = "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


class DLSSSRBackend(Backend):
    def __init__(self, host: Path = HOST, result: Path = RESULT):
        self.host = Path(host)
        self.result = Path(result)
        self.runtime = self.host.parent / "nvngx_dlss.dll"
        self.available = False
        self.reason = "Native standalone DLSS SR has not passed its self-test"

    def _read_result(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def status(self):
        if not self.host.is_file():
            return BackendStatus("DLSS SR", False, "NO HOST", f"Native host missing: {self.host}")
        if not self.runtime.is_file():
            return BackendStatus("DLSS SR", False, "NO RUNTIME", f"NGX runtime missing: {self.runtime}")
        try:
            if _sha256(self.runtime) != APPROVED_DLL_SHA256:
                return BackendStatus("DLSS SR", False, "HASH MISMATCH", f"Unapproved NGX runtime: {self.runtime}")
        except OSError as exc:
            return BackendStatus("DLSS SR", False, "NO RUNTIME", str(exc))
        data = self._read_result()
        if not data:
            return BackendStatus("DLSS SR", False, "HOST BUILT - NOT TESTED", str(self.host))
        if data.get("status") != "success" or not data.get("evaluate_succeeded"):
            return BackendStatus("DLSS SR", False, "FAILED SELFTEST", str(data.get("error", self.reason)))
        return BackendStatus(
            "DLSS SR", False, "EXPERIMENTAL READY",
            "Native Quality self-test passed; normal UI exposure remains gated",
        )

    def validate_runtime(self):
        status = self.status()
        return {
            "host": str(self.host),
            "host_exists": self.host.is_file(),
            "runtime": str(self.runtime),
            "runtime_sha256": _sha256(self.runtime) if self.runtime.is_file() else None,
            "state": status.state,
            "available": status.available,
            "reason": status.reason,
        }

    def selftest(self):
        if not self.host.is_file():
            raise RuntimeError(f"Native DLSS SR host missing: {self.host}")
        completed = subprocess.run(
            [str(self.host), "selftest", "quality"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
        data = self._read_result()
        if completed.returncode or not data or data.get("status") != "success":
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"Native DLSS SR self-test failed: {detail or data}")
        return data

    def process_frame(self, *args, **kwargs):
        raise RuntimeError("DLSS SR frame processing is not exposed until native video integration.")

    def process_video(self, *args, **kwargs):
        raise RuntimeError("DLSS SR video processing is not implemented.")

    def close(self):
        return None
