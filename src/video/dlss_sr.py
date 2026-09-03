"""Temporal video pipeline for the separate native D3D12 DLSS SR host."""

from __future__ import annotations

import hashlib
import queue
import struct
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from src.core.media_info import frame_total, probe
from src.core.progress import report_progress

INPUT_MAGIC = 0x31524644
INPUT_HEADER = struct.Struct("<7I")
OUTPUT_HEADER = struct.Struct("<6I")
MAX_FRAME_BYTES = 7680 * 4320 * 4
MODES = {
    "DLAA": 1.0,
    "Quality": 1.5,
    "Balanced": 1.724,
    "Performance": 2.0,
    "Ultra Performance": 3.0,
}
PRESETS = {"Default": 0, "J": 10, "K": 11, "L": 12, "M": 13}


def _target(width: int, height: int, mode: str) -> tuple[int, int]:
    if mode not in MODES:
        raise ValueError(f"Unsupported DLSS SR mode: {mode}")
    if mode == "DLAA":
        return width, height
    scale = MODES[mode]
    return max(8, round(width * scale)), max(8, round(height * scale))


def _client_root() -> None:
    root = Path(__file__).resolve().parents[2] / "third_party" / "ComfyUI-DLSS5-Enhancer"
    if str(root) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(root))


def _motion_guide(width: int, height: int):
    _client_root()
    from dlss5.motion import TemporalGuide

    return TemporalGuide(width, height, flow_width=min(640, width), enabled=True)


def _read_response(stream, expected_bytes: int) -> tuple[tuple[int, ...], bytes]:
    header = stream.read(OUTPUT_HEADER.size)
    if len(header) != OUTPUT_HEADER.size:
        raise RuntimeError("DLSS SR host closed its output stream")
    values = OUTPUT_HEADER.unpack(header)
    magic, _, _, _, status, payload_size = values
    if magic != INPUT_MAGIC or status or payload_size != expected_bytes or payload_size > MAX_FRAME_BYTES:
        raise RuntimeError(f"Invalid DLSS SR host response: {values}")
    payload = stream.read(payload_size)
    if len(payload) != payload_size:
        raise RuntimeError("DLSS SR host returned a truncated frame")
    return values, payload


