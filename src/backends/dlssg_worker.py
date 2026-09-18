"""Binary client for the persistent offline Ampere DLSS-G worker.

The native executable and NVIDIA/community runtimes are external build/runtime
dependencies. This module never downloads or redistributes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import hashlib
import math
import os
from pathlib import Path
import struct
import subprocess
import threading
import time
import warnings
from typing import BinaryIO, Callable

MAGIC = 0x47534C44
PROTOCOL_VERSION = 4
WORKER_VERSION = 4
KNOWN_COMMUNITY_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"

COMMAND_HELLO = 1
COMMAND_CREATE = 2
COMMAND_PROCESS = 3
COMMAND_RESET_HISTORY = 4
COMMAND_CLOSE = 5

STATUS_OK = 0
STATUS_OK_RESET_NO_OUTPUT = 1

PIXEL_FORMAT_RGBA8_UNORM = 28
DEPTH_MODE_CONSTANT_0_5 = 1
MOTION_MODE_EXTERNAL_R16G16_FLOAT = 1
MOTION_MODE_NVIDIA_OPTICAL_FLOW = 2
PROCESS_FLAG_RESET = 1

REQUEST_HEADER = struct.Struct("<IHHII")
RESPONSE_HEADER = struct.Struct("<IHHIiI")
HELLO_RESPONSE = struct.Struct("<IIII")
CREATE_REQUEST = struct.Struct("<IIIIII")
CREATE_RESPONSE = struct.Struct("<IIII")
PROCESS_REQUEST = struct.Struct("<QIIII")
PROCESS_RESPONSE = struct.Struct("<IIIIII" + "d" * 17)


def mfg_group_indices(multiplier: int) -> tuple[int, ...]:
    """Return the complete DLSS-G generated-index sequence for one group.

    DLSS-G numbers intermediate frames from one through the requested
    multiplier minus one.  Reset and normal groups use the same sequence;
    reset only changes the per-evaluation reset flag and never short-circuits
    the group.
    """
    if multiplier not in (2, 3, 4):
        raise ValueError("multiplier must be 2, 3, or 4")
    return tuple(range(1, multiplier))


def mfg_group_complete(multiplier: int, completed_indices: tuple[int, ...]) -> bool:
    """Return whether all generated indices completed exactly once."""
    return completed_indices == mfg_group_indices(multiplier)


class DlssgWorkerError(RuntimeError):
    """Base error for native worker failures."""


class DlssgWorkerProtocolError(DlssgWorkerError):
    """The worker returned malformed or incompatible protocol data."""


class DlssgWorkerProcessError(DlssgWorkerError):
    """The worker exited or broke its pipe unexpectedly."""


class DlssgNativeError(DlssgWorkerError):
    """The native worker returned a non-success status."""

    def __init__(self, status: int, command: int, diagnostics: str = ""):
        detail = f"native DLSS-G command {command} failed with status {status}"
        if diagnostics:
            detail += f": {diagnostics}"
        super().__init__(detail)
        self.status = status
        self.command = command


@dataclass(frozen=True)
class ProcessResult:
    frame_id: int
    generated_count: int
    disable_interpolation: int
    width: int
    height: int
    pixel_format: int
    outputs: tuple[bytes, ...]
    upload_ms: float
    evaluate_cpu_ms: float
    gpu_wait_ms: float
    readback_ms: float
    total_process_ms: float
    nvof_upload_ms: float
    nvof_execute_ms: float
    flow_conversion_ms: float
    flow_mean_x: float
    flow_mean_y: float
    flow_median_x: float
    flow_median_y: float
    flow_p95_magnitude: float
    flow_maximum_magnitude: float
    flow_standard_deviation_magnitude: float
    flow_near_zero_percent: float
    flow_unusually_large_percent: float
    reset_only: bool

    @property
    def output(self) -> bytes:
        """Compatibility accessor for the first generated frame in a group."""
        return self.outputs[0] if self.outputs else b""

    @property
    def sha256(self) -> str | None:
        return hashlib.sha256(self.output).hexdigest().upper() if self.output else None


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    if size < 0:
        raise ValueError("negative read size")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise DlssgWorkerProcessError(f"worker pipe closed with {remaining} bytes still expected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_all(stream: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = stream.write(view[written:])
        if count is None:
            count = 0
        if count <= 0:
            raise DlssgWorkerProcessError("worker input pipe stopped accepting data")
        written += count
    stream.flush()


def _write_parts(stream: BinaryIO, parts: tuple[bytes | bytearray | memoryview, ...]) -> None:
    """Write protocol segments in order without materializing their concatenation."""
    for part in parts:
        view = memoryview(part)
        written = 0
        while written < len(view):
            count = stream.write(view[written:])
            if count is None:
                count = 0
            if count <= 0:
                raise DlssgWorkerProcessError("worker input pipe stopped accepting data")
            written += count
    stream.flush()


def _decode_response_header(data: bytes, expected_command: int, expected_request_id: int) -> tuple[int, int]:
    magic, version, command, request_id, status, payload_bytes = RESPONSE_HEADER.unpack(data)
    if magic != MAGIC:
        raise DlssgWorkerProtocolError(f"invalid response magic 0x{magic:08X}")
    if version != PROTOCOL_VERSION:
        raise DlssgWorkerProtocolError(f"protocol version {version} != {PROTOCOL_VERSION}")
    if command != expected_command or request_id != expected_request_id:
        raise DlssgWorkerProtocolError(
            f"response correlation mismatch command={command} request={request_id}"
        )
    return status, payload_bytes


def validate_motion_vectors(data: bytes, width: int, height: int) -> None:
    expected = width * height * 4
    if len(data) != expected:
        raise ValueError(f"motion vector payload is {len(data)} bytes; expected {expected}")
    for x, y in struct.iter_unpack("<ee", data):
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("motion vectors must contain finite R16G16_FLOAT values")


class DlssgWorker:
    """Own one persistent native process and one reusable DLSS-G feature."""

    def __init__(
        self,
        executable: str | Path,
        community_runtime: str | Path,
        official_runtime_dir: str | Path,
        *,
        expected_community_sha256: str | None = KNOWN_COMMUNITY_SHA256,
        strict_runtime_hash: bool = False,
        diagnostic_callback: Callable[[str], None] | None = None,
        diagnostic_mode: bool = False,
    ):
        self.executable = Path(executable)
        self.community_runtime = Path(community_runtime)
        self.official_runtime_dir = Path(official_runtime_dir)
        self.expected_community_sha256 = expected_community_sha256.upper() if expected_community_sha256 else None
        self.strict_runtime_hash = strict_runtime_hash
        self.diagnostic_callback = diagnostic_callback
        self.diagnostic_mode = diagnostic_mode
        self._process: subprocess.Popen[bytes] | None = None
        self.last_exit_code: int | None = None
        self._request_id = 0
        self._diagnostics: deque[str] = deque(maxlen=2048)
        self.last_exchange_metrics: dict[str, float | int] = {}
        self._stderr_thread: threading.Thread | None = None
        self.width: int | None = None
        self.height: int | None = None
        self.motion_mode: int | None = None
        self.multiplier: int | None = None

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return tuple(self._diagnostics)

    def _validate_paths(self) -> None:
        for label, path, directory in (
            ("worker executable", self.executable, False),
            ("community runtime", self.community_runtime, False),
            ("official runtime directory", self.official_runtime_dir, True),
        ):
            if not path.is_absolute():
                raise ValueError(f"{label} must be an absolute path: {path}")
            if directory and not path.is_dir():
                raise FileNotFoundError(f"{label} not found: {path}")
            if not directory and not path.is_file():
                raise FileNotFoundError(f"{label} not found: {path}")
        digest = hashlib.sha256(self.community_runtime.read_bytes()).hexdigest().upper()
        if self.expected_community_sha256 and digest != self.expected_community_sha256:
            message = (
                f"community runtime SHA-256 {digest} does not match known identity "
                f"{self.expected_community_sha256}; a hash is provenance, not a safety guarantee"
            )
            if self.strict_runtime_hash:
                raise ValueError(message)
            warnings.warn(message, RuntimeWarning, stacklevel=2)

    def start(self) -> None:
        if self._process is not None:
            raise DlssgWorkerError("worker already started")
        self._validate_paths()
        command = [
            str(self.executable),
            "--serve",
            "--community-runtime",
            str(self.community_runtime),
            "--official-runtime-dir",
            str(self.official_runtime_dir),
        ]
        environment = os.environ.copy()
        if self.diagnostic_mode:
            environment["DLSSG_WORKER_DIAGNOSTIC"] = "1"
        else:
            environment.pop("DLSSG_WORKER_DIAGNOSTIC", None)
        # Forward-only NVOF produces the same current-to-previous field as
        # BOTH on the validated Ampere path, while avoiding the unused reverse
        # output.  Keep BOTH available for explicit diagnostic/fallback runs.
        environment.setdefault("DLSSG_NVOF_DIRECTION", "both" if self.diagnostic_mode else "forward")
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=environment,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        payload = self._exchange(COMMAND_HELLO)
        if len(payload) != HELLO_RESPONSE.size:
            raise DlssgWorkerProtocolError("invalid HELLO response size")
        worker_version, protocol_version, _capabilities, _reserved = HELLO_RESPONSE.unpack(payload)
        if worker_version != WORKER_VERSION or protocol_version != PROTOCOL_VERSION:
            raise DlssgWorkerProtocolError("incompatible worker version")

    def _drain_stderr(self) -> None:
        process = self._process
        if not process or not process.stderr:
            return
        for raw in iter(process.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            self._diagnostics.append(line)
            if self.diagnostic_callback:
                self.diagnostic_callback(line)

    def _require_process(self) -> subprocess.Popen[bytes]:
        process = self._process
        if not process or not process.stdin or not process.stdout:
            raise DlssgWorkerProcessError("worker is not running")
        if process.poll() is not None:
            tail = " | ".join(list(self._diagnostics)[-5:])
            raise DlssgWorkerProcessError(f"worker exited with code {process.returncode}: {tail}")
        return process

    def _exchange(self, command: int, payload: bytes = b"", allowed_statuses: tuple[int, ...] = (STATUS_OK,)) -> bytes:
        process = self._require_process()
        self._request_id += 1
        request_id = self._request_id
        header = REQUEST_HEADER.pack(MAGIC, PROTOCOL_VERSION, command, request_id, len(payload))
        write_start = time.perf_counter()
        _write_all(process.stdin, header + payload)
        write_seconds = time.perf_counter() - write_start
        header_start = time.perf_counter()
        response_header = _read_exact(process.stdout, RESPONSE_HEADER.size)
        header_seconds = time.perf_counter() - header_start
        status, payload_bytes = _decode_response_header(response_header, command, request_id)
        payload_start = time.perf_counter()
        response_payload = _read_exact(process.stdout, payload_bytes)
        payload_seconds = time.perf_counter() - payload_start
        self.last_exchange_metrics = {
            "request_write_ms": write_seconds * 1000.0,
            "response_header_read_ms": header_seconds * 1000.0,
            "response_payload_read_ms": payload_seconds * 1000.0,
            "request_payload_bytes": len(payload),
            "response_payload_bytes": payload_bytes,
        }
        if status not in allowed_statuses:
            tail = " | ".join(list(self._diagnostics)[-5:])
            raise DlssgNativeError(status, command, tail)
        return response_payload

    def _exchange_process(self, frame_id: int, fixed: bytes, color: bytes,
                          motion: bytes, allowed_statuses: tuple[int, ...]) -> tuple[tuple, tuple[bytes, ...]]:
        process = self._require_process()
        self._request_id += 1
        request_id = self._request_id
        payload_bytes = len(fixed) + len(color) + len(motion)
        header = REQUEST_HEADER.pack(MAGIC, PROTOCOL_VERSION, COMMAND_PROCESS, request_id, payload_bytes)
        write_start = time.perf_counter()
        _write_parts(process.stdin, (header, fixed, color, motion))
        write_seconds = time.perf_counter() - write_start
        header_start = time.perf_counter()
        response_header = _read_exact(process.stdout, RESPONSE_HEADER.size)
        header_seconds = time.perf_counter() - header_start
        status, response_bytes = _decode_response_header(response_header, COMMAND_PROCESS, request_id)
        if status not in allowed_statuses:
            tail = " | ".join(list(self._diagnostics)[-5:])
            raise DlssgNativeError(status, COMMAND_PROCESS, tail)
        if response_bytes < PROCESS_RESPONSE.size:
            raise DlssgWorkerProtocolError("short PROCESS response")
        payload_start = time.perf_counter()
        metadata = _read_exact(process.stdout, PROCESS_RESPONSE.size)
        values = PROCESS_RESPONSE.unpack(metadata)
        generated_count, disable, width, height, pixel_format, output_bytes, *timings = values
        expected_frame_bytes = width * height * 4
        if response_bytes != PROCESS_RESPONSE.size + output_bytes:
            raise DlssgWorkerProtocolError("PROCESS payload size does not match output_bytes")
        if generated_count == 0:
            if output_bytes:
                raise DlssgWorkerProtocolError("reset PROCESS response unexpectedly contains output")
            outputs: tuple[bytes, ...] = ()
        else:
            if generated_count not in (1, 2, 3) or output_bytes != generated_count * expected_frame_bytes:
                raise DlssgWorkerProtocolError("invalid generated-frame count or payload size")
            outputs = tuple(_read_exact(process.stdout, expected_frame_bytes) for _ in range(generated_count))
        payload_seconds = time.perf_counter() - payload_start
        self.last_exchange_metrics = {
            "request_write_ms": write_seconds * 1000.0,
            "response_header_read_ms": header_seconds * 1000.0,
            "response_payload_read_ms": payload_seconds * 1000.0,
            "request_payload_bytes": payload_bytes,
            "response_payload_bytes": response_bytes,
            "response_metadata_bytes": PROCESS_RESPONSE.size,
            "response_generated_bytes": output_bytes,
        }
        return (generated_count, disable, width, height, pixel_format, output_bytes, *timings), outputs

    def create(
        self,
        width: int = 256,
        height: int = 256,
        *,
        multiplier: int = 2,
        motion_mode: int = MOTION_MODE_EXTERNAL_R16G16_FLOAT,
    ) -> dict[str, int]:
        if multiplier not in (2, 3, 4):
            raise ValueError("multiplier must be 2, 3, or 4")
        request = CREATE_REQUEST.pack(
            width,
            height,
            PIXEL_FORMAT_RGBA8_UNORM,
            multiplier - 1,
            DEPTH_MODE_CONSTANT_0_5,
            motion_mode,
        )
        payload = self._exchange(COMMAND_CREATE, request)
        if len(payload) != CREATE_RESPONSE.size:
            raise DlssgWorkerProtocolError("invalid CREATE response size")
        worker, protocol, maximum, depth_mode = CREATE_RESPONSE.unpack(payload)
        self.width, self.height, self.motion_mode, self.multiplier = width, height, motion_mode, multiplier
        return {
            "worker_version": worker,
            "protocol_version": protocol,
            "maximum_generated_frames": maximum,
            "depth_mode": depth_mode,
        }

    def process(
        self,
        frame_id: int,
        color_rgba8: bytes,
        motion_r16g16_float: bytes | None = None,
        *,
        reset: bool = False,
    ) -> ProcessResult:
        if self.width is None or self.height is None:
            raise DlssgWorkerError("CREATE must succeed before PROCESS")
        color = bytes(color_rgba8)
        if self.motion_mode == MOTION_MODE_NVIDIA_OPTICAL_FLOW:
            if motion_r16g16_float not in (None, b""):
                raise ValueError("internal NVIDIA Optical Flow mode does not accept caller motion vectors")
            motion = b""
        else:
            if motion_r16g16_float is None:
                raise ValueError("external motion-vector mode requires R16G16_FLOAT data")
            motion = bytes(motion_r16g16_float)
        expected = self.width * self.height * 4
        if len(color) != expected:
            raise ValueError(f"color payload is {len(color)} bytes; expected {expected}")
        if self.motion_mode == MOTION_MODE_EXTERNAL_R16G16_FLOAT:
            validate_motion_vectors(motion, self.width, self.height)
        fixed = PROCESS_REQUEST.pack(
            frame_id,
            PROCESS_FLAG_RESET if reset else 0,
            len(color),
            len(motion),
            0,
        )
        values, outputs = self._exchange_process(
            frame_id, fixed, color, motion, (STATUS_OK, STATUS_OK_RESET_NO_OUTPUT)
        )
        generated_count, disable, width, height, pixel_format, output_bytes, *timings = values
        return ProcessResult(
            frame_id, generated_count, disable, width, height, pixel_format, outputs, *timings,
            reset_only=generated_count == 0,
        )

    def reset_history(self) -> None:
        self._exchange(COMMAND_RESET_HISTORY)

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                self._exchange(COMMAND_CLOSE)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        finally:
            self.last_exit_code = process.poll()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
            self._process = None

    def __enter__(self) -> "DlssgWorker":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
