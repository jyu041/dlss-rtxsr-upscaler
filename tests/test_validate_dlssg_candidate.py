from types import SimpleNamespace

import pytest

from tools.validate_dlssg_candidate import validate_group, validate_reset


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
