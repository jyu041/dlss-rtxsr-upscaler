import pytest

import src.video.stream as stream


def test_vsr_encoder_preflight_passes_selected_codec(monkeypatch):
    calls = []

    def fake_preflight(codec, width, height):
        calls.append((codec, width, height))
        return {
            "available": True,
            "codec": codec,
            "encoder": "h264_nvenc",
            "stderr_tail": "",
        }

    monkeypatch.setattr(stream, "nvenc_preflight", fake_preflight)

    stream._preflight_encoder("H.264", 1920, 1080)

    assert calls == [("H.264", 1920, 1080)]


def test_vsr_h264_preflight_suggests_hevc_when_same_size_passes(monkeypatch):
    def fake_preflight(codec, width, height):
        if codec == "H.264":
            return {
                "available": False,
                "codec": codec,
                "encoder": "h264_nvenc",
                "stderr_tail": "InitializeEncoder failed: invalid param",
            }
        return {
            "available": True,
            "codec": codec,
            "encoder": "hevc_nvenc",
            "stderr_tail": "",
        }

    monkeypatch.setattr(stream, "nvenc_preflight", fake_preflight)

    with pytest.raises(RuntimeError) as exc:
        stream._preflight_encoder("H.264", 5120, 2880)

    message = str(exc.value)
    assert "RTX VSR cannot encode 5120x2880 with H.264" in message
    assert "InitializeEncoder failed: invalid param" in message
    assert "HEVC NVENC passed at the same output size" in message
    assert "reduce the RTX VSR scale" in message


def test_vsr_hevc_preflight_preserves_exact_ffmpeg_reason(monkeypatch):
    monkeypatch.setattr(
        stream,
        "nvenc_preflight",
        lambda codec, width, height: {
            "available": False,
            "codec": codec,
            "encoder": "hevc_nvenc",
            "stderr_tail": "device does not support requested dimensions",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="device does not support requested dimensions",
    ):
        stream._preflight_encoder("HEVC", 8192, 4320)
