"""Experimental application video path for isolated DLSS5 Visual Enhancer v10."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from src.backends.dlss5_v10_app import DLSS5V10ExperimentalBackend
from src.backends.dlss5_v10_app_security import (
    assert_no_host_descendants,
    install_temporary_firewall_block,
    remove_temporary_firewall_block,
)
from src.backends.dlss5_v10_client import (
    APP_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends.dlss5_v10_protocol import FrameRequest
from src.core.media_info import frame_total, probe
from src.core.process_utils import tool
from src.core.progress import report_progress
from src.video.dlssg import scene_cut_metrics
from src.video.nvenc import format_preflight_failure, nvenc_preflight


NGX_RESULT_SUCCESS = 1


def _read_exact_frame(stream, size: int, buffer: bytearray | None = None):
    """Read one exact frame, optionally into reusable storage.

    Real decoder pipes use readinto() to avoid a per-frame allocation/copy.
    Generic binary streams and existing test doubles keep the original read()
    contract for compatibility.
    """
    owns_storage = buffer is None
    storage = buffer if buffer is not None else bytearray(size)
    if len(storage) != size:
        raise ValueError("decoder frame buffer has the wrong size")
    view = memoryview(storage)
    offset = 0
    use_readinto = callable(getattr(stream, "readinto", None))
    while offset < size:
        if use_readinto:
            count = stream.readinto(view[offset:])
            if not count:
                break
            offset += count
        else:
            chunk = stream.read(size - offset)
            if not chunk:
                break
            view[offset : offset + len(chunk)] = chunk
            offset += len(chunk)
    if offset == 0:
        return b""
    if offset != size:
        raise RuntimeError(
            f"truncated RGBA frame from decoder: {offset} bytes, expected {size}"
        )
    return bytes(view) if owns_storage else view


def _validate_output(output, *, width: int, height: int, timestamp: int, reset: bool) -> None:
    if (output.width, output.height) != (width, height):
        raise RuntimeError(
            f"DLSS5 v10 output geometry {output.width}x{output.height} "
            f"does not match expected {width}x{height}"
        )
    if output.timestamp != timestamp:
        raise RuntimeError(
            f"DLSS5 v10 output timestamp {output.timestamp} != expected {timestamp}"
        )
    if output.ngx_create_result != NGX_RESULT_SUCCESS:
        raise RuntimeError(
            "DLSS5 v10 Feature-18 create did not return success: "
            f"0x{output.ngx_create_result & 0xFFFFFFFF:08X}"
        )
    if output.ngx_evaluate_result != NGX_RESULT_SUCCESS:
        raise RuntimeError(
            "DLSS5 v10 Feature-18 evaluate did not return success: "
            f"0x{output.ngx_evaluate_result & 0xFFFFFFFF:08X}"
        )
    if output.cuda_result != 0:
        raise RuntimeError(
            f"DLSS5 v10 CUDA result was {output.cuda_result}, expected 0"
        )
    expected_reset = int(reset)
    if output.scene_reset != expected_reset:
        raise RuntimeError(
            f"DLSS5 v10 scene_reset={output.scene_reset}, expected {expected_reset}"
        )
    expected_bytes = width * height * 4
    if len(output.rgba) != expected_bytes:
        raise RuntimeError(
            f"DLSS5 v10 output byte count {len(output.rgba)} != {expected_bytes}"
        )


def render_dlss5_v10(
    source,
    destination,
    backend: DLSS5V10ExperimentalBackend,
    *,
    scale: float = 1.0,
    style: str = "Natural",
    intensity: float = 0.60,
    local_tone: float = 0.40,
    local_structure: float = 0.40,
    skin_structure: float = 0.15,
    automatic_mask: bool = False,
    nr_passes: int = 1,
    color_strength: float = 1.0,
    tone_preservation: float = 0.0,
    face_skin_protection: float = 0.0,
    grain_preservation: float = 0.0,
    shimmer_suppression: float = 0.70,
    prefer_nvof: bool = False,
    start: float = 0.0,
    duration: float | None = None,
    codec: str = "H.264",
    cancel=None,
    progress=None,
) -> dict[str, object]:
    ffmpeg = tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found in the bundled runtime or on PATH.")

    backend.require_ready()
    info = probe(str(source))
    if bool(info.get("hdr")):
        raise RuntimeError(
            "DLSS 5 v10 experimental application mode currently supports SDR RGBA8 only"
        )
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    backend.validate_geometry(width, height, scale)
    frame_count, estimated = frame_total(info, duration)
    request = backend.create_request(
        width,
        height,
        scale=scale,
        style=style,
        intensity=intensity,
        local_tone=local_tone,
        local_structure=local_structure,
        skin_structure=skin_structure,
        automatic_mask=automatic_mask,
        nr_passes=nr_passes,
        color_strength=color_strength,
        tone_preservation=tone_preservation,
        face_skin_protection=face_skin_protection,
        grain_preservation=grain_preservation,
        shimmer_suppression=shimmer_suppression,
        prefer_nvof=prefer_nvof,
    )

    report_progress(
        progress,
        frame_index=0,
        total_frames=frame_count,
        phase="INITIALIZING",
        message="Initializing isolated DLSS5 v10 Feature-18 session",
    )

    decoder_cmd = [ffmpeg, "-v", "error"]
    if start:
        decoder_cmd += ["-ss", str(max(0.0, float(start)))]
    decoder_cmd += ["-i", str(source)]
    if duration:
        decoder_cmd += ["-t", str(max(1.0, float(duration)))]
    decoder_cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-"]

    decoder = subprocess.Popen(
        decoder_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder = None
    client = V10ProtocolClient(
        python=Path(sys.executable).resolve(),
        start_timeout=20.0,
        frame_timeout=90.0,
        close_grace=2.0,
    )
    video_only = Path(destination).with_suffix(".dlss5-v10-video.mkv")
    frame_bytes = width * height * 4
    count = 0
    resets = 0
    cuts = 0
    started = time.perf_counter()
    previous_raw = None
    frame_buffers = (bytearray(frame_bytes), bytearray(frame_bytes))
    frame_slot = 0
    decode_read_ms = 0.0
    scene_cut_ms = 0.0
    native_process_ms = 0.0
    encoder_write_ms = 0.0
    rule_name = f"NVE DLSS5 v10 app {os.getpid()}-{int(started * 1000) & 0xFFFF:X}"
    firewall_installed = False
    clean_close = False

    try:
        install_temporary_firewall_block(Path(sys.executable), rule_name)
        firewall_installed = True

        hello = client.start_native_application_experimental(
            backend.runtime_dir,
            backend.preflight_report,
            acknowledgement=APP_EXPERIMENT_ACK,
        )
        assert_no_host_descendants(client.pid, "app_after_hello")

        create = client.create(request)
        if create.get("native_loaded") is not True:
            raise RuntimeError("DLSS5 v10 application CREATE did not load the native runtime")
        if create.get("output_size") != [width, height]:
            raise RuntimeError(
                f"DLSS5 v10 application CREATE output_size={create.get('output_size')!r}, "
                f"expected {[width, height]}"
            )
        initialization = create.get("initialization", {})
        if not isinstance(initialization, dict):
            raise RuntimeError("DLSS5 v10 application CREATE initialization evidence is invalid")
        if initialization.get("bridge_abi_version") != 6:
            raise RuntimeError(
                f"DLSS5 v10 application bridge ABI {initialization.get('bridge_abi_version')!r} != 6"
            )
        assert_no_host_descendants(client.pid, "app_after_create")

        encoder_name = {
            "H.264": "h264_nvenc",
            "HEVC": "hevc_nvenc",
            "AV1": "av1_nvenc",
        }[codec]
        preflight = nvenc_preflight(codec, width, height)
        if not preflight["available"]:
            raise RuntimeError(format_preflight_failure(preflight))
        encoder = subprocess.Popen(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-an",
                "-c:v",
                encoder_name,
                "-preset",
                "p5",
                "-cq",
                "19",
                str(video_only),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert decoder.stdout is not None
        assert encoder.stdin is not None

        loop_started = time.perf_counter()
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("DLSS5 v10 render cancelled")
            read_started = time.perf_counter()
            raw_frame = _read_exact_frame(
                decoder.stdout, frame_bytes, frame_buffers[frame_slot]
            )
            decode_read_ms += (time.perf_counter() - read_started) * 1000
            if not raw_frame:
                break

            reset = count == 0
            if previous_raw is not None:
                cut_started = time.perf_counter()
                cut = scene_cut_metrics(previous_raw, raw_frame, width, height)
                scene_cut_ms += (time.perf_counter() - cut_started) * 1000
                if bool(cut["is_cut"]):
                    reset = True
                    cuts += 1
            process_started = time.perf_counter()
            output = client.process_frame(
                FrameRequest(timestamp=count, reset=reset, rgba=raw_frame)
            )
            native_process_ms += (time.perf_counter() - process_started) * 1000
            _validate_output(
                output,
                width=width,
                height=height,
                timestamp=count,
                reset=reset,
            )
            assert_no_host_descendants(client.pid, f"app_after_frame_{count}")

            rendered = np.frombuffer(output.rgba, dtype=np.uint8).reshape(
                height, width, 4
            )
            try:
                write_started = time.perf_counter()
                encoder.stdin.write(
                    np.ascontiguousarray(rendered[..., :3]).tobytes()
                )
                encoder_write_ms += (time.perf_counter() - write_started) * 1000
            except BrokenPipeError as exc:
                details = (
                    encoder.stderr.read() if encoder.stderr else b""
                ).decode(errors="replace")
                raise RuntimeError(
                    f"NVENC encoder stopped early: {details[-2000:]}"
                ) from exc

            previous_raw = raw_frame
            frame_slot ^= 1
            count += 1
            resets += int(reset)
            report_progress(
                progress,
                frame_index=count,
                total_frames=frame_count,
                phase="PROCESSING",
                message=(
                    "Processing DLSS5 v10 scene-aware temporal frames"
                    + (" (scene reset)" if reset else "")
                ),
            )

        processing_loop_wall_seconds = time.perf_counter() - loop_started
        decoder.wait(timeout=30)
        if decoder.returncode:
            details = (
                decoder.stderr.read() if decoder.stderr else b""
            ).decode(errors="replace")
            raise RuntimeError(f"decoder failed: {details[-2000:]}")
        if count == 0:
            raise RuntimeError("DLSS5 v10 decoder produced no frames")

        report_progress(
            progress,
            frame_index=count,
            total_frames=frame_count,
            phase="ENCODING",
            message="Finalizing DLSS5 v10 video",
        )
        encoder.stdin.close()
        encoder.wait(timeout=120)
        if encoder.returncode:
            raise RuntimeError(
                (encoder.stderr.read() if encoder.stderr else b"")
                .decode(errors="replace")[-2000:]
            )

        close_result = client.close()
        clean_close = close_result == "CLOSED"
        if not clean_close:
            raise RuntimeError(
                f"DLSS5 v10 isolated host did not close cleanly: {close_result}"
            )

        report_progress(
            progress,
            frame_index=count,
            total_frames=frame_count,
            phase="MUXING",
            message="Preserving source audio and metadata",
        )
        mux = [ffmpeg, "-y", "-v", "error", "-i", str(video_only)]
        if start:
            mux += ["-ss", str(max(0.0, float(start)))]
        mux += [
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-map_metadata",
            "1",
        ]
        if duration:
            mux += [
                "-t",
                str(max(1.0, float(duration))),
                "-shortest",
            ]
        mux += [str(destination)]
        result = subprocess.run(
            mux,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])

        total_wall_seconds = time.perf_counter() - started
        setup_seconds = max(0.0, loop_started - started)
        finalize_seconds = max(
            0.0,
            total_wall_seconds - setup_seconds - processing_loop_wall_seconds,
        )

        return {
            "frames": count,
            "fps": count / max(0.001, total_wall_seconds),
            "processing_fps": count / max(0.001, processing_loop_wall_seconds),
            "dimensions": (width, height),
            "audio_preserved": bool(info["audio_codec"] != "none"),
            "scene_resets": resets,
            "detected_scene_cuts": cuts,
            "encoder": encoder_name,
            "frames_estimated": estimated,
            "experimental_backend": "dlss5-v10",
            "processing_scale": float(scale),
            "quality_controls": {
                "nr_passes": int(nr_passes),
                "color_strength": float(color_strength),
                "tone_preservation": float(tone_preservation),
                "face_skin_protection": float(face_skin_protection),
                "grain_preservation": float(grain_preservation),
                "shimmer_suppression": float(shimmer_suppression),
                "prefer_nvof": bool(prefer_nvof),
            },
            "performance": {
                "total_wall_seconds": total_wall_seconds,
                "setup_seconds": setup_seconds,
                "processing_loop_wall_seconds": processing_loop_wall_seconds,
                "processing_fps": count / max(0.001, processing_loop_wall_seconds),
                "finalize_seconds": finalize_seconds,
                "decode_read_ms": decode_read_ms,
                "scene_cut_ms": scene_cut_ms,
                "native_process_ms": native_process_ms,
                "encoder_write_ms": encoder_write_ms,
                "transport": "double-buffered-readinto/host-protocol/rawvideo-stdin",
            },
            "host_close": "CLOSED",
            "firewall_containment": True,
            "hello": hello,
            "initialization": initialization,
        }
    finally:
        if not clean_close:
            try:
                client.abort()
            except Exception:
                pass
        for process in (decoder, encoder):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        video_only.unlink(missing_ok=True)
        if firewall_installed:
            remove_temporary_firewall_block(rule_name)
