import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import dlssg_synthetic_input as sut


def test_exact_cpu_only_worker_protocol():
    data = sut.stream()
    sut.validate(data)
    assert len(data) == 20 + 2 * (32 + sut.FRAME_BYTES + sut.MOTION_BYTES)
    assert struct.unpack("<ee", sut.motion(-8.0, 0.0)[:4]) == (-8.0, 0.0)
