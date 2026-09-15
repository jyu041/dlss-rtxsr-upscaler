import json
from pathlib import Path

import pytest

from src.backends.dlss_sr import (ATTESTATION_SCHEMA, DLSSSRBackend,
                                   VALIDATED_DLSS_SR_RUNTIME_SHA256,
                                   VALIDATED_HOST_SHA256)
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
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB" if path.name == "host.exe" else "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983")
    status = DLSSSRBackend(host, tmp_path / "result.json").status()
    assert status.state == "SELFTEST REQUIRED"


def test_failed_native_selftest(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    (tmp_path / "nvngx_dlss.dll").write_bytes(b"dll")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB" if path.name == "host.exe" else "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983")
    result.write_text(json.dumps({"status": "failed", "error": "unsupported"}), encoding="utf-8")
    status = DLSSSRBackend(host, result).status()
    assert status.state == "SELFTEST REQUIRED"
    assert not status.available


def test_successful_mocked_result(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"
    result = tmp_path / "result.json"
    host.write_bytes(b"host")
    (tmp_path / "nvngx_dlss.dll").write_bytes(b"dll")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: "E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB" if path.name == "host.exe" else "3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983")
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": True}), encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *args, **kwargs: Completed())
    identity = {"gpu_identity": "GPU-123|NVIDIA GeForce RTX 3070 Ti|610.62", "gpu_uuid": "GPU-123", "gpu_name": "NVIDIA GeForce RTX 3070 Ti", "driver_version": "610.62"}
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: identity)
    backend = DLSSSRBackend(host, result)
    data = backend.selftest()
    assert data["status"] == "success"
    attestation = json.loads((tmp_path / "attestation.json").read_text())
    assert attestation["schema"] == ATTESTATION_SCHEMA
    assert attestation["gpu_uuid"] == "GPU-123"
    status = backend.status()
    assert status.state == "READY"
    assert status.available is True


def _valid_files(tmp_path, monkeypatch):
    host = tmp_path / "host.exe"; runtime = tmp_path / "nvngx_dlss.dll"; result = tmp_path / "result.json"
    host.write_bytes(b"host"); runtime.write_bytes(b"runtime")
    monkeypatch.setattr("src.backends.dlss_sr._sha256", lambda path: VALIDATED_HOST_SHA256 if path.name == "host.exe" else VALIDATED_DLSS_SR_RUNTIME_SHA256)
    return host, result


def test_attestation_matching_identity_is_ready(tmp_path, monkeypatch):
    host, result = _valid_files(tmp_path, monkeypatch)
    identity = {"gpu_identity": "GPU-A|RTX 3070 Ti|610.62", "gpu_uuid": "GPU-A", "gpu_name": "RTX 3070 Ti", "driver_version": "610.62"}
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: identity)
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": True}), encoding="utf-8")
    class Completed: returncode = 0; stdout = ""; stderr = ""
    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *a, **k: Completed())
    backend = DLSSSRBackend(host, result); backend.selftest()
    assert backend.status().state == "READY"


@pytest.mark.parametrize("field,value", [("gpu_uuid", "GPU-B"), ("driver_version", "610.63")])
def test_attestation_machine_mismatch_requires_selftest(tmp_path, monkeypatch, field, value):
    host, result = _valid_files(tmp_path, monkeypatch)
    identity = {"gpu_identity": "GPU-A|RTX 3070 Ti|610.62", "gpu_uuid": "GPU-A", "gpu_name": "RTX 3070 Ti", "driver_version": "610.62"}
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: identity)
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": True}), encoding="utf-8")
    class Completed: returncode = 0; stdout = ""; stderr = ""
    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *a, **k: Completed())
    backend = DLSSSRBackend(host, result); backend.selftest()
    changed = dict(identity); changed[field] = value; changed["gpu_identity"] = "changed"
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: changed)
    assert backend.status().state == "SELFTEST REQUIRED"


def test_old_attestation_schema_requires_selftest(tmp_path, monkeypatch):
    host, result = _valid_files(tmp_path, monkeypatch)
    identity = {"gpu_identity": "GPU-A|RTX 3070 Ti|610.62", "gpu_uuid": "GPU-A", "gpu_name": "RTX 3070 Ti", "driver_version": "610.62"}
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: identity)
    (tmp_path / "attestation.json").write_text(json.dumps({"schema": "dlss-sr-attestation-v1", "selftest_success": True}), encoding="utf-8")
    assert DLSSSRBackend(host, result).status().state == "SELFTEST REQUIRED"


def test_failed_new_selftest_removes_previous_attestation(tmp_path, monkeypatch):
    host, result = _valid_files(tmp_path, monkeypatch)
    identity = {"gpu_identity": "GPU-A|RTX 3070 Ti|610.62", "gpu_uuid": "GPU-A", "gpu_name": "RTX 3070 Ti", "driver_version": "610.62"}
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: identity)
    attestation = tmp_path / "attestation.json"
    attestation.write_text(json.dumps({"schema": ATTESTATION_SCHEMA, "selftest_success": True}), encoding="utf-8")
    result.write_text(json.dumps({"status": "failed", "evaluate_succeeded": False}), encoding="utf-8")
    class Completed: returncode = 1; stdout = ""; stderr = "failed"
    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *a, **k: Completed())
    with pytest.raises(RuntimeError): DLSSSRBackend(host, result).selftest()
    assert not attestation.exists()


def test_success_without_evaluate_does_not_attest(tmp_path, monkeypatch):
    host, result = _valid_files(tmp_path, monkeypatch)
    result.write_text(json.dumps({"status": "success", "evaluate_succeeded": False}), encoding="utf-8")
    monkeypatch.setattr(DLSSSRBackend, "_machine_identity", lambda self: {"gpu_identity": "GPU-A", "gpu_uuid": "GPU-A", "gpu_name": "RTX 3070 Ti", "driver_version": "610.62"})
    class Completed: returncode = 0; stdout = ""; stderr = ""
    monkeypatch.setattr("src.backends.dlss_sr.subprocess.run", lambda *a, **k: Completed())
    with pytest.raises(RuntimeError): DLSSSRBackend(host, result).selftest()
    assert not (tmp_path / "attestation.json").exists()


def test_identity_gate_blocks_execution_before_subprocess(tmp_path, monkeypatch):
    backend = DLSSSRBackend(tmp_path / "host.exe", tmp_path / "result.json")
    called = []
    monkeypatch.setattr("src.video.dlss_sr.subprocess.run", lambda *a, **k: called.append(a) or None)
    with pytest.raises(RuntimeError, match="missing"):
        __import__("src.video.dlss_sr", fromlist=["process_dlss_sr_frame"]).process_dlss_sr_frame(
            __import__("numpy").zeros((4, 4, 4), dtype="uint8"), backend)
    assert not called


def test_dlss_sr_processing_remains_gated(tmp_path):
    with pytest.raises(RuntimeError, match="implemented by src.video"):
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
