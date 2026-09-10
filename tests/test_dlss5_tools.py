from src.backends.dlss5_benchmark import parse_resolutions
from src.video.nvenc import build_preflight_command, format_preflight_failure
from src.backends.dlss5_diagnostics import collect


def test_resolution_parsing():
    assert parse_resolutions("128x128,960x540") == [(128, 128), (960, 540)]


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
