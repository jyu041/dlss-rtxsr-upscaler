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

    selected = stream._select_encoder("H.264", 1920, 1080)

    assert calls == [("H.264", 1920, 1080)]
    assert selected["codec"] == "H.264"
    assert selected["encoder"] == "h264_nvenc"
    assert selected["fallback"] is False


def test_vsr_h264_preflight_auto_falls_back_to_hevc_when_same_size_passes(monkeypatch):
    calls = []

    def fake_preflight(codec, width, height):
        calls.append((codec, width, height))
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

    selected = stream._select_encoder("H.264", 5120, 2880)

    assert calls == [
        ("H.264", 5120, 2880),
        ("HEVC", 5120, 2880),
    ]
    assert selected["requested_codec"] == "H.264"
    assert selected["codec"] == "HEVC"
    assert selected["encoder"] == "hevc_nvenc"
    assert selected["fallback"] is True
    assert "InitializeEncoder failed" in selected["fallback_reason"]


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
        stream._select_encoder("HEVC", 8192, 4320)
