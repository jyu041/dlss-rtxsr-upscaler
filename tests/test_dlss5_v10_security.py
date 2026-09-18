import json

import pytest

import src.backends.dlss5_v10_security as security
from src.backends.dlss5_v10_static import V10StaticStatus


def _report(destination):
    return {
        "native_executed": False,
        "approved_for_normal_backend": False,
        "hardware_test_ready": True,
        "destination": str(destination),
        "malware_scan": {"status": "passed", "exit_code": 0},
        "static_after_scan": {
            "state": "STATIC_AUDIT_COMPLETE",
            "valid": True,
            "execution_allowed": False,
        },
    }


def test_v10_preflight_security_gate_accepts_matching_clean_report(monkeypatch, tmp_path):
    destination = tmp_path / "candidate"
    runtime = destination / "bin" / "runtime" / "dlssnr"
    runtime.mkdir(parents=True)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(destination)), encoding="utf-8")

    monkeypatch.setattr(
        security,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "STATIC_AUDIT_COMPLETE", True, False, "pass", {}
        ),
    )

    report = security.validate_preflight_report(runtime, report_path)
    assert report["hardware_test_ready"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("native_executed", True, "native_executed=false"),
        ("approved_for_normal_backend", True, "normal backend"),
        ("hardware_test_ready", False, "hardware-test ready"),
    ],
)
def test_v10_preflight_security_gate_rejects_policy_changes(
    monkeypatch, tmp_path, field, value, message
):
    destination = tmp_path / "candidate"
    runtime = destination / "bin" / "runtime" / "dlssnr"
    runtime.mkdir(parents=True)
    report = _report(destination)
    report[field] = value
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        security,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "STATIC_AUDIT_COMPLETE", True, False, "pass", {}
        ),
    )

    with pytest.raises(RuntimeError, match=message):
        security.validate_preflight_report(runtime, report_path)


def test_v10_preflight_security_gate_rejects_runtime_path_mismatch(monkeypatch, tmp_path):
    destination = tmp_path / "candidate"
    expected = destination / "bin" / "runtime" / "dlssnr"
    expected.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(destination)), encoding="utf-8")
    monkeypatch.setattr(
        security,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "STATIC_AUDIT_COMPLETE", True, False, "pass", {}
        ),
    )

    with pytest.raises(RuntimeError, match="does not match preflight destination"):
        security.validate_preflight_report(other, report_path)


def test_v10_preflight_security_gate_rechecks_current_identity(monkeypatch, tmp_path):
    destination = tmp_path / "candidate"
    runtime = destination / "bin" / "runtime" / "dlssnr"
    runtime.mkdir(parents=True)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(destination)), encoding="utf-8")
    monkeypatch.setattr(
        security,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "IDENTITY_MISMATCH", False, False, "changed", {}
        ),
    )

    with pytest.raises(RuntimeError, match="changed after preflight"):
        security.validate_preflight_report(runtime, report_path)
