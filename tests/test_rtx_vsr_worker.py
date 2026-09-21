import io

import numpy as np
import pytest

from src.video.rtx_vsr_worker import DONE, ERROR, FRAME, HEADER, MAGIC, OUTPUT, RTXVSRSession, _native_output_layout, _read_message, _write_message


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


def test_session_rejects_wrong_output_dimensions():
    session = RTXVSRSession()
    session.process = type("Process", (), {"stdin": io.BytesIO()})()
    session.expected_output = (4, 4)
    session._wait = lambda: (OUTPUT, 0, 2, 2, b"x" * 12)
    import src.video.rtx_vsr_worker as worker
    original = worker._write_message
    worker._write_message = lambda *args, **kwargs: None
    try:
        with pytest.raises(RuntimeError, match="Invalid"):
            session.process_frame(0, np.zeros((2, 2, 3), dtype=np.uint8))
    finally:
        worker._write_message = original


def test_finish_rejects_nonzero_exit_after_done(monkeypatch):
    class Process:
        returncode = 7
        stdin = io.BytesIO()
        def wait(self, timeout=None): return 7
        def poll(self): return 7
    session = RTXVSRSession()
    session.process = Process()
    session._wait = lambda: (DONE, 0, 0, 0, b"")
    monkeypatch.setattr("src.video.rtx_vsr_worker._write_message", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="UNEXPECTED_WORKER_FAILURE_AFTER_DONE"):
        session.finish()



@pytest.mark.parametrize(
    ("shape", "width", "height", "expected"),
    [
        ((3, 720, 1280), 1280, 720, ("CHW", 3, False)),
        ((4, 720, 1280), 1280, 720, ("CHW", 4, False)),
        ((720, 1280, 3), 1280, 720, ("HWC", 3, False)),
        ((720, 1280, 4), 1280, 720, ("HWC", 4, False)),
        ((1, 3, 720, 1280), 1280, 720, ("CHW", 3, True)),
        ((1, 720, 1280, 3), 1280, 720, ("HWC", 3, True)),
    ],
)
def test_native_output_layout_accepts_channels_first_and_channels_last(shape, width, height, expected):
    assert _native_output_layout(shape, width, height) == expected


def test_native_output_layout_rejects_mismatched_geometry():
    with pytest.raises(RuntimeError, match="tensor shape"):
        _native_output_layout((3, 480, 640), 1280, 720)



def test_worker_matches_nvidia_reference_geometry_and_stream_setup():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src"
        / "video"
        / "rtx_vsr_worker.py"
    ).read_text(encoding="utf-8")
    assert "torch.cuda.set_device(0)" in source
    assert 'effect.input_width = int(options["input_width"])' in source
    assert 'effect.input_height = int(options["input_height"])' in source
    assert "stream_ptr = torch.cuda.current_stream().cuda_stream" in source
    assert "effect.run(tensor, stream_ptr=stream_ptr)" in source
