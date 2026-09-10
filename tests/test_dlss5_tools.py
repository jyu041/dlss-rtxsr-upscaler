import numpy as np
import pytest

from src.backends.dlss5_benchmark import parse_resolutions, parse_working_scales
from src.backends.dlss5 import validate_working_scale_for_options
from src.backends.dlss5_recompose import compute_working_dimensions, downsample_for_nr, residual_recompose
from src.video.nvenc import build_preflight_command, format_preflight_failure
from src.backends.dlss5_diagnostics import collect


def test_resolution_parsing():
    assert parse_resolutions("128x128,960x540") == [(128, 128), (960, 540)]
    assert parse_working_scales("1,0.75,0.6666666667,0.5") == [1.0, 0.75, 2.0 / 3.0, 0.5]


def test_working_dimensions_are_even_and_aspect_preserving():
    assert compute_working_dimensions(1920, 1080, 1.0) == (1920, 1080)
    assert compute_working_dimensions(1920, 1080, 0.75) == (1440, 810)
    assert compute_working_dimensions(1920, 1080, 2 / 3) == (1280, 720)
    assert compute_working_dimensions(1920, 1080, 0.5) == (960, 540)
    assert compute_working_dimensions(7, 5, 0.5) == (4, 2)
    with pytest.raises(ValueError):
        compute_working_dimensions(10, 10, 0)


def test_reduced_working_scale_requires_native_dlss_output():
    native = type("Options", (), {"upscaling_factor": 1.0})()
    scaled = type("Options", (), {"upscaling_factor": 2.0})()
    assert validate_working_scale_for_options(native, 0.5) == 0.5
    assert validate_working_scale_for_options(scaled, 1.0) == 1.0
    with pytest.raises(ValueError, match="requires DLSS5 output scale 1.0x"):
        validate_working_scale_for_options(scaled, 0.5)


def test_residual_composition_zero_positive_negative_clipping_and_alpha():
    native = np.zeros((4, 6, 4), dtype=np.uint8)
    native[..., :3] = 100
    native[..., 3] = 37
    small = np.full((2, 3, 4), 100, dtype=np.uint8)
    assert np.array_equal(residual_recompose(native, small, small), native)
    positive = small.copy(); positive[..., :3] = 110
    result = residual_recompose(native, small, positive)
    assert np.all(result[..., :3] == 110) and np.all(result[..., 3] == 37)
    negative = small.copy(); negative[..., :3] = 80
    result = residual_recompose(native, small, negative)
    assert np.all(result[..., :3] == 80)
    low = small.copy(); low[..., :3] = 0
    assert np.min(residual_recompose(native, small, low)[..., :3]) >= 0
    high = small.copy(); high[..., :3] = 255
    assert np.max(residual_recompose(native, small, high)[..., :3]) <= 255


def test_downsample_is_rgba_and_native_shape_is_preserved():
    source = np.zeros((5, 7, 4), dtype=np.uint8)
    assert downsample_for_nr(source, 4, 4).shape == (4, 4, 4)


def test_nvenc_command_uses_requested_codec_and_size():
    command = build_preflight_command("HEVC", 960, 540, "ffmpeg.exe")
    assert command[0] == "ffmpeg.exe"
    assert any("960x540" in item for item in command)
    assert command[command.index("-c:v") + 1] == "hevc_nvenc"


def test_nvenc_error_identifies_dlss5_boundary():
    message = format_preflight_failure({"codec": "H.264", "encoder": "h264_nvenc", "width": 1280, "height": 720, "stderr_tail": "No NVENC device"})
    assert "Feature-18 processing reached output successfully" in message
    assert "H.264 1280x720" in message
    assert "No NVENC device" in message


def test_diagnostics_warns_about_public_path_redaction():
    assert "redact paths" in collect()["public_warning"]
