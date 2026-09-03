"""Streaming DLSS5 video path with one temporal worker session per job."""

from __future__ import annotations

import subprocess
import time
from itertools import chain
from pathlib import Path

from src.core.media_info import frame_total, probe
from src.core.progress import report_progress


def render_dlss5(source, destination, backend, options, *, start=0.0, duration=None, codec="H.264", cancel=None, progress=None):
    info = probe(str(source))
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    frame_count, estimated = frame_total(info, duration)
    session_frame_count = frame_count or 2
    report_progress(progress, frame_index=0, total_frames=frame_count, phase="INITIALIZING", message="Initializing DLSS5 Feature-18")
    raw = ["ffmpeg", "-v", "error"]
    if start:
        raw += ["-ss", str(max(0.0, float(start)))]
    raw += ["-i", str(source)]
    if duration:
        raw += ["-t", str(max(1.0, float(duration)))]
    raw += ["-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    decoder = subprocess.Popen(raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    encoder = None
    video_only = Path(destination).with_suffix(".dlss5-video.mkv")
    count = 0
    resets = 0
    started = time.perf_counter()
    frame_bytes = width * height * 4
    try:
        stream = decoder.stdout
        assert stream is not None
        stream_frames = iter(lambda: stream.read(frame_bytes), b"")

        def frames():
            for raw_frame in stream_frames:
                if len(raw_frame) != frame_bytes:
                    break
                import numpy as np
                yield np.frombuffer(raw_frame, dtype=np.uint8).reshape(height, width, 4).copy()

        rendered = backend.process_frames(frames(), width=width, height=height, frame_count=session_frame_count, options=options, cancel=cancel)
        first, first_meta = next(rendered)
        output_height, output_width = first.shape[:2]
        encoder_name = {"H.264": "h264_nvenc", "HEVC": "hevc_nvenc", "AV1": "av1_nvenc"}[codec]
        encoder = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{output_width}x{output_height}", "-r", str(fps), "-i", "-", "-an", "-c:v", encoder_name, "-preset", "p5", "-cq", "19", str(video_only)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert encoder.stdin is not None
        for output, meta in chain(((first, first_meta),), rendered):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("DLSS5 render cancelled")
            try:
                encoder.stdin.write(output[..., :3].tobytes())
            except BrokenPipeError as exc:
                details = (encoder.stderr.read() if encoder.stderr else b"").decode(errors="replace")
                raise RuntimeError(f"NVENC encoder stopped early: {details[-2000:]}") from exc
            count += 1
            resets += int(meta["reset"])
            report_progress(progress, frame_index=count, total_frames=frame_count, phase="PROCESSING", message="Processing DLSS5 temporal frames")
        report_progress(progress, frame_index=count, total_frames=frame_count, phase="ENCODING", message="Encoding DLSS5 output")
        encoder.stdin.close()
        encoder.wait(timeout=120)
        if encoder.returncode:
            raise RuntimeError((encoder.stderr.read() if encoder.stderr else b"").decode(errors="replace")[-2000:])
        report_progress(progress, frame_index=count, total_frames=frame_count, phase="MUXING", message="Preserving audio and metadata")
        mux = ["ffmpeg", "-y", "-v", "error", "-i", str(video_only)]
        if start:
            mux += ["-ss", str(max(0.0, float(start)))]
        mux += ["-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "1"]
        if duration:
            mux += ["-t", str(max(1.0, float(duration))), "-shortest"]
        mux += [str(destination)]
        result = subprocess.run(mux, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return {"frames": count, "fps": count / max(0.001, time.perf_counter() - started), "dimensions": (output_width, output_height), "audio_preserved": bool(info["audio_codec"] != "none"), "scene_resets": resets, "encoder": encoder_name, "frames_estimated": estimated}
    finally:
        for process in (decoder, encoder):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        video_only.unlink(missing_ok=True)
