from fractions import Fraction
from pathlib import Path

import av

from src.video import dlssg


class _Codec:
    name = "h264"


class _Format:
    name = "yuv420p"


class _CodecContext:
    codec = _Codec()
    format = _Format()
    color_range = 0
    colorspace = 0
    color_primaries = 0
    color_trc = 0


class _VideoStream:
    codec_context = _CodecContext()
    average_rate = Fraction(30, 1)
    base_rate = Fraction(30, 1)
    width = 1920
    height = 1080
    frames = 30


class _Streams:
    video = [_VideoStream()]
    audio = []


class _Container:
    streams = _Streams()
    duration = av.time_base

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


def test_probe_video_allows_non_utf8_container_metadata(tmp_path, monkeypatch):
    source = tmp_path / "metadata.mp4"
    source.write_bytes(b"placeholder")
    seen = {}

    def fake_open(path, **kwargs):
        seen["path"] = path
        seen["kwargs"] = kwargs
        return _Container()

    monkeypatch.setattr(av, "open", fake_open)

    info = dlssg.probe_video(source)

    assert seen["path"] == str(source.resolve())
    assert seen["kwargs"]["metadata_errors"] == "replace"
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["fps"] == 30.0


def test_dlssg_pyav_tools_use_tolerant_metadata_decoding():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/video/dlssg.py",
        "tools/validate_dlssg_video.py",
        "tools/capture_mfg_grid_quality_ab.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert 'av.open(str(path), metadata_errors="replace")' in source
