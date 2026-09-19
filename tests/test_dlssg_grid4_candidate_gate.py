from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "run_dlssg_grid4_candidate.ps1"


def test_grid4_candidate_wrapper_is_explicit_and_fails_closed():
    source = WRAPPER.read_text(encoding="utf-8")

    assert "[Alias('Input')]" in source
    assert "[string]$InputPath" in source
    assert "[string]$Input," not in source
    param_block = source.split(")\n\n$ErrorActionPreference", 1)[0]
    assert "$PSScriptRoot" not in param_block
    assert "if (-not $Output)" in source
    assert "if (-not $CommunityRuntime)" in source
    assert "if (-not $OfficialRuntimeDir)" in source
    assert "Join-Path $root 'runtime\\dlssg\\legacy\\version.dll'" in source
    assert "Join-Path $root 'runtime\\dlssg\\official'" in source
    assert "build_validate_dlssg_instrumented.ps1" in source
    assert "dlssg_video.py" in source
    assert "--multiplier 2" in source
    assert "--nvof-profile grid4-gpu-candidate" in source
    assert "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916" in source
    assert "NVOF_OUTPUT_GRID_SELECTED=4 " in source
    assert "interpolation_disabled_frame_ids" in source
    assert "device_removal_results" in source
    assert "DLSSG_GRID4_CANDIDATE_PASS" in source

    assert source.index("& $build @buildArgs") < source.index("& $python $video")
    assert source.index("& $python $video") < source.index("ConvertFrom-Json")
