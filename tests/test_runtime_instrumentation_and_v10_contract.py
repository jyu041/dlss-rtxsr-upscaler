import ctypes
from pathlib import Path

from src.backends.dlss5_v10_contract import (
    BRIDGE_ABI_VERSION,
    EXPECTED_STRUCT_SIZES,
    EXPORT_SIGNATURES,
    LIFETIME_CONTRACT,
    FrameDescriptorV1,
    FrameResultV1,
    RenderParametersV6,
    REQUIRED_EXPORTS,
    struct_sizes,
    validate_static_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_dlss5_v10_contract_layout_matches_upstream_abi6():
    assert BRIDGE_ABI_VERSION == 6
    assert struct_sizes() == EXPECTED_STRUCT_SIZES
    assert ctypes.sizeof(FrameDescriptorV1) == 88
    assert ctypes.sizeof(RenderParametersV6) == 96
    assert ctypes.sizeof(FrameResultV1) == 56
    validate_static_contract()


def test_dlss5_v10_zero_initializers_stamp_size_and_abi():
    frame = FrameDescriptorV1.empty()
    params = RenderParametersV6.defaults()
    result = FrameResultV1.empty()
    assert (frame.struct_size, frame.abi_version) == (88, 6)
    assert (params.struct_size, params.abi_version) == (96, 6)
    assert (result.struct_size, result.abi_version) == (56, 6)


def test_dlss5_v10_required_export_surface_is_explicit():
    assert "dlss5nr_frame_abi_version" in REQUIRED_EXPORTS
    assert "dlss5nr_process_frame_v6" in REQUIRED_EXPORTS
    assert "dlss5nr_process_cuda_v6" in REQUIRED_EXPORTS
    assert "dlss5nr_cuda_supported" in REQUIRED_EXPORTS
    assert "dlss5nr_cuda_status" in REQUIRED_EXPORTS
    assert "dlss5nr_surface_create" in REQUIRED_EXPORTS
    assert set(EXPORT_SIGNATURES) == set(REQUIRED_EXPORTS)


def test_dlss5_v10_v6_entrypoint_signatures_match_upstream_binding():
    assert EXPORT_SIGNATURES["dlss5nr_init"] == (
        ("int", "wchar*", "char*", "int"),
        "int",
    )
    assert EXPORT_SIGNATURES["dlss5nr_process_v6"] == (
        ("float*", "float*", "int", "int", "RenderParametersV6*", "char*", "int"),
        "int",
    )
    assert EXPORT_SIGNATURES["dlss5nr_process_cuda_v6"] == (
        ("uint64", "uint64", "int", "int", "uint64", "RenderParametersV6*", "char*", "int"),
        "int",
    )
    assert EXPORT_SIGNATURES["dlss5nr_process_frame_v6"] == (
        (
            "FrameDescriptorV1*",
            "FrameDescriptorV1*",
            "RenderParametersV6*",
            "FrameResultV1*",
            "char*",
            "int",
        ),
        "int",
    )


def test_dlss5_v10_lifetime_contract_does_not_reuse_v3_shutdown_assumptions():
    assert LIFETIME_CONTRACT["feature_id"] == 18
    assert LIFETIME_CONTRACT["bridge_abi_version"] == 6
    assert LIFETIME_CONTRACT["normal_close_calls_ngx_shutdown"] is False
    assert LIFETIME_CONTRACT["normal_close_unloads_driver_modules"] is False


def test_dlssg_instrumented_build_does_not_default_to_validated_worker_directory():
    build = (ROOT / "native" / "dlssg_sm86_offline" / "build.ps1").read_text(encoding="utf-8")
    assert '[string]$Output = "$PSScriptRoot\\bin-instrumented"' in build
    assert '[string]$Output = "$PSScriptRoot\\bin"' not in build


def test_dlssg_gpu_timestamp_instrumentation_is_diagnostic_only_and_protocol_v4():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "community_run2x.cpp").read_text(encoding="utf-8")
    protocol = (ROOT / "native" / "dlssg_sm86_offline" / "worker_protocol.h").read_text(encoding="utf-8")
    assert "gpuTimestamps_.Initialize(device_, queue_, diagnosticMode_)" in source
    assert 'RunLog("GPU_TIMESTAMP frame=%llu stage=%s index=%u ms=%.6f frequency=%llu"' in source
    assert "constexpr uint16_t kVersion = 4;" in protocol
    assert "static_assert(sizeof(ProcessResponse) == 160);" in protocol