def process_dlss_sr_frame(frame, backend, mode="Quality", preset="K"):
    """Process one isolated RGBA frame with reset history and zero motion."""
    frame = np.asarray(frame, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise ValueError("DLSS SR frames must be HWC RGB or RGBA arrays")
    if frame.shape[2] == 3:
        frame = np.concatenate((frame, np.full((*frame.shape[:2], 1), 255, dtype=np.uint8)), axis=2)
    height, width = frame.shape[:2]
    output_width, output_height = _target(width, height, mode)
    motion = np.zeros((height, width, 2), dtype=np.float32).tobytes()
    command = [str(backend.host), "stream", str(width), str(height), str(output_width), str(output_height),
               mode.lower().replace(" ", ""), preset]
    packet = INPUT_HEADER.pack(INPUT_MAGIC, 0, width, height, 1, frame.nbytes, len(motion)) + frame.tobytes() + motion
    completed = subprocess.run(command, input=packet, capture_output=True, timeout=120)
    if completed.returncode:
        raise RuntimeError(f"DLSS SR frame host failed: {completed.stderr.decode(errors='replace')[-2000:]}")
    values, payload = _read_response(__import__("io").BytesIO(completed.stdout), output_width * output_height * 4)
    if values[1] != 0:
        raise RuntimeError("DLSS SR frame response number mismatch")
    return np.frombuffer(payload, dtype=np.uint8).reshape(output_height, output_width, 4).copy()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def render_dlss_sr(source, destination, backend, mode="Quality", preset="K", *, start=0.0, duration=None,
                   codec="H.264", cancel=None, progress=None):
    if mode == "Ultra Quality":
        raise ValueError("Ultra Quality is not supported by the validated DLSS SR runtime")
    if preset not in PRESETS:
        raise ValueError(f"Unsupported DLSS SR preset: {preset}")
    info = probe(str(source))
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    output_width, output_height = _target(width, height, mode)
    total, estimated = frame_total(info, duration)
    report_progress(progress, frame_index=0, total_frames=total, phase="INITIALIZING DLSS SR",
                    message=f"Initializing native DLSS SR | {mode} | preset {preset}")
    raw_cmd = ["ffmpeg", "-v", "error"]
    if start:
        raw_cmd += ["-ss", str(max(0.0, float(start)))]
    raw_cmd += ["-i", str(source)]
    if duration:
        raw_cmd += ["-t", str(max(0.001, float(duration)))]
    raw_cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    encoder_name = {"H.264": "h264_nvenc", "HEVC": "hevc_nvenc"}.get(codec)
    if not encoder_name:
        raise ValueError("DLSS SR supports H.264 and HEVC NVENC only")
    video_only = Path(destination).with_suffix(".dlss_sr-video.mkv")
    host = backend.host
    command = [str(host), "stream", str(width), str(height), str(output_width), str(output_height),
               mode.lower().replace(" ", ""), preset]
    decoder = encoder = host_process = None
    host_stderr = Path(destination).with_suffix(".dlss_sr-host.log")
    count = resets = 0
    started = time.perf_counter()
    frame_bytes = width * height * 4
    output_bytes = output_width * output_height * 4
    guide = _motion_guide(width, height)
    reader_queue: queue.Queue = queue.Queue(maxsize=2)

    def reader():
        try:
            while True:
                reader_queue.put(_read_response(host_process.stdout, output_bytes))
        except Exception as exc:
            reader_queue.put(exc)

    try:
        decoder = subprocess.Popen(raw_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        host_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=host_stderr.open("wb"))
        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        encoder = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
             "-s", f"{output_width}x{output_height}", "-r", str(fps), "-i", "-", "-an",
             "-c:v", encoder_name, "-preset", "p5", "-cq", "19", str(video_only)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("DLSS SR render cancelled")
            raw = decoder.stdout.read(frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError("FFmpeg returned a truncated RGBA frame")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4).copy()
            guide_frame = guide.process(frame)
            motion = np.asarray(guide_frame.motion, dtype=np.float32).tobytes()
            packet = INPUT_HEADER.pack(INPUT_MAGIC, count, width, height, int(guide_frame.reset), len(raw), len(motion)) + raw + motion
            host_process.stdin.write(packet)
            host_process.stdin.flush()
            values, output = reader_queue.get(timeout=120)
            if isinstance(values, Exception):
                tail = host_stderr.read_text(encoding="utf-8", errors="replace")[-2000:] if host_stderr.is_file() else ""
                raise RuntimeError(f"DLSS SR host failed: {values}; stderr: {tail}")
            if values[1] != count:
                raise RuntimeError(f"DLSS SR host frame mismatch: expected {count}, received {values[1]}")
            encoder.stdin.write(output)
            count += 1
            resets += int(guide_frame.reset)
            report_progress(progress, frame_index=count, total_frames=total, phase="PROCESSING",
                            message=f"DLSS SR {mode} | frame {count}")
        report_progress(progress, frame_index=count, total_frames=total, phase="ENCODING", message="Encoding DLSS SR output")
        encoder.stdin.close()
        encoder.wait(timeout=120)
        if encoder.returncode:
            details = encoder.stderr.read().decode(errors="replace") if encoder.stderr else ""
            raise RuntimeError(f"NVENC encoder stopped: {details[-2000:]}")
        report_progress(progress, frame_index=count, total_frames=total, phase="MUXING", message="Preserving audio and metadata")
        mux = ["ffmpeg", "-y", "-v", "error", "-i", str(video_only)]
        if start:
            mux += ["-ss", str(max(0.0, float(start)))]
        mux += ["-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "1"]
        if duration:
            mux += ["-t", str(max(0.001, float(duration))), "-shortest"]
        mux += [str(destination)]
        result = subprocess.run(mux, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return {"frames": count, "fps": count / max(0.001, time.perf_counter() - started),
                "dimensions": (output_width, output_height), "audio_preserved": info["audio_codec"] != "none",
                "scene_resets": resets, "encoder": encoder_name, "frames_estimated": estimated,
                "runtime_sha256": _sha256(host.parent / "nvngx_dlss.dll")}
    finally:
        for process in (decoder, encoder, host_process):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        video_only.unlink(missing_ok=True)
        host_stderr.unlink(missing_ok=True)
