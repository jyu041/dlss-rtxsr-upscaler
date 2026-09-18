"""Safely stage the exact DLSS5 Visual Enhancer v10 research candidate.

This tool never loads or executes a v10 DLL. It verifies the pinned archive,
extracts only the manifest allowlist, verifies the pinned PE/ABI identities,
requires a clean Microsoft Defender custom scan, verifies identity again after
the scan, and atomically stages the candidate for a later bounded hardware test.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from src.backends.dlss5_v10_static import inspect_v10_runtime
from src.runtime_manager.core import RuntimeManager, extract_safe_zip, verify_artifact


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"
RUNTIME_ID = "dlss5-neuroframe-v10-static-candidate"
DEFAULT_ARCHIVE = ROOT / "runtime" / "downloads" / "Visual.Enhancer.v10.0.zip"
DEFAULT_DESTINATION = ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
DEFAULT_REPORT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"


def _defender_candidates() -> list[Path]:
    candidates: list[Path] = []
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
    program_data = os.environ.get("ProgramData")
    if program_data:
        platform = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform.is_dir():
            candidates.extend(
                sorted(
                    platform.glob("*/MpCmdRun.exe"),
                    key=lambda path: path.parent.name,
                    reverse=True,
                )
            )
    return candidates


def defender_scan(path: Path, *, scanner: Path | None = None) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("DLSS5 v10 Defender preflight requires Windows")
    selected = scanner or next(
        (candidate for candidate in _defender_candidates() if candidate.is_file()),
        None,
    )
    if selected is None or not Path(selected).is_file():
        raise RuntimeError(
            "Microsoft Defender MpCmdRun.exe was not found; v10 hardware preflight "
            "requires a malware scan"
        )
    result = subprocess.run(
        [
            str(Path(selected).resolve()),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(path.resolve()),
            "-DisableRemediation",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    report = {
        "tool": str(Path(selected).resolve()),
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    if result.returncode:
        raise RuntimeError(
            f"Microsoft Defender did not return a clean v10 scan result "
            f"(exit {result.returncode})"
        )
    return report


def _static_gate(runtime_dir: Path) -> dict[str, object]:
    status = inspect_v10_runtime(runtime_dir)
    if status.state != "STATIC_AUDIT_COMPLETE" or not status.valid:
        raise RuntimeError(
            f"DLSS5 v10 static gate failed: {status.state}; {status.detail}"
        )
    if status.execution_allowed:
        raise RuntimeError("v10 static inspector unexpectedly allowed execution")
    return {
        "state": status.state,
        "valid": status.valid,
        "execution_allowed": status.execution_allowed,
        "evidence": status.evidence,
    }


def _activate(staged: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except Exception:
        if had_previous and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)


def stage_candidate(
    archive: Path,
    destination: Path = DEFAULT_DESTINATION,
    *,
    report_path: Path = DEFAULT_REPORT,
    scanner: Path | None = None,
) -> dict[str, object]:
    archive = Path(archive).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    report_path = Path(report_path).expanduser().resolve()

    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    spec = manager.specs[RUNTIME_ID]
    verify_artifact(archive, spec)

    work_parent = destination.parent
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nve-dlss5-v10-stage-", dir=work_parent) as temporary:
        staged = Path(temporary) / "candidate"
        extract_safe_zip(archive, staged, spec.allowlist, selective=True)
        runtime_dir = staged / "bin" / "runtime" / "dlssnr"

        before = _static_gate(runtime_dir)
        malware = defender_scan(staged, scanner=scanner)
        after = _static_gate(runtime_dir)

        before_hashes = {
            name: record["sha256"]
            for name, record in before["evidence"]["files"].items()
        }
        after_hashes = {
            name: record["sha256"]
            for name, record in after["evidence"]["files"].items()
        }
        if before_hashes != after_hashes:
            raise RuntimeError("v10 staged runtime identity changed during Defender scan")

        report = {
            "schema": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_id": RUNTIME_ID,
            "archive": {
                "path": str(archive),
                "size_bytes": archive.stat().st_size,
                "sha256": spec.sha256,
            },
            "destination": str(destination),
            "static_before_scan": before,
            "malware_scan": malware,
            "static_after_scan": after,
            "native_executed": False,
            "approved_for_normal_backend": False,
            "hardware_test_ready": True,
        }

        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary_report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        # Move the staged files only after all gates pass.
        _activate(staged, destination)
        os.replace(temporary_report, report_path)
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = stage_candidate(
            args.archive,
            args.destination,
            report_path=args.report,
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"DLSS5 v10 preflight failed: {exc}", file=__import__("sys").stderr)
        return 1
    print(json.dumps(report, indent=2))
    print("DLSS5 v10 candidate staged for bounded hardware research; native execution has not occurred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
