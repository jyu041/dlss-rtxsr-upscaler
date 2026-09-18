"""Security gate for the bounded DLSS5 v10 native experiment."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .dlss5_v10_static import inspect_v10_runtime

DEFAULT_MAX_PREFLIGHT_AGE_HOURS = 24.0
MAX_FUTURE_SKEW_MINUTES = 5.0


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise RuntimeError("v10 preflight report is missing timestamp_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("v10 preflight report timestamp_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("v10 preflight report timestamp_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def validate_preflight_report(
    runtime_dir: str | Path,
    report_path: str | Path,
    *,
    max_age_hours: float = DEFAULT_MAX_PREFLIGHT_AGE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_dir).expanduser().resolve()
    report_file = Path(report_path).expanduser().resolve()
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"DLSS5 v10 preflight report is unreadable: {exc}") from exc
    if not isinstance(report, dict):
        raise RuntimeError("DLSS5 v10 preflight report must be a JSON object")

    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scanned_at = _parse_timestamp(report.get("timestamp_utc"))
    if scanned_at - current_time > timedelta(minutes=MAX_FUTURE_SKEW_MINUTES):
        raise RuntimeError("v10 preflight timestamp is unexpectedly in the future")
    age = current_time - scanned_at
    if age > timedelta(hours=max_age_hours):
        raise RuntimeError(
            f"v10 Defender preflight is stale ({age.total_seconds() / 3600.0:.2f}h); "
            f"rerun preparation within {max_age_hours:.1f}h of native execution"
        )
    report["preflight_age_seconds"] = max(0.0, age.total_seconds())

    if report.get("native_executed") is not False:
        raise RuntimeError("v10 preflight report does not prove native_executed=false")
    if report.get("approved_for_normal_backend") is not False:
        raise RuntimeError("v10 preflight report unexpectedly approves the normal backend")
    if report.get("hardware_test_ready") is not True:
        raise RuntimeError("v10 preflight report is not hardware-test ready")

    malware = report.get("malware_scan")
    if not isinstance(malware, dict) or malware.get("status") != "passed" or malware.get("exit_code") != 0:
        raise RuntimeError("v10 preflight report does not contain a clean Defender result")

    destination = Path(str(report.get("destination", ""))).expanduser().resolve()
    expected_runtime = (destination / "bin" / "runtime" / "dlssnr").resolve()
    if runtime != expected_runtime:
        raise RuntimeError(
            f"v10 runtime {runtime} does not match preflight destination {expected_runtime}"
        )

    after = report.get("static_after_scan")
    if not isinstance(after, dict):
        raise RuntimeError("v10 preflight report is missing post-scan static evidence")
    if after.get("state") != "STATIC_AUDIT_COMPLETE" or after.get("valid") is not True:
        raise RuntimeError("v10 post-scan static gate did not complete successfully")
    if after.get("execution_allowed") is not False:
        raise RuntimeError("v10 post-scan static evidence unexpectedly allowed execution")

    current = inspect_v10_runtime(runtime)
    if current.state != "STATIC_AUDIT_COMPLETE" or not current.valid:
        raise RuntimeError(
            f"v10 runtime changed after preflight: {current.state}; {current.detail}"
        )
    if current.execution_allowed:
        raise RuntimeError("v10 current static inspector unexpectedly allowed execution")

    return report
