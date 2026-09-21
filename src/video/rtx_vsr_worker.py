"""Supervised child-process transport for the NVIDIA VFX VideoSuperRes API."""
from __future__ import annotations

import json
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

MAGIC = b"RVSR"
HEADER = struct.Struct("<4sBIIII")
HELLO, CREATE, FRAME, DONE, OUTPUT, ERROR = range(6)
MAX_PAYLOAD = 64 * 1024 * 1024
FRAME_TIMEOUT = 30.0
TEARDOWN_GRACE = 1.0


def _native_output_layout(shape, width: int, height: int) -> tuple[str, int, bool]:
    """Describe a native VSR tensor layout without assuming channels-first.

    Standard VSR currently arrives as CHW through the Python binding, while
    same-resolution filter modes may expose an HWC-shaped DLPack view. Treat
    the returned tensor shape as authoritative so denoise/deblur bytes are
    serialized in real RGB pixel order instead of being reinterpreted as CHW.
    """
    dims = tuple(int(value) for value in shape)
    batched = False
    if len(dims) == 4 and dims[0] == 1:
        dims = dims[1:]
        batched = True
    if len(dims) != 3:
        raise RuntimeError(f"RTX VSR returned unsupported tensor shape {tuple(shape)}")
    if dims[0] in (3, 4) and dims[1:] == (int(height), int(width)):
        return "CHW", dims[0], batched
    if dims[:2] == (int(height), int(width)) and dims[2] in (3, 4):
        return "HWC", dims[2], batched
    raise RuntimeError(
        f"RTX VSR returned tensor shape {tuple(shape)} for expected "
        f"{width}x{height} RGB output"
    )


def _read_message(stream):
    header = stream.read(HEADER.size)
    if len(header) != HEADER.size:
        raise EOFError("RTX VSR worker ended before a complete response")
    magic, kind, index, width, height, size = HEADER.unpack(header)
    if magic != MAGIC or size > MAX_PAYLOAD:
        raise RuntimeError("Invalid RTX VSR worker response header")
    payload = stream.read(size)
    if len(payload) != size:
        raise EOFError("RTX VSR worker returned a truncated payload")
    return kind, index, width, height, payload


def _write_message(stream, kind, index=0, width=0, height=0, payload=b""):
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("RTX VSR worker payload exceeds safety limit")
    stream.write(HEADER.pack(MAGIC, kind, index, width, height, len(payload)))
    stream.write(payload)
    stream.flush()


def worker_main():
    """Child entry point. Native teardown is intentionally outside the protocol."""
    import torch
    import nvvfx

    effect = None
    shape = None
    output_shape = None
    print("HEARTBEAT imported", file=sys.stderr, flush=True)
    _write_message(sys.stdout.buffer, HELLO, payload=json.dumps({"protocol": 1, "qualities": [x.name for x in nvvfx.VideoSuperRes.QualityLevel]}).encode())
    try:
        while True:
            kind, index, width, height, payload = _read_message(sys.stdin.buffer)
            if kind == CREATE:
                options = json.loads(payload.decode("utf-8"))
                prefix = {"Super Resolution": "", "High Bitrate": "HIGHBITRATE_", "Deblur": "DEBLUR_", "Denoise": "DENOISE_"}.get(options["mode"])
                if prefix is None:
                    raise ValueError("Unsupported RTX VSR mode")
                quality = prefix + options["quality"]
                effect = nvvfx.VideoSuperRes(getattr(nvvfx.VideoSuperRes.QualityLevel, quality), device=0)
                effect.output_width, effect.output_height = int(options["output_width"]), int(options["output_height"])
                print("HEARTBEAT before_load", file=sys.stderr, flush=True)
                effect.load()
                shape = (int(options["input_width"]), int(options["input_height"]))
                output_shape = (int(options["output_width"]), int(options["output_height"]))
                print("HEARTBEAT loaded", file=sys.stderr, flush=True)
                continue
            if kind == FRAME:
                if effect is None or shape is None or len(payload) != shape[0] * shape[1] * 3:
                    raise RuntimeError("RTX VSR worker received an invalid frame")
                frame = np.frombuffer(payload, dtype=np.uint8).reshape(shape[1], shape[0], 3).copy()
                tensor = torch.from_numpy(frame).to("cuda", dtype=torch.float32).div_(255).permute(2, 0, 1).contiguous()
                native = effect.run(tensor)
                owned = torch.from_dlpack(native.image).clone()
                layout, channels, batched = _native_output_layout(
                    owned.shape, output_shape[0], output_shape[1]
                )
                image = owned[0] if batched else owned
                if layout == "CHW":
                    image = image[:3].permute(1, 2, 0)
                else:
                    image = image[..., :3]
                output = (
                    image.contiguous()
                    .clamp(0, 1)
                    .mul(255)
                    .byte()
                    .cpu()
                    .numpy()
                    .tobytes()
                )
                del native, owned, image, tensor, frame
                _write_message(sys.stdout.buffer, OUTPUT, index=index, width=output_shape[0], height=output_shape[1], payload=output)
                print(f"HEARTBEAT frame={index}", file=sys.stderr, flush=True)
                continue
            if kind == DONE:
                # Send DONE before the known vendor teardown path. The parent
                # owns termination after its short grace period.
                _write_message(sys.stdout.buffer, DONE)
                print("HEARTBEAT done", file=sys.stderr, flush=True)
                if effect is not None:
                    effect.close()
                return 0
            raise RuntimeError(f"Unknown RTX VSR worker command: {kind}")
    except Exception as exc:
        try:
            _write_message(sys.stdout.buffer, ERROR, payload=str(exc).encode("utf-8", errors="replace"))
        except Exception:
            pass
        print(f"ERROR {exc}", file=sys.stderr, flush=True)
        return 2


