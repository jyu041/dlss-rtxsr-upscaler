from pathlib import Path
import io

import pytest

from src.backends.dlssg import DLSSGBackend
from src.video.dlssg import _read_frame, output_frame_count


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


def test_backend_reports_missing_external_dependencies(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    status = backend.status()
    assert not status.available
    assert "external community runtime" in status.reason


def test_backend_requires_configuration(tmp_path: Path):
    backend = DLSSGBackend(tmp_path / "worker.exe", tmp_path / "version.dll", tmp_path / "runtime")
    with pytest.raises(RuntimeError, match="unavailable"):
        backend.require_configuration()
