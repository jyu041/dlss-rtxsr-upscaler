"""Gated adapter for the separate native D3D12 NGX DLSS SR host."""

from __future__ import annotations

import json
import hashlib
import csv
import os
import subprocess
import tempfile
from datetime import datetime, timezone
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
ATTESTATION_SCHEMA = "dlss-sr-attestation-v2"


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

    def _identity(self) -> tuple[bool, str, str | None, str | None]:
        if not self.host.is_file() or not self.runtime.is_file():
            return False, "Validated host/runtime are missing", None, None
        try:
            host_hash, runtime_hash = _sha256(self.host), _sha256(self.runtime)
        except OSError as exc:
            return False, str(exc), None, None
        if host_hash != VALIDATED_HOST_SHA256:
            return False, "Native host identity does not match the validated host", host_hash, runtime_hash
        if runtime_hash != VALIDATED_DLSS_SR_RUNTIME_SHA256:
            return False, "DLSS SR runtime identity does not match the validated official REL runtime", host_hash, runtime_hash
        return True, "validated host/runtime identity", host_hash, runtime_hash

    def validate_identity(self):
        """Fail closed before every native execution path."""
        valid, reason, _, _ = self._identity()
        if not valid:
            raise RuntimeError(reason)
        return True

    def _machine_identity(self) -> dict[str, str] | None:
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, check=False)
            if result.returncode == 0 and result.stdout.strip():
                devices = []
                for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
                    if len(row) != 3:
                        continue
                    uuid, name, driver = (part.strip() for part in row)
                    if uuid and name and driver:
                        devices.append((uuid, name, driver))
                devices.sort()
                if devices:
                    return {
                        "gpu_identity": ";".join("|".join(device) for device in devices),
                        "gpu_uuid": ";".join(device[0] for device in devices),
                        "gpu_name": ";".join(device[1] for device in devices),
                        "driver_version": ";".join(device[2] for device in devices),
                    }
        except (OSError, subprocess.TimeoutExpired, ValueError, csv.Error):
            pass
        return None

    def _read_attestation(self):
        try:
            data = json.loads((self.result.parent / "attestation.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _attestation_current(self, host_hash, runtime_hash):
        data = self._read_attestation()
        identity = self._machine_identity()
        return bool(data and data.get("schema") == ATTESTATION_SCHEMA
                    and data.get("host_sha256") == host_hash
                    and data.get("runtime_sha256") == runtime_hash
                    and identity and data.get("gpu_identity") == identity["gpu_identity"]
                    and data.get("gpu_uuid") == identity["gpu_uuid"]
                    and data.get("gpu_name") == identity["gpu_name"]
                    and data.get("driver_version") == identity["driver_version"]
                    and data.get("selftest_success") is True)

    def status(self):
        if not self.host.is_file():
            return BackendStatus("DLSS SR", False, "NO HOST", f"Native host missing: {self.host}")
        if not self.runtime.is_file():
            return BackendStatus("DLSS SR", False, "NO RUNTIME", f"NGX runtime missing: {self.runtime}")
        valid, reason, host_hash, runtime_hash = self._identity()
        if not valid:
            return BackendStatus("DLSS SR", False, "IDENTITY MISMATCH", reason)
        if self._attestation_current(host_hash, runtime_hash):
            return BackendStatus("DLSS SR", True, "READY", "Validated native Quality self-test attestation is current")
        return BackendStatus("DLSS SR", False, "SELFTEST REQUIRED", "Exact binaries are present; run: python tools/check_dlss_sr_readiness.py --selftest")

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
        self.validate_identity()
        attestation = self.result.parent / "attestation.json"
        attestation.unlink(missing_ok=True)
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
        if (completed.returncode != 0 or not data or data.get("status") != "success"
                or data.get("evaluate_succeeded") is not True):
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"Native DLSS SR self-test failed: {detail or data}")
        identity = self._machine_identity()
        if not identity:
            raise RuntimeError("Cannot attest DLSS SR self-test without GPU UUID, name, and driver identity")
        payload = {"schema": ATTESTATION_SCHEMA, "host_sha256": VALIDATED_HOST_SHA256,
            "runtime_sha256": VALIDATED_DLSS_SR_RUNTIME_SHA256, **identity,
            "selftest_success": True, "created_utc": datetime.now(timezone.utc).isoformat()}
        attestation.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=attestation.parent,
                                             prefix="attestation-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, attestation)
        except Exception:
            if temporary:
                temporary.unlink(missing_ok=True)
            attestation.unlink(missing_ok=True)
            raise
        return data

    def process_frame(self, *args, **kwargs):
        raise RuntimeError("DLSS SR frame processing is implemented by src.video.dlss_sr.process_dlss_sr_frame; use the video pipeline entry point.")

    def process_video(self, *args, **kwargs):
        raise RuntimeError("DLSS SR video processing is implemented by src.video.dlss_sr.render_dlss_sr; use the video pipeline entry point.")

    def close(self):
        return None
