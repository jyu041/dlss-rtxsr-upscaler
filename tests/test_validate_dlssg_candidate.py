from types import SimpleNamespace
import subprocess
import sys
import threading

import pytest

from tools.validate_dlssg_candidate import (
    VALIDATION_HEIGHT,
    VALIDATION_WIDTH,
    _drain_child_output,
    validate_group,
    validate_reset,
)


def result(count=1, outputs=None, disable=0, width=64, height=64, pixel_format=28, reset_only=False):
    return SimpleNamespace(generated_count=count, outputs=outputs if outputs is not None else [b"x" * (width * height * 4)] * count,
                           disable_interpolation=disable, width=width, height=height, pixel_format=pixel_format, reset_only=reset_only)


def test_reset_v4_requires_exact_no_output():
    validate_reset(result(count=0, outputs=[], reset_only=True))
    with pytest.raises(RuntimeError):
        validate_reset(result(count=1, reset_only=False))


@pytest.mark.parametrize("count", [0, 1, 3])
def test_group_requires_exact_multiplier_count(count):
    if count == 1:
        validate_group(result(count=1), 2, 64, 64)
    else:
        with pytest.raises(RuntimeError):
            validate_group(result(count=count), 2, 64, 64)


def test_group_rejects_disabled_or_bad_shape_format_and_bytes():
    with pytest.raises(RuntimeError): validate_group(result(disable=1), 2, 64, 64)
    with pytest.raises(RuntimeError): validate_group(result(width=32), 2, 64, 64)
    with pytest.raises(RuntimeError): validate_group(result(pixel_format=87), 2, 64, 64)
    with pytest.raises(RuntimeError): validate_group(result(outputs=[b"short"]), 2, 64, 64)


def test_4x_requires_three_outputs():
    validate_group(result(count=3), 4, 64, 64)
    with pytest.raises(RuntimeError): validate_group(result(count=1), 4, 64, 64)


def test_child_output_drainer_prevents_large_pipe_deadlock():
    payload_lines = 5000
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "for i in range(5000):\n"
                "    print(f'{i:05d}:' + 'x' * 120, flush=True)\n"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    lines = []
    reader = threading.Thread(
        target=_drain_child_output,
        args=(process.stdout, lines),
        kwargs={"echo": False},
        daemon=True,
    )
    reader.start()
    assert process.wait(timeout=10) == 0
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert len(lines) == payload_lines
    assert lines[0].startswith("00000:")
    assert lines[-1].startswith("04999:")


def test_validator_uses_preserved_256_square_contract():
    assert VALIDATION_WIDTH == 256
    assert VALIDATION_HEIGHT == 256
