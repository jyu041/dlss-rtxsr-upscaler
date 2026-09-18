from io import BytesIO
from pathlib import Path

import pytest

import src.backends.dlss5_v10_adapter as adapter
from src.backends.dlss5_v10_host import contract_report, main as host_main
from src.backends.dlss5_v10_protocol import (
    CREATE,
    FRAME,
    HEADER,
    MAGIC,
    PROTOCOL_VERSION,
    V10ProtocolError,
    decode_json,
    encode_json,
    encode_message,
    read_message,
)
from src.backends.dlss5_v10_static import V10StaticStatus


def test_v10_protocol_roundtrip_binary_and_json():
    wire = encode_message(FRAME, 7, b"abc")
    assert len(wire) == HEADER.size + 3
    assert read_message(BytesIO(wire)) == (FRAME, 7, b"abc")

    json_wire = encode_json(CREATE, 8, {"width": 256, "height": 256})
    command, request_id, payload = read_message(BytesIO(json_wire))
    assert (command, request_id) == (CREATE, 8)
    assert decode_json(payload) == {"height": 256, "width": 256}


def test_v10_protocol_rejects_wrong_magic_and_version():
    bad_magic = HEADER.pack(b"BAD!", PROTOCOL_VERSION, FRAME, 1, 0)
    with pytest.raises(V10ProtocolError, match="magic"):
        read_message(BytesIO(bad_magic))

    bad_version = HEADER.pack(MAGIC, PROTOCOL_VERSION + 1, FRAME, 1, 0)
    with pytest.raises(V10ProtocolError, match="version"):
        read_message(BytesIO(bad_version))


def test_v10_host_contract_selftest_never_loads_native():
    report = contract_report()
    assert report["status"] == "PASS"
    assert report["native_loaded"] is False
    assert report["execution_allowed"] is False
    assert report["protocol_magic"] == "NR10"
    assert report["protocol_version"] == 1
    assert report["bridge_abi_version"] == 6


def test_v10_host_serve_is_fail_closed():
    assert host_main(["--serve", "--runtime-dir", "unused"]) == 78


def test_v10_adapter_plan_requires_static_complete(monkeypatch, tmp_path):
    runtime = tmp_path / "bin" / "runtime" / "dlssnr"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(
        adapter,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "ABI_MISMATCH", False, False, "missing export", {}
        ),
    )
    with pytest.raises(RuntimeError, match="ABI_MISMATCH"):
        adapter.prepare_host_plan(tmp_path)


def test_v10_adapter_plan_is_nonexecuting_and_separate_from_v3(monkeypatch, tmp_path):
    runtime = tmp_path / "bin" / "runtime" / "dlssnr"
    runtime.mkdir(parents=True)
    for name in adapter.V10_EXPECTED_FILES:
        (runtime / name).write_bytes(b"x")

    monkeypatch.setattr(
        adapter,
        "inspect_v10_runtime",
        lambda path: V10StaticStatus(
            "STATIC_AUDIT_COMPLETE", True, False, "static pass", {}
        ),
    )
    plan = adapter.prepare_host_plan(tmp_path, python=tmp_path / "python.exe")
    assert plan.runtime_dir == runtime.resolve()
    assert plan.execution_allowed is False
    assert plan.protocol_version == 1
    assert plan.module == "src.backends.dlss5_v10_host"
    assert "src.backends.dlss5_v10_host" in plan.command
    assert "--serve" in plan.command
    module_index = plan.command.index("-m") + 1
    assert plan.command[module_index] == "src.backends.dlss5_v10_host"
    assert plan.command[module_index] != "src.backends.dlss5"


def test_v10_adapter_launch_remains_disabled():
    with pytest.raises(adapter.V10ExecutionDisabled, match="execution is disabled"):
        adapter.launch_host()


def test_v10_host_source_has_no_native_loader():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "backends"
        / "dlss5_v10_host.py"
    ).read_text(encoding="utf-8")
    assert "ctypes.CDLL" not in source
    assert "WinDLL" not in source
    assert "LoadLibrary" not in source
