import io

import numpy as np
import pytest

from src.video.rtx_vsr_worker import DONE, ERROR, FRAME, HEADER, MAGIC, OUTPUT, _read_message, _write_message


def test_worker_protocol_round_trip():
    stream = io.BytesIO()
    payload = b"abc"
    _write_message(stream, OUTPUT, index=4, width=2, height=1, payload=payload)
    stream.seek(0)
    assert _read_message(stream) == (OUTPUT, 4, 2, 1, payload)


def test_worker_protocol_rejects_wrong_magic():
    stream = io.BytesIO(HEADER.pack(b"NOPE", DONE, 0, 0, 0, 0))
    with pytest.raises(RuntimeError, match="Invalid"):
        _read_message(stream)


def test_worker_protocol_rejects_oversized_payload():
    stream = io.BytesIO(HEADER.pack(MAGIC, FRAME, 0, 0, 0, 64 * 1024 * 1024 + 1))
    with pytest.raises(RuntimeError, match="Invalid"):
        _read_message(stream)
