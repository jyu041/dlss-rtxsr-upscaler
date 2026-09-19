"""Parent-side supervisor for the DLSS5 v10 isolated host protocol.

Only the non-native protocol selftest server can be started at this milestone.
The native host start path remains fail-closed.
"""

from __future__ import annotations

import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time

from .dlss5_v10_adapter import V10ExecutionDisabled
EXPERIMENT_ACK = "BOUNDED_256_ONE_FRAME"
TEMPORAL_EXPERIMENT_ACK = "BOUNDED_256_THREE_FRAME"

from .dlss5_v10_protocol import (
    CLOSE,
    CREATE,
    ERROR,
    FRAME,
    HELLO,
    OUTPUT,
    CLOSE_GRACE_SECONDS,
    FRAME_TIMEOUT_SECONDS,
    HOST_START_TIMEOUT_SECONDS,
    CreateRequest,
    FrameRequest,
    OutputEvidence,
    V10ProtocolError,
    decode_json,
    encode_json,
    encode_message,
    read_message,
)


class V10ProtocolClient:
    def __init__(
        self,
        *,
        python: str | Path | None = None,
        start_timeout: float = HOST_START_TIMEOUT_SECONDS,
        frame_timeout: float = FRAME_TIMEOUT_SECONDS,
        close_grace: float = CLOSE_GRACE_SECONDS,
    ):
        self.python = str(Path(python or sys.executable).expanduser().resolve())
        self.start_timeout = float(start_timeout)
        self.frame_timeout = float(frame_timeout)
        self.close_grace = float(close_grace)
        self.process: subprocess.Popen | None = None
        self._messages: queue.Queue = queue.Queue()
        self._stderr: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._err_reader: threading.Thread | None = None
        self._next_request_id = 1
        self._create: CreateRequest | None = None
        self._poisoned = False
        self._poison_reason: str | None = None
        self._closed = False
        self._native_mode = False

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    @property
    def poison_reason(self) -> str | None:
        return self._poison_reason

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    def start(self) -> None:
        raise V10ExecutionDisabled(
            "Native DLSS5 v10 host start remains disabled; use an explicit bounded experimental entry point"
        )

    def _spawn(self, command: list[str], *, env: dict[str, str] | None = None) -> None:
        if self.process is not None:
            raise V10ProtocolError("v10 protocol client is already started")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        self._start_readers()

    def start_protocol_selftest(self) -> dict[str, object]:
        self._native_mode = False
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                "--protocol-selftest-server",
            ]
        )
        command, request_id, payload = self._wait(self.start_timeout)
        if command != HELLO or request_id != 0:
            self._poison(f"expected HELLO request 0, received command={command} request={request_id}")
            raise V10ProtocolError(self._poison_reason)
        value = decode_json(payload)
        if not isinstance(value, dict) or value.get("native_loaded") is not False:
            self._poison("invalid protocol selftest HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def start_native_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
    ) -> dict[str, object]:
        if acknowledgement != EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "bounded native v10 start requires the exact acknowledgement token"
            )
        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                "--experimental-native-serve",
                "--runtime-dir",
                str(Path(runtime_dir).expanduser().resolve()),
                "--preflight-report",
                str(Path(preflight_report).expanduser().resolve()),
            ],
            env=env,
        )
        command, request_id, payload = self._wait(self.start_timeout)
        if command != HELLO or request_id != 0:
            self._poison(
                f"expected HELLO request 0, received command={command} request={request_id}"
            )
            raise V10ProtocolError(self._poison_reason)
        value = decode_json(payload)
        if (
            not isinstance(value, dict)
            or value.get("native_loaded") is not False
            or value.get("experimental_native_mode") is not True
            or value.get("normal_backend_enabled") is not False
        ):
            self._poison("invalid bounded native HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def start_native_temporal_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
    ) -> dict[str, object]:
        if acknowledgement != TEMPORAL_EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "temporal native v10 start requires the exact acknowledgement token"
            )
        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = TEMPORAL_EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                "--experimental-native-temporal-serve",
                "--runtime-dir",
                str(Path(runtime_dir).expanduser().resolve()),
                "--preflight-report",
                str(Path(preflight_report).expanduser().resolve()),
            ],
            env=env,
        )
        command, request_id, payload = self._wait(self.start_timeout)
        if command != HELLO or request_id != 0:
            self._poison(
                f"expected HELLO request 0, received command={command} request={request_id}"
            )
            raise V10ProtocolError(self._poison_reason)
        value = decode_json(payload)
        if (
            not isinstance(value, dict)
            or value.get("native_loaded") is not False
            or value.get("experimental_native_mode") is not True
            or value.get("normal_backend_enabled") is not False
        ):
            self._poison("invalid bounded temporal native HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def _start_readers(self) -> None:
        assert self.process and self.process.stdout and self.process.stderr

        def read_stdout() -> None:
            try:
                while True:
                    self._messages.put(read_message(self.process.stdout))
            except Exception as exc:
                self._messages.put(exc)

        def read_stderr() -> None:
            try:
                for line in self.process.stderr:
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", errors="replace")
                    self._stderr.put(line.rstrip())
            except Exception:
                return

        self._reader = threading.Thread(target=read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=read_stderr, daemon=True)
        self._reader.start()
        self._err_reader.start()

    def _poison(self, reason: str) -> None:
        self._poisoned = True
        self._poison_reason = str(reason)[:1024] or "unspecified failure"

    def _require_live(self) -> None:
        if self._closed:
            raise V10ProtocolError("v10 protocol client is closed")
        if self._poisoned:
            raise V10ProtocolError(f"v10 protocol client is poisoned: {self._poison_reason}")
        if self.process is None or self.process.poll() is not None:
            raise V10ProtocolError("v10 protocol host is not running")

    def _wait(self, timeout: float) -> tuple[int, int, bytes]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._poison(f"v10 protocol host timed out after {timeout:.3f}s")
                self.abort()
                raise TimeoutError(self._poison_reason)
            try:
                message = self._messages.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if isinstance(message, Exception):
                self._poison(str(message))
                self.abort()
                raise V10ProtocolError(self._poison_reason) from message
            command, request_id, payload = message
            if command == ERROR:
                try:
                    detail = decode_json(payload)
                except V10ProtocolError:
                    detail = {"error": payload.decode("utf-8", errors="replace")}
                self._poison(str(detail.get("error", detail)) if isinstance(detail, dict) else str(detail))
                raise V10ProtocolError(f"v10 host error: {self._poison_reason}")
            return command, request_id, payload

    def _roundtrip(self, command: int, payload: bytes, timeout: float) -> tuple[int, bytes]:
        self._require_live()
        request_id = self._next_request_id
        assert self.process and self.process.stdin
        self.process.stdin.write(encode_message(command, request_id, payload))
        self.process.stdin.flush()
        response_command, response_id, response_payload = self._wait(timeout)
        if response_id != request_id:
            self._poison(
                f"response request_id {response_id} != expected {request_id}"
            )
            self.abort()
            raise V10ProtocolError(self._poison_reason)
        self._next_request_id += 1
        return response_command, response_payload

    def create(self, request: CreateRequest) -> dict[str, object]:
        if self._create is not None:
            raise V10ProtocolError("v10 protocol CREATE is only valid once")
        response_command, payload = self._roundtrip(
            CREATE,
            json.dumps(
                request.to_wire(), separators=(",", ":"), sort_keys=True
            ).encode("utf-8"),
            self.frame_timeout,
        )
        if response_command != CREATE:
            self._poison(f"expected CREATE response, received {response_command}")
            self.abort()
            raise V10ProtocolError(self._poison_reason)
        value = decode_json(payload)
        expected_native_loaded = bool(self._native_mode)
        if (
            not isinstance(value, dict)
            or value.get("native_loaded") is not expected_native_loaded
        ):
            self._poison("invalid CREATE acknowledgement")
            self.abort()
            raise V10ProtocolError(self._poison_reason)
        self._create = request
        return value

    def process_frame(self, frame: FrameRequest) -> OutputEvidence:
        if self._create is None:
            raise V10ProtocolError("FRAME requires CREATE")
        payload = frame.encode(self._create.input_width, self._create.input_height)
        response_command, response_payload = self._roundtrip(
            FRAME, payload, self.frame_timeout
        )
        if response_command != OUTPUT:
            self._poison(f"expected OUTPUT response, received {response_command}")
            self.abort()
            raise V10ProtocolError(self._poison_reason)
        return OutputEvidence.decode(response_payload)

    def close(self) -> str:
        if self._closed:
            return "ALREADY_CLOSED"
        if self.process is None:
            self._closed = True
            return "NOT_STARTED"

        if self.process.poll() is None and not self._poisoned:
            try:
                response_command, payload = self._roundtrip(
                    CLOSE, b"", self.frame_timeout
                )
                if response_command != CLOSE:
                    raise V10ProtocolError(
                        f"expected CLOSE response, received {response_command}"
                    )
                value = decode_json(payload)
                if not isinstance(value, dict):
                    raise V10ProtocolError("invalid CLOSE acknowledgement")
                if self._native_mode:
                    if value.get("ngx_shutdown_called") is not False or value.get("module_unload_called") is not False:
                        raise V10ProtocolError("native CLOSE violated process-lifetime NGX contract")
                elif value.get("native_loaded") is not False:
                    raise V10ProtocolError("invalid CLOSE acknowledgement")
                self.process.wait(timeout=self.close_grace)
                if self.process.returncode != 0:
                    raise V10ProtocolError(
                        f"v10 protocol host exited with {self.process.returncode}"
                    )
                result = "CLOSED"
            except (OSError, subprocess.TimeoutExpired, TimeoutError, V10ProtocolError):
                self.abort()
                result = "TERMINATED_AFTER_CLOSE_FAILURE"
        else:
            self.abort()
            result = "TERMINATED_POISONED"

        self._closed = True
        return result

    def abort(self) -> str:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return "TERMINATED_OWNED_HOST"
        return "NOT_RUNNING"

    def __enter__(self) -> "V10ProtocolClient":
        self.start_protocol_selftest()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
