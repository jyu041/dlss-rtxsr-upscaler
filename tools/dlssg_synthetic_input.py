"""Deterministic CPU-only producer/parser for the DLSS-G worker protocol."""
import argparse
import io
import struct

SETUP_MAGIC, FRAME_MAGIC = 0x31534746, 0x31464746
WIDTH = HEIGHT = 256
FRAME_BYTES = WIDTH * HEIGHT * 4
MOTION_BYTES = WIDTH * HEIGHT * 4


def half(value: float) -> bytes:
    # struct's IEEE-754 binary16 implementation is part of Python 3.6+.
    return struct.pack("<e", value)


def motion(dx: float, dy: float) -> bytes:
    pair = half(dx) + half(dy)
    return pair * (WIDTH * HEIGHT)


def rgba(square_x: int) -> bytes:
    pixels = bytearray(FRAME_BYTES)
    for y in range(64, 128):
        for x in range(square_x, square_x + 64):
            at = (y * WIDTH + x) * 4
            pixels[at:at + 4] = b"\xff\xff\xff\xff"
    return bytes(pixels)


def frame(index: int, reset: int, square_x: int, dx: float, dy: float) -> bytes:
    header = struct.pack("<IIIIqq", FRAME_MAGIC, index, reset, 0, index, 1)
    return header + rgba(square_x) + motion(dx, dy)


def stream() -> bytes:
    setup = struct.pack("<IIIII", SETUP_MAGIC, WIDTH, HEIGHT, 2, 1)
    return setup + frame(0, 1, 64, 0.0, 0.0) + frame(1, 0, 72, -8.0, 0.0)


def validate(data: bytes) -> None:
    reader = io.BytesIO(data)
    setup = struct.unpack("<IIIII", reader.read(20))
    assert setup == (SETUP_MAGIC, WIDTH, HEIGHT, 2, 1)
    for expected_index, expected_x, expected_motion in ((0, 64, (0.0, 0.0)), (1, 72, (-8.0, 0.0))):
        header = struct.unpack("<IIIIqq", reader.read(32))
        assert header[:3] == (FRAME_MAGIC, expected_index, 1 if expected_index == 0 else 0)
        pixels = reader.read(FRAME_BYTES)
        assert len(pixels) == FRAME_BYTES
        assert pixels[(64 * WIDTH + expected_x) * 4:(64 * WIDTH + expected_x) * 4 + 4] == b"\xff\xff\xff\xff"
        raw_motion = reader.read(MOTION_BYTES)
        assert len(raw_motion) == MOTION_BYTES
        assert struct.unpack("<ee", raw_motion[:4]) == expected_motion
        assert struct.unpack("<ee", raw_motion[-4:]) == expected_motion
    assert reader.read(1) == b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    data = stream()
    validate(data)
    if args.output:
        with open(args.output, "wb") as target:
            target.write(data)
    elif not args.validate:
        import sys
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
