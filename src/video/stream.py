"""Bounded FFmpeg -> NVVFX -> FFmpeg video pipeline."""
from pathlib import Path
import subprocess, time
import numpy as np
from src.core.process_utils import tool
from src.core.paths import aligned_dimensions
from src.core.progress import report_progress
from src.video.rtx_vsr_worker import RTXVSRSession

def render_vsr(source, destination, backend, scale=2.0, quality="ULTRA", mode="Super Resolution", cancel=None, progress=None, codec="H.264"):
    if not tool("ffmpeg"): raise RuntimeError("ffmpeg was not found")
    from src.core.media_info import frame_total, probe
    info = probe(str(source)); width, height = int(info["width"]), int(info["height"])
    if mode in {"Deblur", "Denoise"}: output = (width, height)
    else: output = aligned_dimensions(width, height, scale)
    frames, estimated = frame_total(info)
    raw_cmd = ["ffmpeg", "-v", "error", "-i", str(source), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    video_only = Path(destination).with_suffix(".video_only.mp4")
    enc = {"H.264": "h264_nvenc", "HEVC": "hevc_nvenc"}.get(codec)
    if not enc: raise ValueError("RTX VSR supports H.264 and HEVC NVENC only")
    enc_cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{output[0]}x{output[1]}", "-r", str(info["fps"]), "-i", "-", "-an", "-c:v", enc, "-preset", "p5", "-cq", "19", str(video_only)]
    report_progress(progress, frame_index=0, total_frames=frames, phase="INITIALIZING", message="Initializing RTX VSR")
    decoder = encoder = None
    session = None
    count = 0; started = time.perf_counter(); memory_samples = []
    try:
        decoder = subprocess.Popen(raw_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        encoder = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        session = RTXVSRSession(heartbeat=lambda line: report_progress(progress, frame_index=count, total_frames=frames, phase="INITIALIZING", message=f"RTX VSR worker: {line}"))
        session.start(width, height, output[0], output[1], mode, quality)
        frame_bytes = width * height * 3
        while True:
            if cancel and cancel.is_set(): raise InterruptedError("Render cancelled")
            raw = decoder.stdout.read(frame_bytes)
            if not raw: break
            if len(raw) != frame_bytes: raise RuntimeError("FFmpeg returned a truncated RGB frame")
            cpu = session.process_frame(count, np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy())
            encoder.stdin.write(cpu.tobytes())
            count += 1
            if count == 1 or count % 100 == 0:
                sample = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                memory_samples.append({"frame": count, "gpu_memory_mib": sample.stdout.strip() if sample.returncode == 0 else "unavailable"})
            report_progress(progress, frame_index=count, total_frames=frames, phase="PROCESSING", message="Processing RTX VSR")
        teardown = session.finish()
        decoder.wait(timeout=30)
        if decoder.returncode:
            raise RuntimeError(decoder.stderr.read().decode(errors="replace")[-2000:] if decoder.stderr else "FFmpeg decoder failed")
        report_progress(progress, frame_index=count, total_frames=frames, phase="ENCODING", message="Finalizing video encode")
        encoder.stdin.close(); encoder.wait(timeout=120)
        if encoder.returncode: raise RuntimeError(encoder.stderr.read().decode(errors="replace")[-2000:])
        report_progress(progress, frame_index=count, total_frames=frames, phase="MUXING", message="Preserving audio and metadata")
        mux = ["ffmpeg", "-y", "-v", "error", "-i", str(video_only), "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "1", str(destination)]
        result = subprocess.run(mux, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if result.returncode: raise RuntimeError(result.stderr[-2000:])
        return {"frames": count, "fps": count / max(.001, time.perf_counter() - started), "dimensions": output, "audio_preserved": bool(info["audio_codec"] != "none"), "encoder": enc, "gpu_memory_samples": memory_samples, "frames_estimated": estimated, "worker_teardown": teardown}
    finally:
        if session:
            session.close()
        for process in (decoder, encoder):
            if process and process.poll() is None: process.terminate(); process.wait(timeout=5)
        video_only.unlink(missing_ok=True)
