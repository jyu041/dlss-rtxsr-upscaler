"""Versioned transport contract for the isolated DLSS5 v10 host.

This module contains framing and validation only. It does not load or execute
any native runtime.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from typing import BinaryIO


MAGIC = b"NR10"
PROTOCOL_VERSION = 1
MAX_PAYLOAD = 128 * 1024 * 1024

HELLO = 1
CREATE = 2
FRAME = 3
OUTPUT = 4
CLOSE = 5
ERROR = 6

# magic, version, command, request_id, payload_bytes
HEADER = struct.Struct("<4sHHII")

SUPPORTED_SCALES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
STYLE_VALUES = (0, 1, 2)
MAX_LONG_EDGE = 7680
MAX_SHORT_EDGE = 4320
MIN_EDGE = 64
MAX_RGBA_BYTES = MAX_LONG_EDGE * MAX_SHORT_EDGE * 4

# timestamp:int64, reset:uint8, seven reserved bytes, tightly-packed RGBA8 follows.
FRAME_META = struct.Struct("<qB7x")

# width:uint32, height:uint32, timestamp:int64, NGX create/evaluate/CUDA results,
# scene_reset:int32, scene_score:float32, upload/download byte counters, RGBA8 follows.
OUTPUT_META = struct.Struct("<IIqiiiifQQ")


@dataclass(frozen=True)
class CreateRequest:
    input_width: int
    input_height: int
    processing_scale: float = 1.0
    style: int = 0
    intensity: float = 1.0
    nr_passes: int = 1
    local_tone: float = 1.0
    local_structure: float = 1.0
    skin_structure: float = -1.0
    color_strength: float = 1.0
    tone_preservation: float = 0.0
    face_skin_protection: float = 0.0
    grain_preservation: float = 0.0
    shimmer_suppression: float = 0.70
    automatic_mask: bool = False
    prefer_nvof: bool = False

    @property
    def output_size(self) -> tuple[int, int]:
        return resolve_output_size(
            self.input_width, self.input_height, self.processing_scale
        )

    def validate(self) -> "CreateRequest":
        if isinstance(self.input_width, bool) or isinstance(self.input_height, bool):
            raise V10ProtocolError("input dimensions must be integers")
        if not isinstance(self.input_width, int) or not isinstance(self.input_height, int):
            raise V10ProtocolError("input dimensions must be integers")
        if self.input_width <= 0 or self.input_height <= 0:
            raise V10ProtocolError("input dimensions must be positive")
        _scale(self.processing_scale)
        if isinstance(self.style, bool) or self.style not in STYLE_VALUES:
            raise V10ProtocolError("style must be 0 (Default), 1 (Natural), or 2 (Cinematic)")
        if isinstance(self.nr_passes, bool) or not isinstance(self.nr_passes, int) or not 1 <= self.nr_passes <= 4:
            raise V10ProtocolError("nr_passes must be an integer from 1 to 4")
        for name, value, minimum, maximum in (
            ("intensity", self.intensity, 0.0, 2.0),
            ("local_tone", self.local_tone, 0.0, 2.0),
            ("local_structure", self.local_structure, 0.0, 2.0),
            ("skin_structure", self.skin_structure, -1.0, 2.0),
            ("color_strength", self.color_strength, 0.0, 1.0),
            ("tone_preservation", self.tone_preservation, 0.0, 1.0),
            ("face_skin_protection", self.face_skin_protection, 0.0, 1.0),
            ("grain_preservation", self.grain_preservation, 0.0, 1.0),
            ("shimmer_suppression", self.shimmer_suppression, 0.0, 1.0),
        ):
            _bounded_float(name, value, minimum, maximum)
        if not isinstance(self.automatic_mask, bool):
            raise V10ProtocolError("automatic_mask must be boolean")
        if not isinstance(self.prefer_nvof, bool):
            raise V10ProtocolError("prefer_nvof must be boolean")
        self.output_size
        return self

    def to_wire(self) -> dict[str, object]:
        self.validate()
        return {
            "input_width": self.input_width,
            "input_height": self.input_height,
            "processing_scale": float(self.processing_scale),
            "style": self.style,
            "intensity": float(self.intensity),
            "nr_passes": self.nr_passes,
            "local_tone": float(self.local_tone),
            "local_structure": float(self.local_structure),
            "skin_structure": float(self.skin_structure),
            "color_strength": float(self.color_strength),
            "tone_preservation": float(self.tone_preservation),
            "face_skin_protection": float(self.face_skin_protection),
            "grain_preservation": float(self.grain_preservation),
            "shimmer_suppression": float(self.shimmer_suppression),
            "automatic_mask": self.automatic_mask,
            "prefer_nvof": self.prefer_nvof,
            "memory_type": "host",
            "pixel_format": "rgba8",
        }

    @classmethod
    def from_wire(cls, value: object) -> "CreateRequest":
        if not isinstance(value, dict):
            raise V10ProtocolError("CREATE payload must be a JSON object")
        expected = {
            "input_width", "input_height", "processing_scale", "style",
            "intensity", "nr_passes", "local_tone", "local_structure",
            "skin_structure", "color_strength", "tone_preservation",
            "face_skin_protection", "grain_preservation",
            "shimmer_suppression", "automatic_mask", "prefer_nvof",
            "memory_type", "pixel_format",
        }
        if set(value) != expected:
            missing = sorted(expected - set(value))
            extra = sorted(set(value) - expected)
            raise V10ProtocolError(f"CREATE fields mismatch: missing={missing}, extra={extra}")
        if value["memory_type"] != "host" or value["pixel_format"] != "rgba8":
            raise V10ProtocolError("v10 protocol v1 supports host-memory RGBA8 only")
        kwargs = {name: value[name] for name in expected if name not in {"memory_type", "pixel_format"}}
        try:
            return cls(**kwargs).validate()
        except TypeError as exc:
            raise V10ProtocolError(f"invalid CREATE payload: {exc}") from exc


@dataclass(frozen=True)
class FrameRequest:
    timestamp: int
    reset: bool
    rgba: bytes

    def validate(self, width: int, height: int) -> "FrameRequest":
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, int):
            raise V10ProtocolError("frame timestamp must be an integer")
        if not isinstance(self.reset, bool):
            raise V10ProtocolError("frame reset must be boolean")
        expected = rgba_bytes(width, height)
        if len(self.rgba) != expected:
            raise V10ProtocolError(
                f"RGBA8 frame payload is {len(self.rgba)} bytes; expected {expected}"
            )
        return self

    def encode(self, width: int, height: int) -> bytes:
        self.validate(width, height)
        return FRAME_META.pack(self.timestamp, int(self.reset)) + bytes(self.rgba)

    @classmethod
    def decode(cls, payload: bytes, width: int, height: int) -> "FrameRequest":
        expected = FRAME_META.size + rgba_bytes(width, height)
        if len(payload) != expected:
            raise V10ProtocolError(
                f"FRAME payload is {len(payload)} bytes; expected {expected}"
            )
        timestamp, reset = FRAME_META.unpack_from(payload)
        if reset not in (0, 1):
            raise V10ProtocolError("FRAME reset flag must be 0 or 1")
        return cls(timestamp, bool(reset), payload[FRAME_META.size:]).validate(width, height)


@dataclass(frozen=True)
class OutputEvidence:
    width: int
    height: int
    timestamp: int
    ngx_create_result: int
    ngx_evaluate_result: int
    cuda_result: int
    scene_reset: int
    scene_score: float
    upload_bytes: int
    download_bytes: int
    rgba: bytes

    def encode(self) -> bytes:
        expected = rgba_bytes(self.width, self.height)
        if len(self.rgba) != expected:
            raise V10ProtocolError(
                f"OUTPUT RGBA8 payload is {len(self.rgba)} bytes; expected {expected}"
            )
        if self.scene_reset not in (0, 1):
            raise V10ProtocolError("OUTPUT scene_reset must be 0 or 1")
        if not math.isfinite(float(self.scene_score)):
            raise V10ProtocolError("OUTPUT scene_score must be finite")
        return OUTPUT_META.pack(
            self.width, self.height, self.timestamp,
            self.ngx_create_result, self.ngx_evaluate_result, self.cuda_result,
            self.scene_reset, float(self.scene_score),
            self.upload_bytes, self.download_bytes,
        ) + bytes(self.rgba)

    @classmethod
    def decode(cls, payload: bytes) -> "OutputEvidence":
        if len(payload) < OUTPUT_META.size:
            raise V10ProtocolError("OUTPUT payload is truncated")
        values = OUTPUT_META.unpack_from(payload)
        width, height = values[0], values[1]
        rgba = payload[OUTPUT_META.size:]
        result = cls(*values, rgba)
        expected = rgba_bytes(width, height)
        if len(rgba) != expected:
            raise V10ProtocolError(
                f"OUTPUT RGBA8 payload is {len(rgba)} bytes; expected {expected}"
            )
        if result.scene_reset not in (0, 1) or not math.isfinite(result.scene_score):
            raise V10ProtocolError("OUTPUT evidence fields are invalid")
        return result


def _bounded_float(name: str, raw: object, minimum: float, maximum: float) -> float:
    if isinstance(raw, bool):
        raise V10ProtocolError(f"{name} must be numeric")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise V10ProtocolError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise V10ProtocolError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _scale(raw: object) -> float:
    value = _bounded_float("processing_scale", raw, min(SUPPORTED_SCALES), max(SUPPORTED_SCALES))
    for supported in SUPPORTED_SCALES:
        if math.isclose(value, supported, rel_tol=0.0, abs_tol=1e-9):
            return supported
    raise V10ProtocolError(
        "processing_scale must be one of " + ", ".join(str(value) for value in SUPPORTED_SCALES)
    )


def _nearest_even(value: float) -> int:
    return max(2, int(math.floor(value / 2.0 + 0.5)) * 2)


def resolve_output_size(width: int, height: int, scale: float) -> tuple[int, int]:
    factor = _scale(scale)
    output_width = _nearest_even(int(width) * factor)
    output_height = _nearest_even(int(height) * factor)
    if min(output_width, output_height) < MIN_EDGE:
        raise V10ProtocolError(
            f"output {output_width}x{output_height} is below the {MIN_EDGE}x{MIN_EDGE} boundary"
        )
    long_edge = max(output_width, output_height)
    short_edge = min(output_width, output_height)
    if long_edge > MAX_LONG_EDGE or short_edge > MAX_SHORT_EDGE:
        raise V10ProtocolError(
            f"output {output_width}x{output_height} exceeds the supported 7680x4320 boundary"
        )
    return output_width, output_height


def rgba_bytes(width: int, height: int) -> int:
    if isinstance(width, bool) or isinstance(height, bool):
        raise V10ProtocolError("frame dimensions must be integers")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise V10ProtocolError("frame dimensions must be positive integers")
    size = width * height * 4
    if size > MAX_RGBA_BYTES:
        raise V10ProtocolError("RGBA8 frame exceeds protocol v1 safety limit")
    return size


class V10ProtocolError(RuntimeError):
    pass


class V10SessionPoisoned(V10ProtocolError):
    pass


@dataclass
class SessionGuard:
    created: bool = False
    closed: bool = False
    poisoned: bool = False
    poison_reason: str | None = None
    next_request_id: int = 1

    def _require_live(self) -> None:
        if self.closed:
            raise V10ProtocolError("v10 session is already closed")
        if self.poisoned:
            raise V10SessionPoisoned(
                f"v10 session is poisoned: {self.poison_reason or 'unknown reason'}"
            )

    def _consume(self, request_id: int) -> None:
        if request_id != self.next_request_id:
            raise V10ProtocolError(
                f"request_id {request_id} != expected {self.next_request_id}"
            )
        self.next_request_id += 1

    def accept_create(self, request_id: int) -> None:
        self._require_live()
        if self.created:
            raise V10ProtocolError("CREATE is only valid once per v10 host process")
        self._consume(request_id)
        self.created = True

    def accept_frame(self, request_id: int) -> None:
        self._require_live()
        if not self.created:
            raise V10ProtocolError("FRAME requires a successful CREATE first")
        self._consume(request_id)

    def accept_close(self, request_id: int) -> None:
        if self.closed:
            raise V10ProtocolError("v10 session is already closed")
        if request_id != self.next_request_id:
            raise V10ProtocolError(
                f"request_id {request_id} != expected {self.next_request_id}"
            )
        self.next_request_id += 1
        self.closed = True

    def poison(self, reason: str) -> None:
        if self.closed:
            return
        self.poisoned = True
        self.poison_reason = str(reason)[:1024] or "unspecified failure"


HOST_START_TIMEOUT_SECONDS = 15.0
FRAME_TIMEOUT_SECONDS = 30.0
CLOSE_GRACE_SECONDS = 1.0


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
