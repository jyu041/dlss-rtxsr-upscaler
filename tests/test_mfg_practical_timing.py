from pathlib import Path

from tools.validate_dlssg_instrumented import MATRICES


ROOT = Path(__file__).resolve().parents[1]


def test_instrumented_matrices_are_bounded_and_explicit():
    bounded = MATRICES["bounded"]
    practical = MATRICES["practical"]
    assert bounded["geometries"] == ((256, 256),)
    assert bounded["multipliers"] == (2, 3, 4)
    assert practical["geometries"] == ((1280, 720), (1920, 1080))
    assert practical["multipliers"] == (2, 4)
    assert int(practical["timeout"]) >= int(bounded["timeout"])


def test_production_validator_keeps_practical_geometry_child_only():
    source = (ROOT / "tools" / "validate_dlssg_candidate.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--width"' in source
    assert 'parser.add_argument("--height"' in source
    assert "practical geometry is reserved for instrumented child validation" in source
    assert "non-default child geometry requires --instrumented-timing" in source
    assert "width > 1920 or height > 1080" in source


def test_instrumented_wrapper_requires_explicit_matrix_switch():
    source = (ROOT / "tools" / "build_validate_dlssg_instrumented.ps1").read_text(encoding="utf-8")
    assert "[switch]$Validate256" in source
    assert "[switch]$ValidatePractical" in source
    assert "$Validate256 -and $ValidatePractical" in source
    assert "'--matrix', $matrix" in source
    assert "mfg-instrumented-practical-validation.json" in source


def test_native_build_preflights_complete_sdk_header_sets():
    source = (ROOT / "native" / "dlssg_sm86_offline" / "build.ps1").read_text(encoding="utf-8")
    for token in (
        "nvsdk_ngx.h",
        "nvsdk_ngx_d.lib",
        "nvapi.h",
        "nvapi_lite_common.h",
        "nvapi_lite_salstart.h",
        "nvapi_lite_salend.h",
        "nvOpticalFlowD3D12.h",
        "nvOpticalFlowCommon.h",
    ):
        assert token in source
    assert "third_party\\local\\nvapi" in source
    assert "third_party\\local\\nvidia-optical-flow-sdk" in source
