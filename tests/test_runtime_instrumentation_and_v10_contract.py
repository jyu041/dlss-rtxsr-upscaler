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


def test_dlss5_v10_static_audit_workflow_pins_archive_and_never_executes_candidate():
    workflow = (ROOT / "tools" / "audit_dlss5_v10.ps1").read_text(encoding="utf-8")
    assert "690203043" in workflow
    assert "394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515" in workflow
    assert "Visual.Enhancer.v10.0.zip" in workflow
    assert "audit_runtime_candidate.py" in workflow
    assert "--authenticode" in workflow
    assert "NO_V10_DLL_EXECUTED=1" in workflow
    assert "Start-Process" not in workflow
    assert "rundll32" not in workflow.lower()


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


def test_instrumented_workflow_requires_explicit_gpu_validation_switch():
    workflow = (ROOT / "tools" / "build_validate_dlssg_instrumented.ps1").read_text(encoding="utf-8")
    assert "[switch]$Validate256" in workflow
    assert "[switch]$ValidatePractical" in workflow
    assert "[switch]$ValidatePracticalGrid4" in workflow
    assert "$matrixSwitches.Count -gt 1" in workflow
    assert "if (-not $Validate256 -and -not $ValidatePractical -and -not $ValidatePracticalGrid4)" in workflow
    assert "GPU_VALIDATION_SKIPPED" in workflow
    assert "bin-instrumented" in workflow
    assert "validate_dlssg_instrumented.py" in workflow


def test_dlssg_instrumented_build_does_not_default_to_validated_worker_directory():
    build = (ROOT / "native" / "dlssg_sm86_offline" / "build.ps1").read_text(encoding="utf-8")
    assert '[string]$Output = "$PSScriptRoot\\bin-instrumented"' in build
    assert '[string]$Output = "$PSScriptRoot\\bin"' not in build


def test_nvof_gpu_timestamp_is_labeled_as_cross_engine_bracket():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.cpp").read_text(encoding="utf-8")
    worker = (ROOT / "native" / "dlssg_sm86_offline" / "community_run2x.cpp").read_text(encoding="utf-8")
    header = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.h").read_text(encoding="utf-8")
    assert "NvofGpuTimings" in header
    assert "state.queue->Wait(state.ofFence, state.ofFenceValue)" in source
    assert "D3D12_QUERY_HEAP_TYPE_TIMESTAMP" in source
    assert "timings->bracketMs = elapsed(0, 1);" in source
    assert "timings->conversionMs = elapsed(1, 2);" in source
    assert "stage=nvof_bracket" in worker
    assert "stage=nvof_conversion" in worker
    assert "stage=nvof_execute" not in worker


def test_instrumented_timing_switch_is_child_only():
    validator = (ROOT / "tools" / "validate_dlssg_candidate.py").read_text(encoding="utf-8")
    assert 'if args.instrumented_timing and not args.child:' in validator
    assert '--instrumented-timing is reserved for bounded child validation' in validator


def test_dlssg_gpu_timestamp_instrumentation_is_explicit_opt_in_and_protocol_v4():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "community_run2x.cpp").read_text(encoding="utf-8")
    protocol = (ROOT / "native" / "dlssg_sm86_offline" / "worker_protocol.h").read_text(encoding="utf-8")
    validator = (ROOT / "tools" / "validate_dlssg_instrumented.py").read_text(encoding="utf-8")
    child = (ROOT / "tools" / "validate_dlssg_candidate.py").read_text(encoding="utf-8")
    assert 'GetEnvironmentVariableW(L"DLSSG_GPU_TIMESTAMPS"' in source
    assert "gpuTimestamps_.Initialize(device_, queue_, gpuTimestampsEnabled_)" in source
    assert 'RunLog("GPU_TIMESTAMP frame=%llu stage=%s index=%u ms=%.6f frequency=%llu"' in source
    assert '"DLSSG_GPU_TIMESTAMPS": "1"' in validator
    assert '"DLSSG_NVOF_DIRECTION": "forward"' in validator
    assert '"DLSSG_NVOF_GPU_FLOW": "1"' in validator
    assert '"--instrumented-timing"' in validator
    assert "diagnostic_mode=not instrumented_timing" in child
    assert "constexpr uint16_t kVersion = 4;" in protocol
    assert "static_assert(sizeof(ProcessResponse) == 160);" in protocol


def test_mfg_instrumented_build_keeps_generated_shader_artifacts_out_of_source_tree():
    build = (ROOT / "native" / "dlssg_sm86_offline" / "build.ps1").read_text(encoding="utf-8")
    source = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.cpp").read_text(encoding="utf-8")
    assert "$generatedHeader = Join-Path $Output 'flow_convert_bytecode.h'" in build
    assert "Join-Path $PSScriptRoot 'flow_convert_bytecode.h'" not in build
    assert '/I"$Output"' in build
    assert '#include <flow_convert_bytecode.h>' in source
    assert 'native worker compilation failed with exit code $LASTEXITCODE' in build


def test_nvof_gpu_timestamp_samples_cannot_be_silently_overwritten():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.cpp").read_text(encoding="utf-8")
    assert "state.timingEnabled && state.timingPending" in source
    assert "NVOF_GPU_TIMESTAMP_PENDING_UNCONSUMED" in source
    assert "state.timingPending = false;" in source


def test_nvof_header_forward_declares_resource_type():
    header = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.h").read_text(encoding="utf-8")
    assert "struct ID3D12Resource;" in header


def test_mfg_gpu_timestamp_probe_covers_4x_and_releases_resources():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "community_run2x.cpp").read_text(encoding="utf-8")
    assert "static constexpr UINT kCapacity = 16;" in source
    assert 'static_assert(kCapacity >= 12, "4X GPU timing requires twelve timestamp slots");' in source
    assert "~GpuTimestampProbe() { Release(); }" in source
    assert "RunRelease(readback);" in source
    assert "RunRelease(heap);" in source


def test_nvof_coarse_grid_is_explicit_opt_in_and_dense_default_is_preserved():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "nvof_d3d12.cpp").read_text(encoding="utf-8")
    shader = (ROOT / "native" / "dlssg_sm86_offline" / "flow_convert.hlsl").read_text(encoding="utf-8")
    validator = (ROOT / "tools" / "validate_dlssg_instrumented.py").read_text(encoding="utf-8")
    assert 'uint32_t outputGrid = 1;' in source
    assert 'GetEnvironmentVariableW(L"DLSSG_NVOF_OUTPUT_GRID"' in source
    assert 'NV_OF_OUTPUT_VECTOR_GRID_SIZE_4' in source
    assert 'state.outputGrid == 4' in source
    assert 'flowDesc.Width = flowWidth; flowDesc.Height = flowHeight' in source
    assert 'uint grid = max(gridSize, 1u);' in shader
    assert 'uint2 source = id.xy / grid;' in shader
    assert '"DLSSG_NVOF_OUTPUT_GRID": str(nvof_output_grid)' in validator
