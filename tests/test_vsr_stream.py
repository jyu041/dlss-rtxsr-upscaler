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



def test_same_resolution_modes_route_to_reference_helper(monkeypatch, tmp_path):
    calls = []

    def fake_reference(source, destination, **kwargs):
        calls.append((source, destination, kwargs))
        return {
            "frames": 1,
            "fps": 1.0,
            "dimensions": (1280, 720),
            "audio_preserved": False,
        }

    monkeypatch.setattr(stream, "_run_reference_same_res", fake_reference)
    monkeypatch.setattr(stream, "tool", lambda _name: "ffmpeg")
    monkeypatch.setattr(
        "src.core.media_info.probe",
        lambda _path: {"width": 1280, "height": 720},
    )

    result = stream.render_vsr(
        tmp_path / "input.mp4",
        tmp_path / "output.mp4",
        backend=None,
        scale=4.0,
        quality="ULTRA",
        mode="Deblur",
        codec="H.264",
    )

    assert result["dimensions"] == (1280, 720)
    assert len(calls) == 1
    assert calls[0][2]["mode"] == "Deblur"
    assert calls[0][2]["quality"] == "ULTRA"


def test_reference_module_mirrors_nvidia_python_sample_contract():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "video"
        / "rtx_vsr_reference.py"
    ).read_text(encoding="utf-8")
    assert 'frame.to_ndarray(format="rgb24")' in source
    assert '.permute(2, 0, 1)' in source
    assert 'effect.run(rgb_input, stream_ptr=stream_ptr)' in source
    assert 'torch.from_dlpack(native.image).clone()' in source
    assert '.permute(1, 2, 0)' in source



def test_same_resolution_vfx_width_is_aligned_to_8_without_changing_public_size():
    from src.video.rtx_vsr_reference import _native_same_res_width

    assert _native_same_res_width(1434) == 1440
    assert _native_same_res_width(1435) == 1440
    assert _native_same_res_width(1440) == 1440
    assert _native_same_res_width(1920) == 1920


def test_same_resolution_reference_path_pads_right_edge_and_crops_back():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "video"
        / "rtx_vsr_reference.py"
    ).read_text(encoding="utf-8")
    assert 'mode="replicate"' in source
    assert "effect.input_width = native_width" in source
    assert "effect.output_width = native_width" in source
    assert "rgb_output = rgb_output[:, :, :width].contiguous()" in source
