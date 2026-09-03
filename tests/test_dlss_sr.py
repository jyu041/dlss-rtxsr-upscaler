import json
from pathlib import Path

import pytest

from src.backends.dlss_sr import DLSSSRBackend
from src.video.dlss_sr import INPUT_HEADER, INPUT_MAGIC, OUTPUT_HEADER, _read_response, _target
from src.ui.tooltips import DLSS_SR_TOOLTIPS


def test_missing_host_is_explicitly_reported(tmp_path):
    status = DLSSSRBackend(tmp_path / "missing.exe", tmp_path / "result.json").status()
    assert status.state == "NO HOST"
    assert not status.available


def test_host_built_but_not_tested(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    host.write_bytes(b"host")
    (tmp_path / "nvngx_dlss.dll").write_bytes(b"dll")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E")
    status = DLSSSRBackend(host, tmp_path / "result.json").status()
    assert status.state == "HOST BUILT - NOT TESTED"


def test_failed_native_selftest(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    (tmp_path / "nvngx_dlss.dll").write_bytes(b"dll")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E")
    result.write_text(json.dumps({"status": "failed", "error": "unsupported"}), encoding="utf-8")
    status = DLSSSRBackend(host, result).status()
    assert status.state == "FAILED SELFTEST"
    assert not status.available


def test_successful_mocked_result(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    (tmp_path / "nvngx_dlss.dll").write_bytes(b"dll")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E")
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": True}), encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *args, **kwargs: Completed())
    data = DLSSSRBackend(host, result).selftest()
    assert data["status"] == "success"
    status = DLSSSRBackend(host, result).status()
    assert status.state == "EXPERIMENTAL READY"
    assert status.available is True


def test_dlss_sr_processing_remains_gated(tmp_path):
    with pytest.raises(RuntimeError, match="not exposed"):
        DLSSSRBackend(tmp_path / "missing.exe", tmp_path / "result.json").process_frame(None)


def test_dlss_sr_tooltip_mapping_is_nonempty():
    assert all(value.strip() for value in DLSS_SR_TOOLTIPS.values())


def test_dlss_sr_dimensions_match_validated_modes():
    assert _target(1280, 720, "DLAA") == (1280, 720)
    assert _target(1280, 720, "Quality") == (1920, 1080)
    assert _target(960, 540, "Performance") == (1920, 1080)
    with pytest.raises(ValueError):
        _target(640, 360, "Ultra Quality")


def test_stream_response_rejects_malformed_payload():
    import io

    malformed = OUTPUT_HEADER.pack(INPUT_MAGIC, 0, 1, 1, 0, 8)
    with pytest.raises(RuntimeError, match="Invalid"):
        _read_response(io.BytesIO(malformed), 4)
