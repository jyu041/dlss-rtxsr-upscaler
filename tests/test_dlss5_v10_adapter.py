from io import BytesIO
from pathlib import Path

import pytest

import src.backends.dlss5_v10_adapter as adapter
from src.backends.dlss5_v10_host import contract_report, main as host_main
from src.backends.dlss5_v10_protocol import (
    CREATE,
    FRAME,
    CLOSE,
    HEADER,
    MAGIC,
    PROTOCOL_VERSION,
    CreateRequest,
    FrameRequest,
    OutputEvidence,
    SessionGuard,
    V10ProtocolError,
    V10SessionPoisoned,
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


def test_v10_create_schema_matches_upstream_bounds_and_geometry():
    request = CreateRequest(
        input_width=1920,
        input_height=1080,
        processing_scale=1.5,
        style=2,
        intensity=1.25,
        nr_passes=3,
        local_tone=1.0,
        local_structure=0.5,
        skin_structure=-0.25,
        color_strength=0.8,
        tone_preservation=0.2,
        face_skin_protection=0.3,
        grain_preservation=0.4,
        shimmer_suppression=0.7,
        automatic_mask=False,
        prefer_nvof=True,
    )
    assert request.output_size == (2880, 1620)
    wire = request.to_wire()
    assert wire["memory_type"] == "host"
    assert wire["pixel_format"] == "rgba8"
    assert CreateRequest.from_wire(wire) == request


@pytest.mark.parametrize("scale", [0.1, 0.9, 3.0])
def test_v10_create_schema_rejects_unsupported_scales(scale):
    with pytest.raises(V10ProtocolError, match="processing_scale"):
        CreateRequest(1920, 1080, processing_scale=scale).validate()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("style", 3),
        ("nr_passes", 0),
        ("nr_passes", 5),
        ("intensity", 2.1),
        ("local_tone", -0.1),
        ("local_structure", 2.1),
        ("skin_structure", -1.1),
        ("color_strength", 1.1),
        ("tone_preservation", -0.1),
        ("face_skin_protection", 1.1),
        ("grain_preservation", 1.1),
        ("shimmer_suppression", 1.1),
    ],
)
def test_v10_create_schema_rejects_out_of_range_controls(field, value):
    values = {"input_width": 256, "input_height": 256, field: value}
    with pytest.raises(V10ProtocolError):
        CreateRequest(**values).validate()


def test_v10_create_schema_enforces_neural_dimension_boundary():
    assert CreateRequest(256, 256, processing_scale=0.25).output_size == (64, 64)
    with pytest.raises(V10ProtocolError, match="below"):
        CreateRequest(128, 128, processing_scale=0.25).validate()
    with pytest.raises(V10ProtocolError, match="exceeds"):
        CreateRequest(7680, 4320, processing_scale=2.0).validate()


def test_v10_frame_payload_is_exact_tightly_packed_rgba8():
    rgba = bytes(range(64)) * (64 * 64 * 4 // 64)
    frame = FrameRequest(timestamp=123456, reset=True, rgba=rgba)
    payload = frame.encode(64, 64)
    decoded = FrameRequest.decode(payload, 64, 64)
    assert decoded == frame
    with pytest.raises(V10ProtocolError, match="FRAME payload"):
        FrameRequest.decode(payload[:-1], 64, 64)


def test_v10_output_payload_retains_feature18_evidence():
    rgba = bytes([7, 8, 9, 255]) * (64 * 64)
    evidence = OutputEvidence(
        width=64,
        height=64,
        timestamp=99,
        ngx_create_result=0,
        ngx_evaluate_result=0,
        cuda_result=0,
        scene_reset=1,
        scene_score=0.125,
        upload_bytes=len(rgba),
        download_bytes=len(rgba),
        rgba=rgba,
    )
    decoded = OutputEvidence.decode(evidence.encode())
    assert decoded.width == 64
    assert decoded.height == 64
    assert decoded.timestamp == 99
    assert decoded.ngx_create_result == 0
    assert decoded.ngx_evaluate_result == 0
    assert decoded.scene_reset == 1
    assert decoded.scene_score == pytest.approx(0.125)
    assert decoded.rgba == rgba


def test_v10_session_guard_requires_exact_order_and_poison_is_terminal():
    guard = SessionGuard()
    with pytest.raises(V10ProtocolError, match="CREATE"):
        guard.accept_frame(1)
    guard.accept_create(1)
    guard.accept_frame(2)
    with pytest.raises(V10ProtocolError, match="expected 3"):
        guard.accept_frame(4)
    guard.poison("native timeout")
    with pytest.raises(V10SessionPoisoned, match="native timeout"):
        guard.accept_frame(3)
    # CLOSE remains available as a parent-side terminal protocol action.
    guard.accept_close(3)
    assert guard.closed is True


def test_v10_session_guard_create_is_single_use_and_request_zero_is_reserved():
    guard = SessionGuard()
    with pytest.raises(V10ProtocolError, match="expected 1"):
        guard.accept_create(0)
    guard.accept_create(1)
    with pytest.raises(V10ProtocolError, match="only valid once"):
        guard.accept_create(2)


def test_v10_create_wire_rejects_unknown_fields_and_non_host_memory():
    value = CreateRequest(256, 256).to_wire()
    value["unexpected"] = 1
    with pytest.raises(V10ProtocolError, match="fields mismatch"):
        CreateRequest.from_wire(value)

    value = CreateRequest(256, 256).to_wire()
    value["memory_type"] = "cuda"
    with pytest.raises(V10ProtocolError, match="host-memory RGBA8"):
        CreateRequest.from_wire(value)


def test_v10_protocol_rejects_truncated_header_and_payload():
    with pytest.raises(EOFError):
        read_message(BytesIO(b"NR10"))
    message = encode_message(FRAME, 1, b"abc")
    with pytest.raises(EOFError):
        read_message(BytesIO(message[:-1]))


def test_v10_protocol_rejects_unknown_command_and_oversized_declared_payload():
    unknown = HEADER.pack(MAGIC, PROTOCOL_VERSION, 99, 1, 0)
    with pytest.raises(V10ProtocolError, match="unknown"):
        read_message(BytesIO(unknown))

    oversized = HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        FRAME,
        1,
        64 * 1024 * 1024 + 1,
    )
    with pytest.raises(V10ProtocolError, match="safety limit"):
        read_message(BytesIO(oversized))
