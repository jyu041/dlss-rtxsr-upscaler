from pathlib import Path
import io

import pytest

from src.backends.dlssg import DLSSGBackend
from src.video.dlssg import _bitstream_color_options, _read_frame, output_frame_count, scene_cut_metrics


class ShortReadStream:
    def __init__(self, data: bytes, chunk_size: int):
        self._stream = io.BytesIO(data)
        self._chunk_size = chunk_size

    def read(self, size: int) -> bytes:
        return self._stream.read(min(size, self._chunk_size))


def test_output_frame_count_duration_policy():
    assert output_frame_count(0) == 0
    assert output_frame_count(1) == 2
    assert output_frame_count(4) == 8
    assert output_frame_count(4, duplicate_terminal_frame=False) == 7


def test_raw_frame_reader_handles_short_pipe_reads():
    expected = bytes(range(32))
    stream = ShortReadStream(expected, 3)
    assert _read_frame(stream, len(expected)) == expected
    assert _read_frame(stream, len(expected)) == b""


def test_raw_frame_reader_rejects_truncated_frame():
    with pytest.raises(RuntimeError, match="truncated RGBA frame"):
        _read_frame(ShortReadStream(b"short", 2), 16)


def test_scene_cut_detector_rejects_small_motion_and_accepts_hard_cut():
    width = height = 64
    dark = bytes((16, 16, 16, 255)) * (width * height)
    small_change = bytes((20, 18, 16, 255)) * (width * height)
    bright = bytes((235, 235, 235, 255)) * (width * height)
    assert not scene_cut_metrics(dark, small_change, width, height)["is_cut"]
    decision = scene_cut_metrics(dark, bright, width, height)
    assert decision["is_cut"]
    assert decision["rgb_mad"] > 200
    assert decision["histogram_distance"] > 0.9


def test_scene_cut_detector_validates_packed_size():
    with pytest.raises(ValueError, match="tightly packed"):
        scene_cut_metrics(b"bad", b"bad", 2, 2)


def test_h264_bitstream_color_metadata_uses_source_vui_values():
    info = {"color_range": 1, "color_space": 1, "color_primaries": 1, "color_transfer": 1}
    assert _bitstream_color_options("h264_nvenc", info) == [
        "-bsf:v",
        "h264_metadata=video_full_range_flag=0:colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
    ]


def test_hevc_bitstream_color_metadata_preserves_full_range():
    info = {"color_range": 2, "color_space": 9, "color_primaries": 9, "color_transfer": 14}
    assert _bitstream_color_options("hevc_nvenc", info) == [
        "-bsf:v",
        "hevc_metadata=video_full_range_flag=1:colour_primaries=9:transfer_characteristics=14:matrix_coefficients=9",
    ]


def test_backend_reports_missing_external_dependencies(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    status = backend.status()
    assert not status.available
    assert "external community runtime" in status.reason


def test_backend_requires_configuration(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    with pytest.raises(RuntimeError, match="unavailable"):
        backend.require_configuration()
