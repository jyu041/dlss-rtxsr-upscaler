"""Versioned transport contract for the isolated DLSS5 v10 host.

This module contains framing and validation only. It does not load or execute
any native runtime.
"""

from __future__ import annotations

import json
import struct
from typing import BinaryIO


MAGIC = b"NR10"
PROTOCOL_VERSION = 1
MAX_PAYLOAD = 64 * 1024 * 1024

HELLO = 1
CREATE = 2
FRAME = 3
OUTPUT = 4
CLOSE = 5
ERROR = 6

# magic, version, command, request_id, payload_bytes
HEADER = struct.Struct("<4sHHII")


class V10ProtocolError(RuntimeError):
    pass


def encode_message(command: int, request_id: int, payload: bytes = b"") -> bytes:
    if command not in {HELLO, CREATE, FRAME, OUTPUT, CLOSE, ERROR}:
        raise ValueError(f"unknown v10 protocol command: {command}")
    if request_id < 0 or request_id > 0xFFFFFFFF:
        raise ValueError("request_id must fit uint32")
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("v10 protocol payload exceeds safety limit")
    return HEADER.pack(MAGIC, PROTOCOL_VERSION, command, request_id, len(payload)) + payload


def encode_json(command: int, request_id: int, value: object) -> bytes:
    return encode_message(
        command,
        request_id,
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"),
    )


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError(f"v10 host stream ended with {remaining} bytes still expected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> tuple[int, int, bytes]:
    header = _read_exact(stream, HEADER.size)
    magic, version, command, request_id, payload_bytes = HEADER.unpack(header)
    if magic != MAGIC:
        raise V10ProtocolError(f"invalid v10 host magic: {magic!r}")
    if version != PROTOCOL_VERSION:
        raise V10ProtocolError(
            f"v10 host protocol version {version} != {PROTOCOL_VERSION}"
        )
    if command not in {HELLO, CREATE, FRAME, OUTPUT, CLOSE, ERROR}:
        raise V10ProtocolError(f"unknown v10 host command: {command}")
    if payload_bytes > MAX_PAYLOAD:
        raise V10ProtocolError("v10 host payload exceeds safety limit")
    return command, request_id, _read_exact(stream, payload_bytes)


def decode_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise V10ProtocolError(f"invalid v10 host JSON payload: {exc}") from exc
