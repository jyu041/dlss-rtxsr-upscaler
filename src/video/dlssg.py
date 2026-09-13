"""Real-video 2X interpolation through persistent NVOF + offline DLSS-G."""

from __future__ import annotations

from collections import defaultdict
import heapq
import hashlib
import json
from pathlib import Path
import subprocess
import threading
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
        context = stream.codec_context
        rate = stream.average_rate or stream.base_rate
        fps = float(rate or 0)
        duration = float(container.duration or 0) / av.time_base
        audio_stream = container.streams.audio[0] if container.streams.audio else None
        audio_duration = (
            float(audio_stream.duration * audio_stream.time_base)
            if audio_stream is not None and audio_stream.duration is not None
            else (duration if audio_stream is not None else 0.0)
        )
        color_range = int(context.color_range)
        color_space = int(context.colorspace)
        color_primaries = int(context.color_primaries)
        color_transfer = int(context.color_trc)
        return {
            "path": str(path),
            "codec": context.codec.name if context.codec else "unknown",
            "pixel_format": context.format.name if context.format else "unknown",
            "width": int(stream.width),
            "height": int(stream.height),
            "fps": fps,
            "fps_numerator": int(rate.numerator) if rate else 0,
            "fps_denominator": int(rate.denominator) if rate else 1,
            "frames": int(stream.frames or 0),
            "duration": duration,
            "audio": audio_stream is not None,
            "audio_codec": audio_stream.codec_context.codec.name if audio_stream and audio_stream.codec_context.codec else None,
            "audio_duration": audio_duration,
            "color_range": color_range,
            "color_space": color_space,
            "color_primaries": color_primaries,
            "color_transfer": color_transfer,
            "hdr": color_transfer in {16, 18},
        }


def output_frame_count(input_frames: int, duplicate_terminal_frame: bool = True) -> int:
    if input_frames < 1:
        return 0
    return 2 * input_frames if duplicate_terminal_frame else 2 * input_frames - 1


