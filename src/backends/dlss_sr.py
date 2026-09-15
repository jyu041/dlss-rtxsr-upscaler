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
VALIDATED_DLSS_SR_RUNTIME_SHA256 = "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983"
VALIDATED_HOST_SHA256 = "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB"
VALIDATED_SDK_COMMIT = "374959484E79A640FEABA44C93AC8CFB0A03F5B5"
VALIDATED_SDK_LICENSE_SHA256 = "3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294"


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
            host_hash = _sha256(self.host)
            if host_hash != VALIDATED_HOST_SHA256:
                return BackendStatus("DLSS SR", False, "HOST HASH MISMATCH", f"Unvalidated native host: {self.host}")
            runtime_hash = _sha256(self.runtime)
            if runtime_hash != VALIDATED_DLSS_SR_RUNTIME_SHA256:
                return BackendStatus("DLSS SR", False, "RUNTIME HASH MISMATCH", f"Unvalidated official NGX runtime: {self.runtime}")
        except OSError as exc:
            return BackendStatus("DLSS SR", False, "NO RUNTIME", str(exc))
        data = self._read_result()
        if not data:
            return BackendStatus("DLSS SR", False, "HOST BUILT - NOT TESTED", str(self.host))
        if data.get("status") != "success" or not data.get("evaluate_succeeded"):
            return BackendStatus("DLSS SR", False, "FAILED SELFTEST", str(data.get("error", self.reason)))
        return BackendStatus(
            "DLSS SR", True, "EXPERIMENTAL READY",
            "Native Quality self-test passed",
        )

    def validate_runtime(self):
        status = self.status()
        return {
            "host": str(self.host),
            "host_exists": self.host.is_file(),
            "runtime": str(self.runtime),
            "runtime_sha256": _sha256(self.runtime) if self.runtime.is_file() else None,
            "host_sha256": _sha256(self.host) if self.host.is_file() else None,
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
        raise RuntimeError("DLSS SR frame processing is implemented by src.video.dlss_sr.process_dlss_sr_frame; use the video pipeline entry point.")

    def process_video(self, *args, **kwargs):
        raise RuntimeError("DLSS SR video processing is implemented by src.video.dlss_sr.render_dlss_sr; use the video pipeline entry point.")

    def close(self):
        return None
