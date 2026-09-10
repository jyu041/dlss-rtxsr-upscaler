"""Passive DLSS5 diagnostics and the explicit optional self-test command."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .dlss5 import REQUIRED_HASHES, _approval, _hash_report, approval_runtime, firewall_status, ROOT


def _hash(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest().upper()
    except OSError:
        return None


def _gpu() -> dict[str, Any]:
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, check=False)
        values = [item.strip() for item in result.stdout.strip().split(",")]
        if result.returncode == 0 and len(values) >= 3:
            architecture = "Ampere" if values[2].startswith("8.") else None
            generation = 30 if architecture == "Ampere" else None
            return {"name": values[0], "driver_version": values[1], "cuda_compute_capability": values[2], "architecture": architecture, "generation": generation}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"name": None, "driver_version": None, "cuda_compute_capability": None, "architecture": None, "generation": None}


def _file_metadata(path: Path) -> dict[str, Any]:
    item = {"name": path.name, "sha256": _hash(path), "version": None, "authenticode": {"status": "unavailable", "subject": None}}
    if platform.system() != "Windows" or not path.is_file():
        return item
    escaped = str(path).replace("'", "''")
    script = f"$v=(Get-Item -LiteralPath '{escaped}').VersionInfo; $s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; [pscustomobject]@{{version=$v.FileVersion;status=$s.Status.ToString();subject=if($s.SignerCertificate){{$s.SignerCertificate.Subject}}else{{$null}}}} | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=10, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        item["version"] = data.get("version")
        item["authenticode"] = {"status": data.get("status", "unavailable"), "subject": data.get("subject")}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return item


def collect() -> dict[str, Any]:
    approval = _approval() or {}
    runtime = approval_runtime()
    hashes = {}
    expected = {key: str(approval.get(key, "")).upper() for key in REQUIRED_HASHES}
    files = []
    firewall = {"valid": False, "reason": "No approved runtime", "rules": []}
    worker = None
    if runtime is not None:
        worker = runtime / "nvngx.dll"
        hashes_ok, hashes, hash_reason = _hash_report(runtime, approval)
        firewall = firewall_status(worker)
        for names in REQUIRED_HASHES.values():
            files.append(_file_metadata(runtime / names[0]))
    else:
        hashes_ok, hash_reason = False, "Runtime is not approved by the local manifest"
    try:
        from .dlss5 import SELFTEST_RESULT
        selftest = json.loads(SELFTEST_RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        selftest = {"feature_18_verified": False, "reason": "No local self-test report"}
    return {"schema_version": 1, "timestamp": datetime.now().astimezone().isoformat(), "application": {"commit": _commit(), "python": sys.version, "windows": platform.platform()}, "gpu": _gpu(), "runtime_directory": str(runtime) if runtime else None, "runtime_files": files, "actual_sha256": hashes, "expected_sha256": expected, "hash_match": bool(hashes_ok), "hash_reason": hash_reason, "firewall": firewall, "worker_path": str(worker) if worker else None, "worker_protocol": {"client": "pinned Blueforcer ComfyUI-DLSS5-Enhancer", "submodule": "796ed5927a202ba50b5c929cd08e16b365041162"}, "feature_18": {"verified": bool(selftest.get("feature_18_verified")), "evidence": selftest.get("feature_18_evidence"), "nr_effect_observed": selftest.get("nr_effect_observed"), "effectiveness_metrics": selftest.get("effectiveness_metrics"), "timing": {key: selftest.get(key) for key in ("runtime_validation_seconds", "session_initialization_seconds", "first_submit_seconds", "render_seconds", "total_seconds")}}, "public_warning": "Local reports contain filesystem paths; redact paths before sharing publicly."}


def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect DLSS5 state without modifying the system")
    parser.add_argument("--self-test", action="store_true", help="run the existing approved hardware self-test")
    args = parser.parse_args()
    if args.self_test:
        result = subprocess.run([sys.executable, "-m", "src.backends.dlss5_selftest"], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    report = collect()
    path = ROOT / "logs" / f"dlss5-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