def _mad(a: bytes, b: bytes) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("MAD inputs must be equal non-empty frames")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def scene_cut_metrics(previous: bytes, current: bytes, width: int, height: int) -> dict[str, float | bool]:
    """Return a deterministic, sampled SDR scene-cut decision."""
    import numpy as np

    expected = width * height * 4
    if len(previous) != expected or len(current) != expected:
        raise ValueError("scene-cut inputs must be tightly packed RGBA frames")
    step = max(1, min(width, height) // 128)
    left = np.frombuffer(previous, dtype=np.uint8).reshape(height, width, 4)[::step, ::step, :3].astype(np.int16)
    right = np.frombuffer(current, dtype=np.uint8).reshape(height, width, 4)[::step, ::step, :3].astype(np.int16)
    rgb_mad = float(np.abs(left - right).mean())
    left_luma = ((54 * left[..., 0] + 183 * left[..., 1] + 19 * left[..., 2]) >> 8).astype(np.uint8)
    right_luma = ((54 * right[..., 0] + 183 * right[..., 1] + 19 * right[..., 2]) >> 8).astype(np.uint8)
    left_hist = np.bincount(left_luma.ravel(), minlength=256).reshape(32, 8).sum(axis=1).astype(np.float64)
    right_hist = np.bincount(right_luma.ravel(), minlength=256).reshape(32, 8).sum(axis=1).astype(np.float64)
    left_hist /= max(float(left_hist.sum()), 1.0)
    right_hist /= max(float(right_hist.sum()), 1.0)
    histogram_distance = float(np.abs(left_hist - right_hist).sum() * 0.5)
    is_cut = (rgb_mad >= 45.0 and histogram_distance >= 0.25) or rgb_mad >= 80.0
    return {"rgb_mad": rgb_mad, "histogram_distance": histogram_distance, "is_cut": is_cut}


def _encoder_color_options(info: dict[str, object]) -> list[str]:
    options: list[str] = ["-pix_fmt", "yuv420p"]
    mappings = (
        ("color_range", {1: "tv", 2: "pc"}, "-color_range"),
        ("color_space", {1: "bt709", 5: "bt470bg", 6: "smpte170m", 9: "bt2020nc"}, "-colorspace"),
        ("color_primaries", {1: "bt709", 5: "bt470bg", 6: "smpte170m", 9: "bt2020"}, "-color_primaries"),
        ("color_transfer", {1: "bt709", 6: "smpte170m", 14: "bt2020-10", 15: "bt2020-12"}, "-color_trc"),
    )
    for key, values, option in mappings:
        value = values.get(int(info[key]))
        if value:
            options.extend((option, value))
    return options


def _bitstream_color_options(codec: str, info: dict[str, object]) -> list[str]:
    """Write source SDR color identity into the encoded H.26x VUI.

    FFmpeg's container-level color options are not sufficient for every NVENC
    raw-RGBA input path, so set the same values in the elementary bitstream.
    Unknown source fields are intentionally left unspecified.
    """
    values: list[str] = []
    color_range = int(info["color_range"])
    if color_range in {1, 2}:
        values.append(f"video_full_range_flag={1 if color_range == 2 else 0}")
    for key, option in (
        ("color_primaries", "colour_primaries"),
        ("color_transfer", "transfer_characteristics"),
        ("color_space", "matrix_coefficients"),
    ):
        value = int(info[key])
        if value > 0:
            values.append(f"{option}={value}")
    if not values:
        return []
    normalized = codec.lower()
    if "264" in normalized:
        return ["-bsf:v", "h264_metadata=" + ":".join(values)]
    if "265" in normalized or "hevc" in normalized:
        return ["-bsf:v", "hevc_metadata=" + ":".join(values)]
    return []


def _vram_mib() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return int(result.stdout.strip().splitlines()[0]) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
        return None


class _VramSampler:
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="dlssg-vram-sampler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            value = _vram_mib()
            if value is not None:
                self.samples.append(value)
            self._stop.wait(self.interval)

    def stop(self) -> int | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return max(self.samples) if self.samples else None


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


def _write_contact_sheet(directory: Path, candidates: list[tuple], width: int, height: int) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not candidates:
        return None
    thumbnail_width = min(width, 320)
    thumbnail_height = max(1, round(height * thumbnail_width / width))
    label_height = 24
    sheet = Image.new("RGB", (thumbnail_width * 3, (thumbnail_height + label_height) * len(candidates)), "black")
    draw = ImageDraw.Draw(sheet)
    for row, (_score, pair, previous, generated, current, _record) in enumerate(candidates):
        top = row * (thumbnail_height + label_height)
        for column, (name, data) in enumerate((("PREVIOUS", previous), ("GENERATED", generated), ("CURRENT", current))):
            image = Image.frombytes("RGBA", (width, height), data).convert("RGB")
            if image.size != (thumbnail_width, thumbnail_height):
                image = image.resize((thumbnail_width, thumbnail_height), Image.Resampling.LANCZOS)
            sheet.paste(image, (column * thumbnail_width, top + label_height))
            draw.text((column * thumbnail_width + 4, top + 4), f"{name} pair {pair}", fill="white")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "selected_transitions_contact_sheet.png"
    sheet.save(path)
    return str(path)


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
    scene_cut_detection: bool = True,
    diagnostic_count: int = 8,
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
    if bool(info["hdr"]):
        raise RuntimeError("HDR/PQ/HLG input is not supported by the current SDR RGBA8 DLSS-G backend")
    width, height, fps = int(info["width"]), int(info["height"]), float(info["fps"])
    if width < 1 or height < 1 or fps <= 0:
        raise RuntimeError(f"invalid video geometry/timing: {info}")
    config = backend.require_configuration()
    ffmpeg = ffmpeg_executable()
    frame_bytes = width * height * 4
    output_fps = fps * 2.0
    fps_numerator = int(info["fps_numerator"])
    fps_denominator = int(info["fps_denominator"])
    output_rate = f"{fps_numerator * 2}/{fps_denominator}" if fps_numerator else f"{output_fps:.12g}"
    h26x_output = "264" in codec.lower() or "265" in codec.lower() or "hevc" in codec.lower()
    temporary = destination_path.with_suffix(".dlssg-video.mp4" if h26x_output else ".dlssg-video.mkv")
    log_path = destination_path.with_suffix(".dlssg-worker.log")
    manifest_path = destination_path.with_suffix(".dlssg-manifest.json")
    artifacts = Path(artifact_dir).resolve() if artifact_dir else destination_path.parent / f"{destination_path.stem}_frames"
    decoder = encoder = None
    worker_lines: list[str] = []
    timings: dict[str, list[float]] = defaultdict(list)
    hashes: list[str] = []
    comparisons: list[dict[str, object]] = []
    scene_cuts: list[dict[str, object]] = []
    candidates: list[tuple] = []
    input_count = output_count = generated_count = scene_cut_holds = 0
    interpolation_disabled_ids: list[int] = []
    previous_generated_digest: str | None = None
    decode_seconds = encode_seconds = 0.0
    started = time.perf_counter()
    vram_before = _vram_mib()
    vram_sampler = _VramSampler()
    vram_sampler.start()
    peak_vram: int | None = None

    def diagnostics(line: str) -> None:
        worker_lines.append(line)
        if diagnostic_callback:
            diagnostic_callback(line)

    try:
        decoder = subprocess.Popen(
            [ffmpeg, "-v", "error", "-i", str(source_path), "-f", "rawvideo", "-pix_fmt", "rgba",
             "-fps_mode", "passthrough", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        encode_options = ["-c:v", codec, "-preset", "p5", "-cq", "19"] if codec.endswith("_nvenc") else [
            "-c:v", codec, "-preset", "medium", "-crf", "18"
        ]
        container_options = (
            ["-video_track_timescale", str(fps_numerator * 2)]
            if h26x_output and fps_numerator else []
        )
        encoder = subprocess.Popen(
            [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
             "-r", output_rate, "-i", "-", "-an", *encode_options,
             *_encoder_color_options(info), *_bitstream_color_options(codec, info),
             *container_options, str(temporary)],
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
                if previous is None:
                    try:
                        result = client.process(frame_id, current, reset=True)
                    except Exception as exc:
                        raise RuntimeError(f"DLSS-G worker failed at input frame {frame_id}") from exc
                    frame_id += 1
                    assert result.reset_only and not result.output
                    encode_start = time.perf_counter(); encoder.stdin.write(current)
                    encode_seconds += time.perf_counter() - encode_start
                    output_count += 1
                else:
                    cut = scene_cut_metrics(previous, current, width, height) if scene_cut_detection else {
                        "rgb_mad": _mad(previous, current), "histogram_distance": 0.0, "is_cut": False
                    }
                    if bool(cut["is_cut"]):
                        client.reset_history()
                        try:
                            result = client.process(frame_id, current, reset=True)
                        except Exception as exc:
                            raise RuntimeError(f"DLSS-G worker reset failed at scene cut frame {frame_id}") from exc
                        if not result.reset_only or result.output:
                            raise RuntimeError(f"scene-cut reset unexpectedly returned output at frame {frame_id}")
                        scene_cut = {"pair": frame_id, **cut, "hold": "previous"}
                        scene_cuts.append(scene_cut)
                        scene_cut_holds += 1
                        previous_generated_digest = None
                        _write_contact_triplet(artifacts / "scene_cuts", frame_id, previous, previous, current, width, height)
                        encode_start = time.perf_counter(); encoder.stdin.write(previous); encoder.stdin.write(current)
                        encode_seconds += time.perf_counter() - encode_start
                        output_count += 2
                        frame_id += 1
                        previous = current
                        report_progress(progress, frame_index=input_count, total_frames=int(info["frames"]) or None,
                                        phase="DLSS-G 2X", message=f"Scene cut reset at frame {input_count}")
                        continue
                    try:
                        result = client.process(frame_id, current)
                    except Exception as exc:
                        raise RuntimeError(f"DLSS-G worker failed at input frame {frame_id}") from exc
                    frame_id += 1
                    if result.generated_count != 1 or result.disable_interpolation:
                        interpolation_disabled_ids.append(frame_id - 1)
                        raise RuntimeError(f"DLSS-G returned no midpoint for input frame {frame_id - 1}")
                    generated = result.output
                    digest = hashlib.sha256(generated).hexdigest().upper()
                    real_pair_mad = _mad(previous, current)
                    stale_suspect = previous_generated_digest == digest and real_pair_mad > 1.0
                    comparison = {
                        "pair": frame_id - 1,
                        "sha256": digest,
                        "identical_previous": generated == previous,
                        "identical_current": generated == current,
                        "identical_previous_generated": previous_generated_digest == digest,
                        "stale_suspect": stale_suspect,
                        "mad_previous": _mad(generated, previous),
                        "mad_current": _mad(generated, current),
                        "mad_real_pair": real_pair_mad,
                        "flow_mean_x": result.flow_mean_x,
                        "flow_mean_y": result.flow_mean_y,
                        "flow_median_x": result.flow_median_x,
                        "flow_median_y": result.flow_median_y,
                        "flow_p95_magnitude": result.flow_p95_magnitude,
                        "flow_maximum_magnitude": result.flow_maximum_magnitude,
                        "flow_standard_deviation_magnitude": result.flow_standard_deviation_magnitude,
                        "flow_near_zero_percent": result.flow_near_zero_percent,
                        "flow_unusually_large_percent": result.flow_unusually_large_percent,
                    }
                    hashes.append(digest); comparisons.append(comparison); generated_count += 1
                    previous_generated_digest = digest
                    score = (result.flow_p95_magnitude + result.flow_standard_deviation_magnitude +
                             real_pair_mad / 8.0)
                    heapq.heappush(candidates, (score, frame_id - 1, previous, generated, current, comparison))
                    if len(candidates) > max(1, diagnostic_count):
                        heapq.heappop(candidates)
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
                 "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "1", str(destination_path)],
                capture_output=True, text=True, check=False,
            )
            if mux.returncode:
                raise RuntimeError(f"audio remux failed: {mux.stderr[-4000:]}")
        else:
            temporary.replace(destination_path)
        peak_vram = vram_sampler.stop()
        output_info = probe_video(destination_path)
        encoded_frames = int(output_info["frames"])
        if encoded_frames and encoded_frames != output_count:
            raise RuntimeError(
                f"encoded output frame count mismatch ({encoded_frames} != {output_count}); "
                "the muxer or encoder dropped a temporal sample"
            )
        color_metadata_preserved = all(
            int(info[key]) <= 0 or int(output_info[key]) == int(info[key])
            for key in ("color_range", "color_space", "color_primaries", "color_transfer")
        )
        if not color_metadata_preserved:
            raise RuntimeError(
                "encoded output color metadata differs from the source: "
                f"source={tuple(info[key] for key in ('color_range', 'color_space', 'color_primaries', 'color_transfer'))} "
                f"output={tuple(output_info[key] for key in ('color_range', 'color_space', 'color_primaries', 'color_transfer'))}"
            )
        selected = sorted(candidates, reverse=True)
        selected_files: list[str] = []
        for _score, pair, previous_bytes, generated_bytes, current_bytes, _record in selected:
            selected_files.extend(_write_contact_triplet(
                artifacts, pair, previous_bytes, generated_bytes, current_bytes, width, height
            ))
        contact_sheet = _write_contact_sheet(artifacts, selected, width, height)
        duration_policy = "duplicate final real frame for exact 2X CFR duration" if terminal_frame_policy == "duplicate" else "2N-1 short tail"
        summary = {name: sum(values) / len(values) for name, values in timings.items() if values}
        flow_summary = {
            name: sum(float(item[name]) for item in comparisons) / len(comparisons)
            for name in (
                "flow_mean_x", "flow_mean_y", "flow_median_x", "flow_median_y",
                "flow_p95_magnitude", "flow_maximum_magnitude",
                "flow_standard_deviation_magnitude", "flow_near_zero_percent",
                "flow_unusually_large_percent",
            )
        } if comparisons else {}
        lifecycle = {
            "worker_process_count": 1,
            "nvof_initialization_count": sum(line == "NVOF_INSTANCE_CREATED" for line in worker_lines),
            "dlssg_create_feature_count": sum(line.startswith("WORKER_CREATE_COMPLETE") for line in worker_lines),
            "evaluate_count": sum(line.startswith("WORKER_EVALUATE ") for line in worker_lines),
            "worker_restarts": 0,
            "device_removal_results": sorted({
                line.rsplit("=", 1)[-1] for line in worker_lines if "DEVICE_REMOVED_REASON=" in line
            }),
        }
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
            "unique_interpolated_frames": generated_count,
            "scene_cut_hold_frames": scene_cut_holds,
            "terminal_hold_frames": 1 if terminal_frame_policy == "duplicate" else 0,
            "output_frames": output_count,
            "expected_output_frames": output_frame_count(input_count, terminal_frame_policy == "duplicate"),
            "terminal_policy": duration_policy,
            "audio_preserved": preserve_audio and bool(info["audio"]),
            "input_metadata": info,
            "output_metadata": output_info,
            "color_metadata_preserved": color_metadata_preserved,
            "scene_cuts": scene_cuts,
            "interpolation_disabled_frame_ids": interpolation_disabled_ids,
            "generated": comparisons,
            "generated_unique_hashes": len(set(hashes)),
            "generated_endpoint_duplicates": sum(
                bool(item["identical_previous"] or item["identical_current"]) for item in comparisons
            ),
            "stale_output_suspects": sum(bool(item["stale_suspect"]) for item in comparisons),
            "flow_summary_mean": flow_summary,
            "selected_transition_pairs": [item[1] for item in selected],
            "selected_transition_files": selected_files,
            "contact_sheet": contact_sheet,
            "lifecycle": lifecycle,
            "timings_mean_ms": summary,
            "decode_ms_per_frame": decode_seconds * 1000 / input_count,
            "encode_write_ms_per_output": encode_seconds * 1000 / output_count,
            "end_to_end_fps": output_count / max(time.perf_counter() - started, 1e-9),
            "total_wall_seconds": time.perf_counter() - started,
            "effective_input_fps": input_count / max(time.perf_counter() - started, 1e-9),
            "vram_before_mib": vram_before,
            "vram_peak_mib": peak_vram,
            "worker_diagnostics": str(log_path),
        }
        log_path.write_text("\n".join(worker_lines) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    finally:
        if peak_vram is None:
            vram_sampler.stop()
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
