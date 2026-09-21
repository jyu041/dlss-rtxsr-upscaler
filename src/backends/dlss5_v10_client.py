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
VIDEO_AB_EXPERIMENT_ACK = "BOUNDED_256_VIDEO_AB_16"
SCENE_CUT_EXPERIMENT_ACK = "BOUNDED_256_SCENE_CUT_32"
SCENE_SOAK_EXPERIMENT_ACK = "BOUNDED_256_SCENE_AWARE_128"
APP_EXPERIMENT_ACK = "EXPERIMENTAL_APP_SCENE_AWARE_V10"

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
        self._last_close_error: str | None = None

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    @property
    def poison_reason(self) -> str | None:
        return self._poison_reason

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    @property
    def last_close_error(self) -> str | None:
        return self._last_close_error

    def _stderr_tail(self, limit: int = 20) -> str:
        lines: list[str] = []
        while len(lines) < limit:
            try:
                lines.append(str(self._stderr.get_nowait()))
            except queue.Empty:
                break
        return "\n".join(lines[-limit:]).strip()

    def start(self) -> None:
        raise V10ExecutionDisabled(
            "Native DLSS5 v10 host start remains disabled; use an explicit bounded research or experimental application entry point"
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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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

    def start_native_video_ab_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
        mode: str,
    ) -> dict[str, object]:
        if acknowledgement != VIDEO_AB_EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "real-video v10 A/B start requires the exact acknowledgement token"
            )
        routes = {
            "persistent": "--experimental-native-video-persistent-serve",
            "reset-control": "--experimental-native-video-reset-serve",
        }
        route = routes.get(mode)
        if route is None:
            raise ValueError("v10 real-video A/B mode must be persistent or reset-control")

        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = VIDEO_AB_EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                route,
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
            or value.get("video_ab_mode") != mode
        ):
            self._poison("invalid bounded real-video A/B native HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def start_native_scene_cut_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
        mode: str,
    ) -> dict[str, object]:
        if acknowledgement != SCENE_CUT_EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "scene-cut v10 start requires the exact acknowledgement token"
            )
        routes = {
            "no-cut-reset": "--experimental-native-scene-no-reset-serve",
            "scene-aware": "--experimental-native-scene-aware-serve",
            "reset-control": "--experimental-native-scene-reset-serve",
        }
        route = routes.get(mode)
        if route is None:
            raise ValueError(
                "v10 scene-cut mode must be no-cut-reset, scene-aware, or reset-control"
            )
        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = SCENE_CUT_EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                route,
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
            or value.get("scene_cut_mode") != mode
        ):
            self._poison("invalid bounded scene-cut native HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def start_native_scene_soak_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
        mode: str,
    ) -> dict[str, object]:
        if acknowledgement != SCENE_SOAK_EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "scene-aware soak v10 start requires the exact acknowledgement token"
            )
        routes = {
            "scene-aware": (
                "--experimental-native-scene-soak-serve",
                "scene-aware-soak",
            ),
            "reset-control": (
                "--experimental-native-scene-soak-reset-serve",
                "reset-control-soak",
            ),
        }
        selected = routes.get(mode)
        if selected is None:
            raise ValueError(
                "v10 scene-aware soak mode must be scene-aware or reset-control"
            )
        route, hello_mode = selected
        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = SCENE_SOAK_EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                route,
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
            or value.get("scene_cut_mode") != hello_mode
        ):
            self._poison("invalid bounded scene-aware soak native HELLO")
            raise V10ProtocolError(self._poison_reason)
        return value

    def start_native_application_experimental(
        self,
        runtime_dir: str | Path,
        preflight_report: str | Path,
        *,
        acknowledgement: str,
    ) -> dict[str, object]:
        if acknowledgement != APP_EXPERIMENT_ACK:
            raise V10ExecutionDisabled(
                "experimental application v10 start requires the exact acknowledgement token"
            )
        self._native_mode = True
        env = dict(os.environ)
        env["NVE_DLSS5_V10_NATIVE"] = APP_EXPERIMENT_ACK
        self._spawn(
            [
                self.python,
                "-u",
                "-m",
                "src.backends.dlss5_v10_host",
                "--experimental-native-app-serve",
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
        contract = value.get("application_contract") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("native_loaded") is not False
            or value.get("experimental_native_mode") is not True
            or value.get("experimental_application_mode") is not True
            or value.get("normal_backend_enabled") is not False
            or not isinstance(contract, dict)
            or contract.get("processing_scales") != [1.0]
        ):
            self._poison("invalid experimental application v10 HELLO")
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
                    session_close = str(value.get("session_close") or "")
                    allowed_native_close = {
                        "CLOSED_RELEASED",
                        "CLOSED_NO_RELEASE_EXPORT",
                        "CLOSED_WITHOUT_NATIVE_SESSION",
                        "CLOSED_PROCESS_LIFETIME",
                    }
                    if session_close not in allowed_native_close:
                        raise V10ProtocolError(
                            f"native session close was not clean: {session_close or 'missing status'}"
                        )
                elif value.get("native_loaded") is not False:
                    raise V10ProtocolError("invalid CLOSE acknowledgement")

                if self._native_mode and session_close == "CLOSED_PROCESS_LIFETIME":
                    # The application host has completed its logical protocol
                    # close. Deliberately do not enter Python/DLL teardown with
                    # live process-lifetime NGX state: the isolated OS process
                    # is the teardown boundary.
                    if self.process.poll() is None:
                        self.process.kill()
                        self.process.wait(timeout=5)
                    result = "CLOSED_PROCESS_LIFETIME"
                else:
                    try:
                        self.process.wait(timeout=self.close_grace)
                    except subprocess.TimeoutExpired:
                        if not self._native_mode:
                            raise
                        # Research-native sessions that did perform their
                        # logical release still use supervised termination if
                        # interpreter/DLL teardown stalls afterward.
                        self.process.kill()
                        self.process.wait(timeout=5)
                        result = "CLOSED_ACK_TERMINATED"
                    else:
                        if self.process.returncode != 0:
                            raise V10ProtocolError(
                                f"v10 protocol host exited with {self.process.returncode}"
                            )
                        result = "CLOSED"
            except (OSError, subprocess.TimeoutExpired, TimeoutError, V10ProtocolError) as exc:
                detail = str(exc).strip() or type(exc).__name__
                stderr_tail = self._stderr_tail()
                if stderr_tail:
                    detail = f"{detail}; host stderr: {stderr_tail}"
                self._last_close_error = detail
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
