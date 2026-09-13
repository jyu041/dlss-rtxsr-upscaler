"""Real-video 2X interpolation through persistent NVOF + offline DLSS-G."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Callable

from src.backends.dlssg import DLSSGBackend
from src.backends.dlssg_worker import DlssgWorker, MOTION_MODE_NVIDIA_OPTICAL_FLOW
from src.core.paths import safe_input
from src.core.progress import report_progress


def ffmpeg_executable() -> str:
    from src.core.process_utils import tool

    found = tool("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError) as exc:
        raise RuntimeError("FFmpeg is unavailable; install it or imageio-ffmpeg in the project environment") from exc


def probe_video(source: str | Path) -> dict[str, object]:
    import av

    path = safe_input(str(source))
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or stream.base_rate or 0)
        duration = float(container.duration or 0) / av.time_base
        return {
            "path": str(path),
            "width": int(stream.width),
            "height": int(stream.height),
            "fps": fps,
            "frames": int(stream.frames or 0),
            "duration": duration,
            "audio": bool(container.streams.audio),
        }


def output_frame_count(input_frames: int, duplicate_terminal_frame: bool = True) -> int:
    if input_frames < 1:
        return 0
    return 2 * input_frames if duplicate_terminal_frame else 2 * input_frames - 1


def _mad(a: bytes, b: bytes) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("MAD inputs must be equal non-empty frames")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _read_frame(stream, frame_bytes: int) -> bytes:
    """Read one exact raw frame, allowing normal short pipe reads."""
    chunks: list[bytes] = []
    remaining = frame_bytes
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return b""
            received = frame_bytes - remaining
            raise RuntimeError(f"FFmpeg decoder returned a truncated RGBA frame ({received}/{frame_bytes} bytes)")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_contact_triplet(directory: Path, index: int, previous: bytes, generated: bytes,
                           current: bytes, width: int, height: int) -> list[str]:
    try:
        from PIL import Image
    except ImportError:
        return []
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for kind, data in (("previous", previous), ("generated", generated), ("current", current)):
        path = directory / f"pair_{index:04d}_{kind}.png"
        Image.frombytes("RGBA", (width, height), data).save(path)
        paths.append(str(path))
    return paths


def render_dlssg_2x(
    source: str | Path,
    destination: str | Path,
    backend: DLSSGBackend,
    *,
    codec: str = "h264_nvenc",
    preserve_audio: bool = True,
    cancel=None,
    progress=None,
    terminal_frame_policy: str = "duplicate",
    artifact_dir: str | Path | None = None,
    diagnostic_callback: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Interpolate adjacent decoded real frames and preserve duration at 2X CFR.

    The default terminal policy duplicates the last real frame once. N input
    frames therefore produce N-1 generated midpoints plus N real frames plus
    one terminal duplicate: 2N frames at exactly twice the input FPS.
    """
    if terminal_frame_policy not in {"duplicate", "short"}:
        raise ValueError("terminal_frame_policy must be duplicate or short")
    source_path = safe_input(str(source))
    destination_path = Path(destination).expanduser().resolve()
    if destination_path == source_path:
        raise ValueError("DLSS-G output path must differ from the input path")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe_video(source_path)
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    if width < 1 or height < 1 or fps <= 0:
        raise RuntimeError(f"invalid video geometry/timing: {info}")
    config = backend.require_configuration()
    ffmpeg = ffmpeg_executable()
    frame_bytes = width * height * 4
    output_fps = fps * 2.0
    temporary = destination_path.with_suffix(".dlssg-video.mkv")
    log_path = destination_path.with_suffix(".dlssg-worker.log")
    manifest_path = destination_path.with_suffix(".dlssg-manifest.json")
    artifacts = Path(artifact_dir).resolve() if artifact_dir else destination_path.parent / f"{destination_path.stem}_frames"
    decoder = encoder = None
    worker_lines: list[str] = []
    timings: dict[str, list[float]] = defaultdict(list)
    hashes: list[str] = []
    comparisons: list[dict[str, object]] = []
    input_count = output_count = generated_count = 0
    decode_seconds = encode_seconds = 0.0
    started = time.perf_counter()

    def diagnostics(line: str) -> None:
        worker_lines.append(line)
        if diagnostic_callback:
            diagnostic_callback(line)

    try:
        decoder = subprocess.Popen(
            [ffmpeg, "-v", "error", "-i", str(source_path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        encode_options = ["-c:v", codec, "-preset", "p5", "-cq", "19"] if codec.endswith("_nvenc") else [
            "-c:v", codec, "-preset", "medium", "-crf", "18"
        ]
        encoder = subprocess.Popen(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
             "-r", f"{output_fps:.12g}", "-i", "-", "-an", *encode_options, str(temporary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert decoder.stdout is not None and encoder.stdin is not None
        client = DlssgWorker(
            config.worker,
            config.community_runtime,
            config.official_runtime_dir,
            diagnostic_callback=diagnostics,
        )
        with client:
            client.create(width, height, motion_mode=MOTION_MODE_NVIDIA_OPTICAL_FLOW)
            previous: bytes | None = None
            frame_id = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("DLSS-G interpolation cancelled")
                decode_start = time.perf_counter()
                current = _read_frame(decoder.stdout, frame_bytes)
                decode_seconds += time.perf_counter() - decode_start
                if not current:
                    break
                input_count += 1
                result = client.process(frame_id, current, reset=frame_id == 0)
                frame_id += 1
                if previous is None:
                    assert result.reset_only and not result.output
                    encode_start = time.perf_counter(); encoder.stdin.write(current)
                    encode_seconds += time.perf_counter() - encode_start
                    output_count += 1
                else:
                    if result.generated_count != 1 or result.disable_interpolation:
                        raise RuntimeError(f"DLSS-G returned no midpoint for input frame {frame_id - 1}")
                    generated = result.output
                    digest = hashlib.sha256(generated).hexdigest().upper()
                    if hashes and hashes[-1] == digest:
                        raise RuntimeError(f"stale consecutive DLSS-G output at pair {frame_id - 1}")
                    comparison = {
                        "pair": frame_id - 1,
                        "sha256": digest,
                        "identical_previous": generated == previous,
                        "identical_current": generated == current,
                        "mad_previous": _mad(generated, previous),
                        "mad_current": _mad(generated, current),
                        "mad_real_pair": _mad(previous, current),
                    }
                    if comparison["identical_previous"] or comparison["identical_current"]:
                        raise RuntimeError(f"DLSS-G output duplicates a real frame at pair {frame_id - 1}")
                    hashes.append(digest); comparisons.append(comparison); generated_count += 1
                    if generated_count <= 3:
                        _write_contact_triplet(artifacts, generated_count, previous, generated, current, width, height)
                    encode_start = time.perf_counter(); encoder.stdin.write(generated); encoder.stdin.write(current)
                    encode_seconds += time.perf_counter() - encode_start
                    output_count += 2
                    for name in ("nvof_upload_ms", "nvof_execute_ms", "flow_conversion_ms", "upload_ms",
                                 "evaluate_cpu_ms", "gpu_wait_ms", "readback_ms", "total_process_ms"):
                        timings[name].append(float(getattr(result, name)))
                previous = current
                report_progress(progress, frame_index=input_count, total_frames=int(info["frames"]) or None,
                                phase="DLSS-G 2X", message=f"NVOF + DLSS-G frame {input_count}")
            if input_count == 0 or previous is None:
                raise RuntimeError("input video contains no decodable frames")
            if terminal_frame_policy == "duplicate":
                encoder.stdin.write(previous); output_count += 1
        encoder.stdin.close(); encoder.wait(timeout=300)
        if encoder.returncode:
            raise RuntimeError((encoder.stderr.read() if encoder.stderr else b"").decode(errors="replace")[-4000:])
        if decoder.wait(timeout=60):
            raise RuntimeError((decoder.stderr.read() if decoder.stderr else b"").decode(errors="replace")[-4000:])
        if preserve_audio and bool(info["audio"]):
            mux = subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-i", str(temporary), "-i", str(source_path), "-map", "0:v:0",
                 "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "1", "-shortest", str(destination_path)],
                capture_output=True, text=True, check=False,
            )
            if mux.returncode:
                raise RuntimeError(f"audio remux failed: {mux.stderr[-4000:]}")
        else:
            temporary.replace(destination_path)
        duration_policy = "duplicate final real frame for exact 2X CFR duration" if terminal_frame_policy == "duplicate" else "2N-1 short tail"
        summary = {name: sum(values) / len(values) for name, values in timings.items() if values}
        manifest = {
            "status": "PASS",
            "input": str(source_path),
            "output": str(destination_path),
            "width": width,
            "height": height,
            "input_fps": fps,
            "output_fps": output_fps,
            "input_frames": input_count,
            "generated_frames": generated_count,
            "output_frames": output_count,
            "expected_output_frames": output_frame_count(input_count, terminal_frame_policy == "duplicate"),
            "terminal_policy": duration_policy,
            "audio_preserved": preserve_audio and bool(info["audio"]),
            "generated": comparisons,
            "timings_mean_ms": summary,
            "decode_ms_per_frame": decode_seconds * 1000 / input_count,
            "encode_write_ms_per_output": encode_seconds * 1000 / output_count,
            "end_to_end_fps": output_count / max(time.perf_counter() - started, 1e-9),
            "worker_diagnostics": str(log_path),
        }
        log_path.write_text("\n".join(worker_lines) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    finally:
        if worker_lines:
            log_path.write_text("\n".join(worker_lines) + "\n", encoding="utf-8")
        for process in (decoder, encoder):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        temporary.unlink(missing_ok=True)
