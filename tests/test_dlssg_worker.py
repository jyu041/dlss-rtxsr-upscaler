import io
import math
import struct

import pytest

from src.backends import dlssg_worker as worker


class ChunkedReader:
    def __init__(self, data: bytes, chunk: int):
        self.data = data
        self.chunk = chunk

    def read(self, size: int) -> bytes:
        take = min(size, self.chunk, len(self.data))
        result, self.data = self.data[:take], self.data[take:]
        return result


class ChunkedWriter:
    def __init__(self, chunk: int):
        self.chunk = chunk
        self.data = bytearray()

    def write(self, data) -> int:
        count = min(len(data), self.chunk)
        self.data.extend(data[:count])
        return count

    def flush(self) -> None:
        pass


def test_protocol_layout_sizes_and_roundtrip():
    assert worker.REQUEST_HEADER.size == 16
    assert worker.RESPONSE_HEADER.size == 20
    assert worker.CREATE_REQUEST.size == 24
    assert worker.PROCESS_REQUEST.size == 24
    assert worker.PROCESS_RESPONSE.size == 160
    packed = worker.REQUEST_HEADER.pack(
        worker.MAGIC, worker.PROTOCOL_VERSION, worker.COMMAND_PROCESS, 7, 123
    )
    assert worker.REQUEST_HEADER.unpack(packed) == (
        worker.MAGIC,
        worker.PROTOCOL_VERSION,
        worker.COMMAND_PROCESS,
        7,
        123,
    )


def test_exact_io_handles_partial_reads_and_writes():
    assert worker._read_exact(ChunkedReader(b"abcdef", 2), 6) == b"abcdef"
    destination = ChunkedWriter(2)
    worker._write_all(destination, b"abcdef")
    assert destination.data == b"abcdef"


def test_short_read_is_process_error():
    with pytest.raises(worker.DlssgWorkerProcessError, match="still expected"):
        worker._read_exact(io.BytesIO(b"abc"), 4)


@pytest.mark.parametrize(
    "magic,version,error",
    [
        (0, worker.PROTOCOL_VERSION, "magic"),
        (worker.MAGIC, worker.PROTOCOL_VERSION + 1, "version"),
    ],
)
def test_invalid_response_identity(magic, version, error):
    encoded = worker.RESPONSE_HEADER.pack(magic, version, worker.COMMAND_HELLO, 1, 0, 0)
    with pytest.raises(worker.DlssgWorkerProtocolError, match=error):
        worker._decode_response_header(encoded, worker.COMMAND_HELLO, 1)


def test_motion_vector_validation():
    valid = struct.pack("<ee", -8.0, 0.0) * 4
    worker.validate_motion_vectors(valid, 2, 2)
    with pytest.raises(ValueError, match="expected"):
        worker.validate_motion_vectors(valid[:-1], 2, 2)
    invalid = struct.pack("<ee", math.nan, 0.0) * 4
    with pytest.raises(ValueError, match="finite"):
        worker.validate_motion_vectors(invalid, 2, 2)


def test_process_rejects_incorrect_color_size_before_protocol_io(tmp_path):
    client = worker.DlssgWorker(
        tmp_path / "missing.exe",
        tmp_path / "missing.dll",
        tmp_path / "runtime",
    )
    client.width = client.height = 2
    client.motion_mode = worker.MOTION_MODE_EXTERNAL_R16G16_FLOAT
    with pytest.raises(ValueError, match="color payload"):
        client.process(0, b"bad", struct.pack("<ee", 0.0, 0.0) * 4, reset=True)


def test_internal_motion_mode_rejects_external_payload(tmp_path):
    client = worker.DlssgWorker(
        tmp_path / "missing.exe",
        tmp_path / "missing.dll",
        tmp_path / "runtime",
    )
    client.width = client.height = 2
    client.motion_mode = worker.MOTION_MODE_NVIDIA_OPTICAL_FLOW
    with pytest.raises(ValueError, match="does not accept"):
        client.process(0, bytes(16), bytes(16), reset=True)


def test_native_error_preserves_status_and_command():
    error = worker.DlssgNativeError(-8, worker.COMMAND_PROCESS, "diagnostic")
    assert error.status == -8
    assert error.command == worker.COMMAND_PROCESS
    assert "diagnostic" in str(error)
