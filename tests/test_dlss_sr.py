import json
from pathlib import Path

import pytest

from src.backends.dlss_sr import DLSSSRBackend
from src.ui.tooltips import DLSS_SR_TOOLTIPS


def test_missing_host_is_explicitly_reported(tmp_path):
    status = DLSSSRBackend(tmp_path / "missing.exe", tmp_path / "result.json").status()
    assert status.state == "NO HOST"
    assert not status.available


def test_host_built_but_not_tested(tmp_path):
    host = tmp_path / "host.exe"
    host.write_bytes(b"host")
    status = DLSSSRBackend(host, tmp_path / "result.json").status()
    assert status.state == "HOST BUILT - NOT TESTED"


def test_failed_native_selftest(tmp_path):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    result.write_text(json.dumps({"status": "failed", "error": "unsupported"}), encoding="utf-8")
    status = DLSSSRBackend(host, result).status()
    assert status.state == "FAILED SELFTEST"
    assert not status.available


def test_successful_mocked_result(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": True}), encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *args, **kwargs: Completed())
    data = DLSSSRBackend(host, result).selftest()
    assert data["status"] == "success"
    assert DLSSSRBackend(host, result).status().state == "EXPERIMENTAL READY"


def test_dlss_sr_processing_remains_gated(tmp_path):
    with pytest.raises(RuntimeError, match="not exposed"):
        DLSSSRBackend(tmp_path / "missing.exe", tmp_path / "result.json").process_frame(None)


def test_dlss_sr_tooltip_mapping_is_nonempty():
    assert all(value.strip() for value in DLSS_SR_TOOLTIPS.values())