class RTXVSRSession:
    """Parent-side supervisor for one persistent RTX VSR job."""

    def __init__(self, timeout=FRAME_TIMEOUT, heartbeat=None, python=None):
        self.timeout = float(timeout)
        self.heartbeat = heartbeat
        self.python = python or sys.executable
        self.process = None
        self._messages = __import__("queue").Queue()
        self._stderr = __import__("queue").Queue()
        self._reader = None
        self._err_reader = None
        self._expected_index = 0
        self._done = False
        self.expected_output = None

    @property
    def pid(self):
        return self.process.pid if self.process else None

    def _start_reader(self):
        def read_stdout():
            try:
                while True:
                    self._messages.put(_read_message(self.process.stdout))
            except Exception as exc:
                self._messages.put(exc)
        def read_stderr():
            for line in self.process.stderr:
                self._stderr.put(line.decode("utf-8", errors="replace").rstrip() if isinstance(line, bytes) else line.rstrip())
        self._reader = threading.Thread(target=read_stdout, daemon=True)
        self._err_reader = threading.Thread(target=read_stderr, daemon=True)
        self._reader.start(); self._err_reader.start()

    def _wait(self):
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"RTX VSR worker timed out after {self.timeout:.1f}s")
            try:
                message = self._messages.get(timeout=min(.25, remaining))
            except __import__("queue").Empty:
                continue
            while True:
                try:
                    line = self._stderr.get_nowait()
                except __import__("queue").Empty:
                    break
                if self.heartbeat:
                    self.heartbeat(line)
            if isinstance(message, Exception):
                raise message
            return message

    def start(self, input_width, input_height, output_width, output_height, mode, quality):
        self.expected_output = (int(output_width), int(output_height))
        self.process = subprocess.Popen([self.python, "-u", "-m", "src.video.rtx_vsr_worker", "--worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self._start_reader()
        kind, _, _, _, payload = self._wait()
        if kind != HELLO:
            raise RuntimeError("RTX VSR worker did not send HELLO")
        options = {"input_width": input_width, "input_height": input_height, "output_width": output_width, "output_height": output_height, "mode": mode, "quality": quality}
        _write_message(self.process.stdin, CREATE, payload=json.dumps(options).encode())

    def process_frame(self, index, frame):
        if index != self._expected_index:
            raise ValueError(f"RTX VSR frame index {index} does not match expected {self._expected_index}")
        _write_message(self.process.stdin, FRAME, index=index, width=frame.shape[1], height=frame.shape[0], payload=frame.tobytes())
        kind, returned, width, height, payload = self._wait()
        if kind == ERROR:
            raise RuntimeError(payload.decode("utf-8", errors="replace"))
        expected_width, expected_height = self.expected_output or (0, 0)
        if (kind != OUTPUT or returned != index or width != expected_width or height != expected_height
                or len(payload) != expected_width * expected_height * 3):
            raise RuntimeError("Invalid or mismatched RTX VSR worker output")
        self._expected_index += 1
        return np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3).copy()

    def finish(self):
        if not self.process or self._done:
            return "NOT_STARTED"
        _write_message(self.process.stdin, DONE)
        kind, _, _, _, payload = self._wait()
        if kind != DONE:
            raise RuntimeError(payload.decode("utf-8", errors="replace") if kind == ERROR else "RTX VSR worker did not finish")
        self._done = True
        try:
            self.process.wait(timeout=TEARDOWN_GRACE)
            if self.process.returncode == 0:
                return "EXITED_AFTER_DONE"
            raise RuntimeError(f"UNEXPECTED_WORKER_FAILURE_AFTER_DONE: exit code {self.process.returncode}")
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            return "EXPECTED_TEARDOWN_TIMEOUT_AFTER_DONE"

    def abort(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
            return "TERMINATED_OWNED_HELPER"
        return "NOT_RUNNING"

    def close(self):
        if self._done:
            return
        self.abort()


if __name__ == "__main__" and "--worker" in sys.argv:
    raise SystemExit(worker_main())
