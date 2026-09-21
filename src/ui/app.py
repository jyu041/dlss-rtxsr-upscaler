import hashlib, os, json, shutil, subprocess, sys, tempfile, traceback, warnings

# Gradio 6.16 currently references Starlette's deprecated HTTP 422 alias on
# queue joins. It is upstream noise rather than an application failure, so
# suppress only that exact warning instead of hiding deprecations globally.
warnings.filterwarnings(
    "ignore",
    message=r"'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated\. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead\.",
)

import gradio as gr
from html import escape
from pathlib import Path
from src.core.media_info import probe, format_info
from src.core.config import load_settings, save_settings, load_presets
from src.core.diagnostics import collect, runtime_inventory
from src.core.dlssg_readiness import assess, format_summary
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.backends.dlss5_unified import DLSS5UnifiedBackend
from src.backends.dlss5_v10_app import DLSS5V10ExperimentalBackend
from src.backends.dlss_sr import DLSSSRBackend
from src.backends.dlssg import DLSSGBackend, backend_for_nvof_profile
from src.backends.dlssg_worker import NVOF_PROFILE_GRID4_GPU_CANDIDATE, NVOF_PROFILE_VALIDATED
from src.video.ffmpeg import preview_frame
from src.core.paths import TEMP
from src.core.paths import output_path
from src.core.paths import aligned_dimensions
from src.core.jobs import JobController
from src.core.monitoring import MONITOR
from src.core.progress import tracker_callback
from src.core.user_presets import clear_last_successful_render, load_last_successful_render, load_last_used, save_last_successful_render, save_last_used
from src.ui.monitoring import metrics_html
from src.ui.progress_view import progress_html
from src.ui.tooltips import RTX_TOOLTIPS, DLSS5_TOOLTIPS, DLSS_SR_TOOLTIPS, setting_label
from src.ui.preset_controls import delete_dlss, delete_rtx, delete_dlss_sr, load_dlss, load_dlss_sr, load_rtx, preset_choices, save_dlss, save_dlss_sr, save_rtx
from src.video.stream import render_vsr
from src.video.rtx_vsr_worker import RTXVSRSession
from src.video.dlss5 import render_dlss5
from src.video.dlss5_unified import render_dlss5_unified
from src.video.dlss_sr import process_dlss_sr_frame, render_dlss_sr
from src.video.dlssg import ffmpeg_executable, render_dlssg
from src.runtime_manager import RuntimeManager

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
CONTROLLER = JobController()
RUNTIME_MANIFEST = Path(__file__).resolve().parents[1] / "runtime_manager" / "manifest.json"
RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
DEFAULT_DLSSG_PROFILE = "legacy"


def _log_ui_exception(operation: str, exc: BaseException) -> None:
    """Keep the WebUI concise while preserving a complete console traceback."""
    print(f"{operation} failed: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)


def runtime_action(runtime_id: str, action: str, archive_path: str | None = None) -> str:
    """Handle one explicit, user-triggered managed-runtime action."""
    manager = RuntimeManager(RUNTIME_MANIFEST, RUNTIME_ROOT)
    spec = manager.specs[runtime_id]
    if action in {"INSTALL", "UPDATE", "REPAIR"}:
        if spec.policy != "UPSTREAM_DOWNLOAD":
            return f"{action} blocked: {spec.policy} requires user-supplied configuration."
        print(f"Explicit runtime download: {spec.source_url}", flush=True)
        method = "repair" if action in {"UPDATE", "REPAIR"} else "install"
        destination = getattr(manager, method)(runtime_id, target=Path(archive_path) if archive_path else None, progress=lambda done, total: print(f"runtime {done}/{total or '?'}", flush=True))
        return f"{action} complete: {destination}"
    if action == "VERIFY":
        result = manager.verify(runtime_id)
        return f"VERIFY {runtime_id}: {result.get('detail', result)}"
    if action == "REMOVE":
        manager.remove(runtime_id)
        return f"REMOVE complete: {spec.id}"
    if action == "IMPORT":
        if not archive_path:
            return "IMPORT requires a local archive path."
        destination = manager.import_zip(runtime_id, Path(archive_path))
        return f"IMPORT complete: {destination}"
    return f"Unknown runtime action: {action}"


def status_html():
    d = collect()
    rtx_state = d["rtx_vsr"].get("state", "UNAVAILABLE")
    rtx = rtx_state if d["rtx_vsr"]["available"] else "Unavailable"
    try:
        dlss5_status = DLSS5UnifiedBackend().status()
        dlss = dlss5_status.state if dlss5_status.available else "Unavailable"
    except Exception:
        dlss = "Unavailable"
    sr = d["dlss_sr"]["state"]
    fg = "Validated 2X/3X/4X" if d["dlssg"]["available"] else d["dlssg"].get("state", "Unavailable")
    ffmpeg = "Ready" if d["ffmpeg"] == "AVAILABLE" else "Unavailable"
    return (
        '<div class="app-shell-header">'
        '<div class="app-header"><h1>NVIDIA Video Enhancer</h1>'
        '<p>Local RTX video enhancement · upload, configure, preview, render</p></div>'
        '<details class="status-menu">'
        '<summary><span class="status-dot"></span>Backend status</summary>'
        '<div class="backend-status">'
        f'<span class="status-badge">RTX VSR <b>● {rtx}</b></span>'
        f'<span class="status-badge">DLSS SR <b>● {sr}</b></span>'
        f'<span class="status-badge">DLSS 5 <b>● {dlss}</b></span>'
        f'<span class="status-badge">DLSS-G <b>● {fg}</b></span>'
        f'<span class="status-badge">FFmpeg <b>● {ffmpeg}</b></span>'
        '</div></details></div>'
    )


def runtime_cards_markdown() -> str:
    lines = ["### Managed runtime inventory", "| Component | State | Action | Version | Policy |", "|---|---|---|---|---|"]
    for item in runtime_inventory():
        lines.append(
            f"| {item.get('name', item.get('id', 'runtime'))} | {item.get('state', 'INVALID')} | "
            f"{item.get('action', 'REVIEW')} | {item.get('version', 'unknown')} | {item.get('policy', 'unknown')} |"
        )
    lines.append("\n`setup.bat` provisions the normal managed runtime set. Runtime Manager is for inspection, repair, updates, and experimental components.")
    return "\n".join(lines)


def _tip(mapping, key, label):
    return gr.HTML(setting_label(label, mapping[key]), show_label=False, elem_classes="setting-label")


def _save_last(backend, values):
    try:
        save_last_used(backend, values)
    except Exception:
        pass


def save_dlssg_settings(motion_provider, depth_mode, multiplier=2, nvof_profile=NVOF_PROFILE_VALIDATED):
    _save_last(
        "dlssg",
        {
            "motion_provider": motion_provider,
            "depth_mode": depth_mode,
            "multiplier": int(multiplier),
            "nvof_profile": nvof_profile,
        },
    )
    return "DLSS-G settings saved locally. Runtime paths are managed by setup.bat."


def check_dlssg_readiness(nvof_profile=NVOF_PROFILE_VALIDATED):
    if nvof_profile == NVOF_PROFILE_VALIDATED:
        return "```text\n" + format_summary(assess(runtime_profile=DEFAULT_DLSSG_PROFILE)) + "\n```"
    try:
        status = backend_for_nvof_profile(nvof_profile).status()
    except Exception as exc:
        return f"```text\nExperimental grid4 readiness failed: {exc}\n```"
    return (
        "```text\n"
        f"Profile: {nvof_profile}\n"
        f"State: {status.state}\n"
        f"Available: {status.available}\n"
        f"Reason: {status.reason}\n"
        "```"
    )


def validate_dlss_sr():
    backend = DLSSSRBackend()
    try:
        backend.selftest()
        status = backend.status()
        message = f"DLSS SR self-test: {status.state} — {status.reason}"
    except Exception as exc:
        status = backend.status()
        message = f"DLSS SR self-test failed: {exc}. Current state: {status.state} — {status.reason}"
    return status_html(), message, gr.update(choices=available_mode_choices())


def refresh_dlss5_v10_preflight():
    """Install or repair the preferred DLSS 5 runtime."""
    try:
        from tools.provision_dlss5_v10 import prepare_dlss5_v10

        prepare_dlss5_v10()
        status = DLSS5V10ExperimentalBackend().status()
        return status_html(), f"DLSS 5 runtime: {status.state} — {status.reason}"
    except Exception as exc:
        return status_html(), f"DLSS 5 runtime setup failed: {exc}"


def inspect(path):
    if not path: return "<span class=\"muted\">No video selected.</span>", "No video selected."
    try:
        i = probe(path)
        summary = f"<div class=\"media-summary\"><b>{i['width']} × {i['height']}</b><span>{i['fps']:.3g} FPS</span><span>{i['duration']:.2f} sec</span><span>{i['codec']}</span><span>Audio: {i['audio_codec']}</span></div>"
        detail = format_info(i) + ("\n\nWARNING: HDR/high-bit-depth detected; DLSS5 path is SDR RGBA8 only." if i['hdr'] else "")
        return summary, detail
    except Exception as e: return f"<span class=\"error\">Inspection failed: {e}</span>", f"Inspection failed: {e}"


def _browser_display_video(path: str | Path) -> str:
    """Create a full-length browser-playable MP4 without shortening the media.

    H.264/AAC inputs are losslessly remuxed: encoded video/audio packets are
    copied unchanged while malformed metadata/timestamps are normalized and the
    MP4 index is moved to the front for reliable browser playback. Other codecs
    fall back to a full-resolution/full-duration H.264/AAC display copy. The
    original source/render artifact is never replaced.
    """
    source = Path(path).expanduser().resolve()
    stat = source.stat()
    info = probe(source)
    video_codec = str(info.get("codec") or "").strip().lower()
    audio_codec = str(info.get("audio_codec") or "none").strip().lower()
    stream_copy = video_codec in {"h264", "avc1"} and audio_codec in {"aac", "none"}

    identity = (
        f"full-display-v2|{source}|{stat.st_size}|{stat.st_mtime_ns}|"
        f"{video_codec}|{audio_codec}|{int(stream_copy)}"
    ).encode("utf-8", errors="surrogatepass")
    key = hashlib.sha256(identity).hexdigest()[:20]
    root = TEMP / "browser_display"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / key
    destination = directory / "video.mp4"
    if destination.is_file() and destination.stat().st_size > 0:
        return str(destination)

    directory.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_executable(),
        "-y",
        "-v",
        "error",
        "-fflags",
        "+genpts",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
    ]
    if stream_copy:
        command += ["-c:v", "copy"]
        if audio_codec != "none":
            command += ["-c:a", "copy"]
    else:
        command += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
        ]
        if audio_codec != "none":
            command += ["-c:a", "aac", "-b:a", "192k"]
    command += [
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(destination),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    if result.returncode or not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "FFmpeg did not create a display video")[-4000:]
        raise RuntimeError(f"full-length browser video preparation failed: {detail}")

    old = sorted(
        (item for item in root.iterdir() if item.is_dir() and item != directory),
        key=lambda item: item.stat().st_mtime,
    )
    for item in old[:-3]:
        shutil.rmtree(item, ignore_errors=True)
    return str(destination)


def select_source(path):
    """Accept an original source while exposing only one input surface at a time."""
    summary, detail = inspect(path)
    if not path or detail.startswith("Inspection failed"):
        return (
            None,
            gr.update(visible=True),
            gr.update(value=None, visible=False),
            gr.update(visible=False),
            summary,
            detail,
        )
    try:
        preview = _browser_display_video(path)
    except Exception as exc:
        _log_ui_exception("Source video display", exc)
        preview = None
        detail += f"\n\nInput video display unavailable: {exc}"
    return (
        str(Path(path).expanduser().resolve()),
        gr.update(visible=False),
        gr.update(value=preview, visible=bool(preview)),
        gr.update(visible=True),
        summary,
        detail,
    )


def clear_source():
    return (
        None,
        gr.update(value=None, visible=True),
        gr.update(value=None, visible=False),
        gr.update(visible=False),
        '<span class="muted">No video selected.</span>',
        "No video selected.",
        None,
        None,
        None,
        None,
        "Ready. One GPU job at a time.",
    )


def do_frame(path, timestamp, mode, vsr_mode, scale_value, quality_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale=1.0, recompose_backend="auto", shimmer_suppression=0.0, color_strength=1.0, tone_preservation=0.0, v10_nr_passes=1, v10_face_skin_protection=0.0, v10_grain_preservation=0.0, v10_shimmer_suppression=0.70, v10_prefer_nvof="Off", *dlssg_settings):
    if not path: return None, None, "Choose an input video."
    try:
        if mode == "DLSS Frame Generation 2X":
            return None, None, "DLSS-G is temporal interpolation; use Preview Clip or Render Video."
        if mode.startswith("DLSS SR"):
            backend = DLSSSRBackend(); status = backend.status()
            if status.state != "READY":
                return None, None, f"{status.name} {status.state}: {status.reason}"
            source_frame=TEMP/f"preview_source_{os.getpid()}.png"; preview_frame(path,timestamp,source_frame)
            from PIL import Image
            image = Image.open(source_frame).convert("RGBA")
            enhanced = process_dlss_sr_frame(__import__("numpy").asarray(image), backend, sr_mode, sr_model)
            out=TEMP/f"preview_{os.getpid()}.png"; Image.fromarray(enhanced).save(out)
            return str(source_frame), str(out), f"DLSS SR verified | {sr_mode} | Model {sr_model} | {image.width}x{image.height} -> {enhanced.shape[1]}x{enhanced.shape[0]}"
        if mode == "DLSS 5 only":
            legacy_status = DLSS5Backend().status()
            if not legacy_status.available:
                return None, None, (
                    "Single-frame DLSS 5 preview is unavailable because the "
                    "compatibility frame-preview backend is not ready. Use "
                    "Preview Clip or Render Video to exercise the preferred runtime."
                )
        elif not RTXVSRBackend().status().available:
            return None, None, f"{mode} unavailable. No substitute processing was performed. Install and audit the genuine runtime first."
        source_frame=TEMP/f"preview_source_{os.getpid()}.png"; preview_frame(path,timestamp,source_frame)
        if mode.startswith("DLSS"):
            _save_last("dlss5", {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On", "nr_working_scale": nr_working_scale, "recompose_backend": recompose_backend, "shimmer_suppression": float(shimmer_suppression), "color_strength": float(color_strength), "tone_preservation": float(tone_preservation), "v10_nr_passes": int(v10_nr_passes), "v10_face_skin_protection": float(v10_face_skin_protection), "v10_grain_preservation": float(v10_grain_preservation), "v10_shimmer_suppression": float(v10_shimmer_suppression), "v10_prefer_nvof": v10_prefer_nvof == "On"})
        else:
            _save_last("rtx_vsr", {"mode": vsr_mode, "scale": float(scale_value), "quality": quality_value})
        from PIL import Image
        import numpy as np
        image=np.asarray(Image.open(source_frame).convert("RGB"), dtype=np.uint8); h,w=image.shape[:2]
        if mode == "DLSS 5 only":
            # Single-frame preview remains on the validated compatibility path;
            # the preferred v10 runtime is temporal and is exercised by Preview
            # Clip / Render Video.
            backend = DLSS5Backend()
            options = backend.options(upscaling_mode=dlss_scale, nr_preset=nrpreset, nr_style=style, nr_intensity=float(intensity), local_tone_strength=float(tone), local_structure_strength=float(structure), skin_structure_strength=float(skin), automatic_mask=mask == "On", dlss_model_preset=model, motion_mode="none")
            composition = {}
            enhanced = backend.process_frame(image, options=options, nr_working_scale=nr_working_scale, recompose_backend=recompose_backend, telemetry=composition, shimmer_suppression=float(shimmer_suppression), color_strength=float(color_strength), tone_preservation=float(tone_preservation))[..., :3]
            out=TEMP/f"preview_{os.getpid()}.png"; Image.fromarray(enhanced).save(out)
            used = composition.get("recompose_backend_used", "bypassed")
            return str(source_frame), str(out), f"DLSS 5 compatibility frame preview | Recompose {used} | {dlss_scale}x | {style} | Intensity {float(intensity):.2f} | Output {enhanced.shape[1]}x{enhanced.shape[0]}. Preview Clip / Render Video uses the preferred runtime when ready."
        target=(w,h) if vsr_mode in {"Deblur","Denoise"} else aligned_dimensions(w,h,float(scale_value))
        session = RTXVSRSession()
        try:
            session.start(w, h, target[0], target[1], vsr_mode, quality_value)
            enhanced = session.process_frame(0, image)
            session.finish()
        finally:
            session.close()
        out=TEMP/f"preview_{os.getpid()}.png"; Image.fromarray(enhanced).save(out)
        del image,enhanced
        return str(source_frame), str(out), f"RTX VSR {vsr_mode} preview completed at {target[0]}x{target[1]}."
    except Exception as e:
        _log_ui_exception("Frame preview", e)
        return None, None, str(e)


def apply_preset(name):
    p=load_presets().get(name,{}); return [p.get(k) for k in ["dlss_preset","dlss_style","dlss_intensity","local_tone","local_structure","skin_structure","automatic_mask"]]


def unavailable_action(mode, action):
    status = DLSS5UnifiedBackend().status() if mode == "DLSS 5 only" else RTXVSRBackend().status()
    if not status.available:
        return f"{action} blocked: {status.name} unavailable. {status.reason}"
    return f"{action} is gated until the installed SDK adapter passes its smoke test."


def _dlss_options(backend, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    return backend.options(upscaling_mode=dlss_scale, nr_preset=nrpreset, nr_style=style, nr_intensity=float(intensity), local_tone_strength=float(tone), local_structure_strength=float(structure), skin_structure_strength=float(skin), automatic_mask=mask == "On", dlss_model_preset=model, motion_mode="optical_flow")


def mode_visibility(selected):
    """Return visibility for the selected backend and its settings group."""
    return (
        selected == "RTX VSR only",
        selected == "DLSS 5 only",
        selected == "DLSS SR only",
        selected == "DLSS Frame Generation 2X",
    )


def available_mode_choices():
    choices = [
        ("RTX VSR", "RTX VSR only"),
        ("DLSS 5", "DLSS 5 only"),
    ]
    if DLSSSRBackend().status().state == "READY":
        choices.append(("DLSS SR", "DLSS SR only"))
    choices.append(("DLSS Frame Generation (2X)", "DLSS Frame Generation 2X"))
    return choices


def default_mode():
    """Choose a practical first-run backend without requiring user configuration."""
    try:
        if RTXVSRBackend().status().available:
            return "RTX VSR only"
    except Exception:
        pass
    try:
        if DLSSSRBackend().status().state == "READY":
            return "DLSS SR only"
    except Exception:
        pass
    try:
        if DLSSGBackend().status().available:
            return "DLSS Frame Generation 2X"
    except Exception:
        pass
    try:
        if DLSS5UnifiedBackend().status().available:
            return "DLSS 5 only"
    except Exception:
        pass
    return "RTX VSR only"


def load_last_render():
    path = load_last_successful_render()
    if not path:
        return (
            None,
            gr.update(value=None, visible=True),
            gr.update(value=None, visible=False),
            gr.update(visible=False),
            '<span class="muted">No previous render available.</span>',
            "No previous render available.",
            None,
            None,
            None,
            None,
            "No previous render available.",
            gr.update(interactive=False),
        )
    summary, detail = inspect(path)
    if detail.startswith("Inspection failed"):
        clear_last_successful_render()
        return (
            None,
            gr.update(value=None, visible=True),
            gr.update(value=None, visible=False),
            gr.update(visible=False),
            '<span class="error">Previous render is not a readable video.</span>',
            detail,
            None,
            None,
            None,
            None,
            "Previous render is not a readable video.",
            gr.update(interactive=False),
        )
    try:
        preview = _browser_display_video(path)
    except Exception as exc:
        _log_ui_exception("Last render video display", exc)
        preview = None
        detail += f"\n\nVideo display unavailable: {exc}"
    return (
        str(Path(path).resolve()),
        gr.update(value=None, visible=False),
        gr.update(value=preview, visible=bool(preview)),
        gr.update(visible=True),
        summary,
        detail,
        None,
        None,
        None,
        None,
        f"Loaded last successful render: {Path(path).name}",
        gr.update(interactive=True),
    )


def render_video(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, codec_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale=1.0, recompose_backend="auto", shimmer_suppression=0.0, color_strength=1.0, tone_preservation=0.0, v10_nr_passes=1, v10_face_skin_protection=0.0, v10_grain_preservation=0.0, v10_shimmer_suppression=0.70, v10_prefer_nvof="Off", dlssg_motion="NVIDIA Optical Flow", dlssg_depth="Constant 0.5", dlssg_multiplier=2, dlssg_nvof_profile=NVOF_PROFILE_VALIDATED):
    if not path: return None, "Choose an input video."
    job = None
    try:
        job = CONTROLLER.start(); MONITOR.set_active(True); destination = output_path(Path(path), processing_mode, container_value, float(dlss_scale), int(dlssg_multiplier))
        if processing_mode == "DLSS Frame Generation 2X":
            _save_last("dlssg", {"motion_provider": dlssg_motion, "depth_mode": dlssg_depth, "multiplier": int(dlssg_multiplier), "nvof_profile": dlssg_nvof_profile})
            if dlssg_motion != "NVIDIA Optical Flow" or dlssg_depth != "Constant 0.5": raise RuntimeError("Only NVIDIA Optical Flow + Constant 0.5 depth is implemented")
            backend = backend_for_nvof_profile(dlssg_nvof_profile)
        elif processing_mode.startswith("DLSS SR"):
            backend = DLSSSRBackend(); status = backend.status()
            if status.state != "READY": raise RuntimeError(f"DLSS SR {status.state}: {status.reason}")
            save_last_used("dlss_sr", {"mode": sr_mode, "model_preset": sr_model})
        else:
            if processing_mode == "DLSS 5 only":
                _save_last("dlss5", {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On", "nr_working_scale": nr_working_scale, "recompose_backend": recompose_backend, "shimmer_suppression": float(shimmer_suppression), "color_strength": float(color_strength), "tone_preservation": float(tone_preservation), "v10_nr_passes": int(v10_nr_passes), "v10_face_skin_protection": float(v10_face_skin_protection), "v10_grain_preservation": float(v10_grain_preservation), "v10_shimmer_suppression": float(v10_shimmer_suppression), "v10_prefer_nvof": v10_prefer_nvof == "On"})
            else:
                _save_last("rtx_vsr", {"mode": vsr_mode, "scale": float(scale_value), "quality": quality_value})
        progress = tracker_callback(job.progress)
        if processing_mode == "DLSS Frame Generation 2X":
            stats = render_dlssg(path, destination, backend, multiplier=int(dlssg_multiplier), codec={"H.264":"h264_nvenc", "HEVC":"hevc_nvenc"}[codec_value], cancel=job.cancel_event, progress=progress, nvof_profile=dlssg_nvof_profile)
            stats["frames"] = stats["output_frames"]; stats["fps"] = stats["end_to_end_fps"]; stats["dimensions"] = (stats["width"], stats["height"])
        elif processing_mode.startswith("DLSS SR"):
            stats = render_dlss_sr(path, destination, backend, sr_mode, sr_model, codec=codec_value, cancel=job.cancel_event, progress=progress)
        elif processing_mode == "DLSS 5 only":
            backend = DLSS5UnifiedBackend()
            stats = render_dlss5_unified(
                path,
                destination,
                backend,
                output_scale=float(dlss_scale),
                nr_preset=nrpreset,
                style=style,
                model_preset=model,
                intensity=float(intensity),
                local_tone=float(tone),
                local_structure=float(structure),
                skin_structure=float(skin),
                automatic_mask=mask == "On",
                nr_working_scale=nr_working_scale,
                recompose_backend=recompose_backend,
                temporal_stabilization=float(shimmer_suppression),
                color_strength=float(color_strength),
                tone_preservation=float(tone_preservation),
                nr_passes=int(v10_nr_passes),
                face_skin_protection=float(v10_face_skin_protection),
                grain_preservation=float(v10_grain_preservation),
                native_shimmer_suppression=float(v10_shimmer_suppression),
                prefer_nvof=v10_prefer_nvof == "On",
                codec=codec_value,
                cancel=job.cancel_event,
                progress=progress,
            )
        else:
            stats = render_vsr(path, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event, progress=progress, codec=codec_value)
        MONITOR.set_active(False); CONTROLLER.finish("COMPLETED", f"Completed: {stats['frames']} frames")
        save_last_successful_render(destination)
        performance = stats.get("timings_mean_ms", {})
        timing = f"; native median {performance.get('total_process_ms', 0):.1f} ms" if performance else ""
        dlss_runtime = ""
        if "dlss5_runtime" in stats:
            dlss_runtime = (
                "; DLSS 5 compatibility fallback"
                if stats.get("compatibility_fallback")
                else "; DLSS 5 preferred runtime"
            )
        browser_video = None
        display_note = ""
        try:
            browser_video = _browser_display_video(destination)
        except Exception as exc:
            _log_ui_exception("Rendered video display", exc)
            display_note = "; in-app video display unavailable"
        if processing_mode == "DLSS Frame Generation 2X":
            rate_text = (
                f"output {stats['output_fps']:.3f} FPS; "
                f"render throughput {stats['end_to_end_fps']:.2f} output frames/s"
            )
        else:
            rate_text = f"render throughput {stats['fps']:.2f} frames/s"
        return browser_video, f"Completed {stats.get('multiplier', 1)}X: {stats['frames']} frames; {rate_text}; {stats['dimensions'][0]}x{stats['dimensions'][1]}; audio preserved: {stats['audio_preserved']}{timing}{dlss_runtime}{display_note}"
    except InterruptedError:
        if job: MONITOR.set_active(False); CONTROLLER.finish("CANCELLED", "Render cancelled")
        return None, "Render cancelled; partial output removed."
    except Exception as exc:
        _log_ui_exception("Render", exc)
        if job: MONITOR.set_active(False); CONTROLLER.finish("FAILED", str(exc))
        return None, f"Render failed: {exc}"


def _preview_directory() -> Path:
    root = TEMP / "preview"; root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="clip-", dir=root))
    old = sorted((item for item in root.iterdir() if item.is_dir() and item != directory), key=lambda item: item.stat().st_mtime)
    for item in old[:-3]: shutil.rmtree(item, ignore_errors=True)
    return directory


def preview_clip(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, start_timestamp, duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale=1.0, recompose_backend="auto", shimmer_suppression=0.0, color_strength=1.0, tone_preservation=0.0, v10_nr_passes=1, v10_face_skin_protection=0.0, v10_grain_preservation=0.0, v10_shimmer_suppression=0.70, v10_prefer_nvof="Off", dlssg_motion="NVIDIA Optical Flow", dlssg_depth="Constant 0.5", dlssg_multiplier=2, dlssg_nvof_profile=NVOF_PROFILE_VALIDATED):
    if not path: return None, None, "Choose an input video."
    job = None
    clip_source = None
    try:
        job = CONTROLLER.start(); MONITOR.set_active(True); progress = tracker_callback(job.progress); preview_dir = _preview_directory(); destination = preview_dir / "processed.mp4"
        if processing_mode == "DLSS Frame Generation 2X":
            clip_source = preview_dir / "source.mp4"
            result = __import__('subprocess').run([ffmpeg_executable(), "-y", "-v", "error", "-ss", str(float(start_timestamp)), "-t", str(float(duration)), "-i", str(path), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(clip_source)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if result.returncode: raise RuntimeError(result.stderr[-1000:])
            _save_last("dlssg", {"motion_provider": dlssg_motion, "depth_mode": dlssg_depth, "multiplier": int(dlssg_multiplier), "nvof_profile": dlssg_nvof_profile})
            backend = backend_for_nvof_profile(dlssg_nvof_profile)
            stats = render_dlssg(clip_source, destination, backend, multiplier=int(dlssg_multiplier), codec="h264_nvenc", cancel=job.cancel_event, progress=progress, nvof_profile=dlssg_nvof_profile)
            stats["frames"] = stats["output_frames"]; stats["fps"] = stats["output_fps"]; stats["dimensions"] = (stats["width"], stats["height"])
        elif processing_mode.startswith("DLSS SR"):
            backend = DLSSSRBackend(); status = backend.status()
            if status.state != "READY": raise RuntimeError(f"DLSS SR {status.state}: {status.reason}")
            save_last_used("dlss_sr", {"mode": sr_mode, "model_preset": sr_model})
            stats = render_dlss_sr(path, destination, backend, sr_mode, sr_model, start=float(start_timestamp), duration=float(duration), codec="H.264", cancel=job.cancel_event, progress=progress)
        elif processing_mode == "DLSS 5 only":
            _save_last("dlss5", {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On", "nr_working_scale": nr_working_scale, "recompose_backend": recompose_backend, "shimmer_suppression": float(shimmer_suppression), "color_strength": float(color_strength), "tone_preservation": float(tone_preservation), "v10_nr_passes": int(v10_nr_passes), "v10_face_skin_protection": float(v10_face_skin_protection), "v10_grain_preservation": float(v10_grain_preservation), "v10_shimmer_suppression": float(v10_shimmer_suppression), "v10_prefer_nvof": v10_prefer_nvof == "On"})
            backend = DLSS5UnifiedBackend()
            stats = render_dlss5_unified(
                path,
                destination,
                backend,
                output_scale=float(dlss_scale),
                nr_preset=nrpreset,
                style=style,
                model_preset=model,
                intensity=float(intensity),
                local_tone=float(tone),
                local_structure=float(structure),
                skin_structure=float(skin),
                automatic_mask=mask == "On",
                nr_working_scale=nr_working_scale,
                recompose_backend=recompose_backend,
                temporal_stabilization=float(shimmer_suppression),
                color_strength=float(color_strength),
                tone_preservation=float(tone_preservation),
                nr_passes=int(v10_nr_passes),
                face_skin_protection=float(v10_face_skin_protection),
                grain_preservation=float(v10_grain_preservation),
                native_shimmer_suppression=float(v10_shimmer_suppression),
                prefer_nvof=v10_prefer_nvof == "On",
                start=float(start_timestamp),
                duration=float(duration),
                codec="H.264",
                cancel=job.cancel_event,
                progress=progress,
            )
        else:
            clip_source = TEMP / f"preview_input_{os.getpid()}.mp4"
            from src.core.process_utils import run
            result = run(["ffmpeg", "-y", "-v", "error", "-ss", str(float(start_timestamp)), "-t", str(float(duration)), "-i", str(path), "-c", "copy", str(clip_source)])
            if result.returncode: raise RuntimeError(result.stderr[-1000:])
            stats = render_vsr(clip_source, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event, progress=progress)
        MONITOR.set_active(False); CONTROLLER.finish("COMPLETED", f"Preview completed: {stats['frames']} frames")
        if processing_mode == "DLSS Frame Generation 2X":
            before_playback = _browser_display_video(clip_source)
            after_playback = _browser_display_video(destination)
            return before_playback, after_playback, f"Preview {stats['multiplier']}X: source {probe(clip_source)['fps']:.3f} FPS → output {stats['output_fps']:.3f} FPS; {stats['generated_frames']} generated frames; {stats['total_wall_seconds']:.2f}s"
        runtime_note = ""
        if "dlss5_runtime" in stats:
            runtime_note = (
                "; compatibility fallback"
                if stats.get("compatibility_fallback")
                else "; preferred runtime"
            )
        return None, _browser_display_video(destination), f"Preview completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}{runtime_note}"
    except InterruptedError:
        if job: MONITOR.set_active(False); CONTROLLER.finish("CANCELLED", "Preview cancelled")
        return None, None, "Preview cancelled; partial output removed."
    except Exception as exc:
        _log_ui_exception("Clip preview", exc)
        if job: MONITOR.set_active(False); CONTROLLER.finish("FAILED", str(exc))
        return None, None, f"Preview failed: {exc}"


def build():
    last = load_last_used()
    rlast = last.get("rtx_vsr", {})
    dlast = last.get("dlss5", {})
    dlss_default_scale = 1.0
    srlast = last.get("dlss_sr", {})
    dlssglast = last.get("dlssg", {})
    dlssg_multiplier_default = dlssglast.get("multiplier", 2)
    if dlssg_multiplier_default not in {2, 3, 4}: dlssg_multiplier_default = 2
    dlssg_nvof_default = dlssglast.get("nvof_profile", NVOF_PROFILE_VALIDATED)
    if dlssg_nvof_default not in {NVOF_PROFILE_VALIDATED, NVOF_PROFILE_GRID4_GPU_CANDIDATE}:
        dlssg_nvof_default = NVOF_PROFILE_VALIDATED
    previous_render = load_last_successful_render()
    sr_initial_status = DLSSSRBackend().status()
    sr_validation_enabled = sr_initial_status.state in {"SELFTEST REQUIRED", "READY"}
    initial_mode = default_mode()
    rtx_initial, dlss_initial, sr_initial, dlssg_initial = mode_visibility(initial_mode)
    with gr.Blocks(title="NVIDIA Video Enhancer", analytics_enabled=False) as ui:
        status = gr.HTML(status_html(), elem_classes="status-header")
        refresh_timer = gr.Timer(0.5)
        with gr.Tabs(elem_id="app-tabs"):
            with gr.Tab("Enhance"):
                with gr.Row(elem_classes="main-workspace"):
                    with gr.Column(scale=25, min_width=280, elem_classes=["workspace-card", "input-panel"]):
                        gr.Markdown("## Input")
                        source_state = gr.State(None)
                        with gr.Column(elem_classes="source-input-shell"):
                            inp = gr.File(
                                label="Choose video",
                                file_types=["video"],
                                type="filepath",
                            )
                            source_preview = gr.Video(
                                label="Input video",
                                format="mp4",
                                interactive=False,
                                include_audio=True,
                                visible=False,
                            )
                            replace_input = gr.Button("Choose a different video", visible=False, elem_classes="replace-input")
                        load_render = gr.Button("Load Last Render", interactive=bool(previous_render), elem_classes="load-render")
                        summary = gr.HTML('<span class="muted">No video selected.</span>')
                        with gr.Accordion("Media details", open=False):
                            info = gr.Textbox(value="No video selected.", show_label=False, lines=5, interactive=False)
                        state = gr.State(initial_mode)
                    with gr.Column(scale=35, min_width=360, elem_classes=["workspace-card", "settings-panel"]):
                        gr.Markdown("## Enhancement")
                        mode = gr.Radio(available_mode_choices(), value=initial_mode, show_label=False, elem_id="enhancement-selector", elem_classes="enhancement-selector")
                        with gr.Column(visible=rtx_initial, elem_classes=["backend-panel", "backend-rtx"]) as rtx_group:
                            gr.Markdown("### RTX VSR Settings")
                            _tip(RTX_TOOLTIPS, "mode", "Mode")
                            vsr_mode = gr.Dropdown(["Super Resolution", "High Bitrate", "Deblur", "Denoise"], value=rlast.get("mode", "Super Resolution"), show_label=False)
                            _tip(RTX_TOOLTIPS, "scale", "Scale factor")
                            scale = gr.Dropdown([1.0, 1.5, 2.0, 2.5, 3.0, 4.0], value=rlast.get("scale", 2.0), show_label=False)
                            _tip(RTX_TOOLTIPS, "quality", "Quality")
                            quality = gr.Dropdown(["LOW", "MEDIUM", "HIGH", "ULTRA"], value=rlast.get("quality", "ULTRA"), show_label=False)
                        with gr.Column(visible=dlss_initial, elem_classes=["backend-panel", "backend-dlss"]) as dlss_group:
                            gr.Markdown("### DLSS 5 Settings")
                            gr.Markdown("Preset and neural working resolution are the normal controls. Detailed tuning stays collapsed unless you need it.", elem_classes="compact-note")
                            _tip(DLSS5_TOOLTIPS, "builtin_preset", "Built-in preset")
                            preset = gr.Dropdown(list(load_presets()) + ["Default"], value="Photoreal Balanced", show_label=False)
                            dlss_scale = gr.State(dlss_default_scale)
                            _tip(DLSS5_TOOLTIPS, "working_scale", "NR Working Resolution")
                            nr_working_scale = gr.Dropdown([("Auto (target ~720p neural workload)", "auto"), ("100% (Native)", 1.0), ("87.5%", 0.875), ("75%", 0.75), ("67% (2/3)", 2.0 / 3.0), ("50%", 0.5)], value=dlast.get("nr_working_scale", 1.0), show_label=False)

                            nrpreset = gr.State(dlast.get("nr_preset", "Default"))
                            model = gr.State(dlast.get("model_preset", "Default"))
                            with gr.Accordion("Quality tuning", open=False, elem_classes="compact-settings"):
                                _tip(DLSS5_TOOLTIPS, "nr_style", "NR style")
                                style = gr.Dropdown(["Default", "Natural", "Cinematic"], value=dlast.get("nr_style", "Natural"), show_label=False)
                                _tip(DLSS5_TOOLTIPS, "intensity", "NR intensity")
                                intensity = gr.Slider(0, 2, dlast.get("intensity", .60), .05, show_label=False)
                                _tip(DLSS5_TOOLTIPS, "tone", "Local tone strength")
                                tone = gr.Slider(0, 2, dlast.get("local_tone", .40), .05, show_label=False)
                                _tip(DLSS5_TOOLTIPS, "structure", "Local structure strength")
                                structure = gr.Slider(0, 2, dlast.get("local_structure", .40), .05, show_label=False)
                                _tip(DLSS5_TOOLTIPS, "skin", "Skin structure strength")
                                skin = gr.Slider(-1, 2, dlast.get("skin_structure", .15), .05, show_label=False)
                                _tip(DLSS5_TOOLTIPS, "mask", "Automatic mask")
                                mask = gr.Dropdown(["Off", "On"], value="On" if dlast.get("automatic_mask", False) else "Off", show_label=False)
                                shimmer_suppression = gr.Slider(0, 1, dlast.get("shimmer_suppression", 0.0), .05, label="Temporal residual stabilization")
                                color_strength = gr.Slider(0, 1, dlast.get("color_strength", 1.0), .05, label="Neural color strength")
                                tone_preservation = gr.Slider(0, 1, dlast.get("tone_preservation", 0.0), .05, label="Tone preservation")

                            with gr.Accordion("Advanced runtime / neural controls", open=False, elem_classes="compact-settings"):
                                _tip(DLSS5_TOOLTIPS, "recompose", "Recomposition")
                                recompose_backend = gr.Dropdown([("Auto (CUDA preferred)", "auto"), ("CUDA", "cuda"), ("CPU", "cpu")], value=dlast.get("recompose_backend", "auto"), show_label=False)
                                v10_nr_passes = gr.Dropdown([1, 2, 3, 4], value=dlast.get("v10_nr_passes", 1), label="NR passes")
                                v10_face_skin_protection = gr.Slider(0, 1, dlast.get("v10_face_skin_protection", 0.0), .05, label="Face / skin protection")
                                v10_grain_preservation = gr.Slider(0, 1, dlast.get("v10_grain_preservation", 0.0), .05, label="Grain preservation")
                                v10_shimmer_suppression = gr.Slider(0, 1, dlast.get("v10_shimmer_suppression", 0.70), .05, label="Native shimmer suppression")
                                v10_prefer_nvof = gr.Dropdown(["Off", "On"], value="On" if dlast.get("v10_prefer_nvof", False) else "Off", label="Prefer NVIDIA Optical Flow")
                        with gr.Column(visible=sr_initial, elem_classes=["backend-panel", "backend-sr"]) as sr_group:
                            gr.Markdown("### DLSS SR Settings")
                            _tip(DLSS_SR_TOOLTIPS, "mode", "Mode")
                            sr_mode = gr.Dropdown(["DLAA", "Quality", "Balanced", "Performance", "Ultra Performance"], value=srlast.get("mode", "Quality"), show_label=False)
                            _tip(DLSS_SR_TOOLTIPS, "model_preset", "Model preset")
                            sr_model = gr.Dropdown(["Default", "J", "K", "L", "M"], value=srlast.get("model_preset", "Default"), show_label=False)
                        with gr.Column(visible=dlssg_initial, elem_classes=["backend-panel", "backend-dlssg"]) as dlssg_group:
                            gr.Markdown("### DLSS Frame Generation")
                            gr.Markdown("`setup.bat` installs the pinned C55 worker, validated SM86 direct-host runtime, and official NVIDIA DLSS-G provider into managed project folders. Normal use does not require downloading DLLs or entering runtime paths.")
                            dlssg_multiplier = gr.Dropdown([("2X Frame Generation", 2), ("3X Multi Frame Generation", 3), ("4X Multi Frame Generation", 4)], value=dlssg_multiplier_default, label="Frame multiplier")
                            dlssg_nvof_profile = gr.Dropdown(
                                [
                                    ("Validated grid1 / pinned C55", NVOF_PROFILE_VALIDATED),
                                    ("Experimental grid4 / GPU-resident NVOF", NVOF_PROFILE_GRID4_GPU_CANDIDATE),
                                ],
                                value=dlssg_nvof_default,
                                label="NVOF profile",
                            )
                            gr.Markdown("Grid4 is the hardware-tested performance candidate; the pinned grid1 profile remains the default.", elem_classes="compact-note")
                            with gr.Accordion("Runtime / advanced", open=False, elem_classes="compact-settings"):
                                with gr.Row():
                                    dlssg_check = gr.Button("Check DLSS-G readiness")
                                dlssg_readiness = gr.Markdown("Managed runtime readiness has not been refreshed.")
                                dlssg_motion = gr.Dropdown(["NVIDIA Optical Flow"], value=dlssglast.get("motion_provider", "NVIDIA Optical Flow"), label="Motion provider")
                                dlssg_depth = gr.Dropdown(["Constant 0.5"], value=dlssglast.get("depth_mode", "Constant 0.5"), label="Depth mode")
                                dlssg_saved = gr.Markdown()
                                gr.Markdown("Constant depth is a first-generation quality limitation; it is not renderer-quality depth.")
                                gr.Markdown("2X Frame Generation, 3X Multi Frame Generation, and 4X Multi Frame Generation are hardware-validated on the tested RTX 3070 Ti configuration.")
                        with gr.Accordion("Output settings", open=False):
                            codec = gr.Dropdown(["H.264", "HEVC"], value="H.264", label="Codec")
                            container = gr.Dropdown(["MP4", "MKV", "MOV"], value="MP4", label="Container")
                    with gr.Column(scale=40, min_width=420, elem_classes=["workspace-card", "preview-panel"]):
                        progress_panel = gr.HTML(
                            progress_html(CONTROLLER.snapshot()),
                            elem_classes=["workspace-progress", "preview-progress"],
                        )
                        gr.Markdown("## Preview / Output")
                        with gr.Tabs(selected="video", elem_classes="preview-tabs") as preview_tabs:
                            with gr.Tab("Video", id="video"):
                                with gr.Row(elem_classes="preview-grid"):
                                    before_clip = gr.Video(label="Before / source clip", format="mp4")
                                    result_video = gr.Video(label="After / processed video", format="mp4")
                            with gr.Tab("Frame", id="frame"):
                                with gr.Row(elem_classes="preview-grid"):
                                    before = gr.Image(label="Before / source", type="filepath")
                                    after = gr.Image(label="After / processed", type="filepath")
                        gr.Markdown("### Preview / Render")
                        with gr.Row(elem_classes="preview-options"):
                            timestamp = gr.Number(0, label="Timestamp (sec)")
                            preview_duration = gr.Slider(1, 10, 3, step=1, label="Duration (sec)")
                        with gr.Row(elem_classes="action-bar"):
                            frame = gr.Button("Preview Frame")
                            clip = gr.Button("Preview Clip")
                        render = gr.Button("Render Video", variant="primary", elem_classes="render-button")
                        stop = gr.Button("Cancel", interactive=False, elem_classes="cancel-button")
                        job = gr.Markdown("Ready. One GPU job at a time.")

            with gr.Tab("Configuration"):
                gr.Markdown("## Configuration")
                gr.Markdown("Validation, runtime maintenance, and reusable presets. Normal video work stays in Enhance.")

                gr.Markdown("### Backend validation")
                with gr.Row(elem_classes="validation-grid"):
                    with gr.Group(elem_classes="backend-readiness"):
                        gr.Markdown("### DLSS SR readiness")
                        sr_readiness = gr.Markdown(f"Current state: {sr_initial_status.state} — {sr_initial_status.reason}")
                        sr_validate = gr.Button("Validate DLSS SR", interactive=sr_validation_enabled)
                    v10_initial_status = DLSS5V10ExperimentalBackend().status()
                    with gr.Group(elem_classes="backend-readiness-v10"):
                        gr.Markdown("### DLSS 5 runtime")
                        v10_readiness = gr.Markdown(f"Current state: {v10_initial_status.state} — {v10_initial_status.reason}")
                        v10_refresh = gr.Button("Install / Repair DLSS 5")
                gr.Markdown("Normal runtime paths are provisioned by `setup.bat`. Missing backends are never silently substituted.", elem_classes="configuration-note")

                with gr.Group(elem_classes="configuration-card"):
                    gr.Markdown("### Runtime Manager")
                    gr.Markdown("Inspect or repair a managed component. The full inventory is collapsed by default because normal use should not require runtime administration.")
                    runtime_ids = gr.Dropdown(choices=sorted(RuntimeManager(RUNTIME_MANIFEST, RUNTIME_ROOT).specs), label="Managed component")
                    with gr.Row():
                        runtime_action_choice = gr.Dropdown(["INSTALL", "UPDATE", "VERIFY", "REPAIR", "REMOVE", "IMPORT"], value="VERIFY", label="Action")
                        runtime_archive = gr.Textbox(label="Local archive path", placeholder="Only needed for Import or archive-based repair")
                    runtime_action_button = gr.Button("Run runtime action")
                    runtime_action_result = gr.Markdown("No runtime action has been requested.", elem_classes="runtime-result")
                    with gr.Accordion("Managed component inventory", open=False):
                        runtime_cards = gr.Markdown(runtime_cards_markdown())
                        runtime_refresh = gr.Button("Refresh inventory")

                with gr.Accordion("Saved presets", open=False):
                    rtx_saved = gr.Dropdown(preset_choices("rtx_vsr"), label="RTX VSR saved preset")
                    rtx_name = gr.Textbox(label="Preset name", max_length=80)
                    with gr.Row():
                        rtx_load = gr.Button("Load"); rtx_save = gr.Button("Save"); rtx_delete = gr.Button("Delete"); rtx_reset = gr.Button("Reset")
                    rtx_message = gr.Markdown()
                    dlss_saved = gr.Dropdown(preset_choices("dlss5"), label="DLSS5 saved preset")
                    dlss_name = gr.Textbox(label="Preset name", max_length=80)
                    with gr.Row():
                        dlss_load = gr.Button("Load"); dlss_save = gr.Button("Save"); dlss_delete = gr.Button("Delete"); dlss_reset = gr.Button("Reset")
                    dlss_message = gr.Markdown()
                    sr_saved = gr.Dropdown(preset_choices("dlss_sr"), label="DLSS SR saved preset")
                    sr_name = gr.Textbox(label="Preset name", max_length=80)
                    with gr.Row():
                        sr_load = gr.Button("Load"); sr_save = gr.Button("Save"); sr_delete = gr.Button("Delete"); sr_reset = gr.Button("Reset")
                    sr_message = gr.Markdown()

            with gr.Tab("Diagnostics"):
                with gr.Column(elem_classes="diagnostics-shell"):
                    gr.Markdown("## Diagnostics")
                    gr.Markdown("Live local hardware telemetry. These values update while the application is open.")
                    metrics = gr.HTML(metrics_html(), elem_classes="diagnostics-metrics")
                    gr.HTML('<details class="advanced-diagnostics"><summary>Backend implementation notes</summary><div>DLSS SR uses a separate native D3D12 NGX host with optical-flow motion guidance. Video mode is SDR, has no renderer depth or jitter, and requires the approved local NVIDIA runtime.</div></details>')
        def visibility(selected):
            rtx_visible, dlss_visible, sr_visible, dlssg_visible = mode_visibility(selected)
            return gr.update(visible=rtx_visible), gr.update(visible=dlss_visible), gr.update(visible=sr_visible), gr.update(visible=dlssg_visible)
        inp.upload(
            select_source,
            inp,
            [source_state, inp, source_preview, replace_input, summary, info],
            show_progress="full",
        )
        replace_input.click(
            clear_source,
            outputs=[source_state, inp, source_preview, replace_input, summary, info, before, after, before_clip, result_video, job],
            show_progress="hidden",
        )
        load_render.click(
            load_last_render,
            outputs=[source_state, inp, source_preview, replace_input, summary, info, before, after, before_clip, result_video, job, load_render],
        )
        mode.change(lambda value: value, mode, state)
        mode.change(visibility, mode, [rtx_group, dlss_group, sr_group, dlssg_group])
        preset.change(apply_preset, preset, [nrpreset, style, intensity, tone, structure, skin, mask])
        dlssg_inputs = [dlssg_motion, dlssg_depth, dlssg_multiplier, dlssg_nvof_profile]
        for control in dlssg_inputs:
            control.change(save_dlssg_settings, dlssg_inputs, dlssg_saved, show_progress="hidden")
        dlssg_check.click(check_dlssg_readiness, inputs=dlssg_nvof_profile, outputs=dlssg_readiness, show_progress="hidden")
        sr_validate.click(validate_dlss_sr, outputs=[status, sr_readiness, mode], show_progress="full")
        v10_refresh.click(refresh_dlss5_v10_preflight, outputs=[status, v10_readiness], show_progress="full")
        runtime_refresh.click(runtime_cards_markdown, outputs=runtime_cards, show_progress="hidden")
        runtime_action_button.click(runtime_action, [runtime_ids, runtime_action_choice, runtime_archive], runtime_action_result, show_progress="full")
        frame_event = frame.click(do_frame, [source_state, timestamp, state, vsr_mode, scale, quality, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale, recompose_backend, shimmer_suppression, color_strength, tone_preservation, v10_nr_passes, v10_face_skin_protection, v10_grain_preservation, v10_shimmer_suppression, v10_prefer_nvof, *dlssg_inputs], [before, after, job])
        frame_event.then(lambda: gr.Tabs(selected="frame"), outputs=preview_tabs, show_progress="hidden")
        clip_event = clip.click(preview_clip, [source_state, state, vsr_mode, scale, quality, container, timestamp, preview_duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale, recompose_backend, shimmer_suppression, color_strength, tone_preservation, v10_nr_passes, v10_face_skin_protection, v10_grain_preservation, v10_shimmer_suppression, v10_prefer_nvof, *dlssg_inputs], [before_clip, result_video, job])
        clip_event.then(lambda: gr.Tabs(selected="video"), outputs=preview_tabs, show_progress="hidden")
        render_event = render.click(render_video, [source_state, state, vsr_mode, scale, quality, container, codec, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model, sr_mode, sr_model, nr_working_scale, recompose_backend, shimmer_suppression, color_strength, tone_preservation, v10_nr_passes, v10_face_skin_protection, v10_grain_preservation, v10_shimmer_suppression, v10_prefer_nvof, *dlssg_inputs], [result_video, job])
        render_event.then(lambda: gr.Tabs(selected="video"), outputs=preview_tabs, show_progress="hidden")
        stop.click(lambda: (CONTROLLER.cancel() or "Cancellation requested."), None, job)
        refresh_timer.tick(lambda: (metrics_html(), progress_html(CONTROLLER.snapshot())), outputs=[metrics, progress_panel], show_progress="hidden", queue=False)
        rtx_save.click(save_rtx, [rtx_name, vsr_mode, scale, quality], [rtx_saved, rtx_message])
        rtx_load.click(load_rtx, rtx_saved, [vsr_mode, scale, quality, rtx_message])
        rtx_delete.click(delete_rtx, rtx_saved, [rtx_saved, rtx_message])
        rtx_reset.click(lambda: ("Super Resolution", 2.0, "ULTRA", "RTX settings reset."), outputs=[vsr_mode, scale, quality, rtx_message])
        dlss_preset_controls = [
            dlss_scale, nrpreset, style, model, intensity, tone, structure, skin,
            mask, nr_working_scale, recompose_backend, shimmer_suppression,
            color_strength, tone_preservation, v10_nr_passes,
            v10_face_skin_protection, v10_grain_preservation,
            v10_shimmer_suppression, v10_prefer_nvof,
        ]
        dlss_save.click(save_dlss, [dlss_name, *dlss_preset_controls], [dlss_saved, dlss_message])
        dlss_load.click(load_dlss, dlss_saved, [*dlss_preset_controls, dlss_message])
        dlss_delete.click(delete_dlss, dlss_saved, [dlss_saved, dlss_message])
        dlss_reset.click(
            lambda: (
                1.0, "Default", "Natural", "Default", .60, .40, .40, .15, "Off",
                1.0, "auto", 0.0, 1.0, 0.0, 1, 0.0, 0.0, .70, "Off",
                "DLSS5 settings reset.",
            ),
            outputs=[*dlss_preset_controls, dlss_message],
        )
        sr_save.click(save_dlss_sr, [sr_name, sr_mode, sr_model], [sr_saved, sr_message])
        sr_load.click(load_dlss_sr, sr_saved, [sr_mode, sr_model, sr_message])
        sr_delete.click(delete_dlss_sr, sr_saved, [sr_saved, sr_message])
        sr_reset.click(lambda: ("Quality", "Default", "DLSS SR settings reset."), outputs=[sr_mode, sr_model, sr_message])
    return ui


def launch():
    build().launch(server_name="127.0.0.1", share=False, enable_monitoring=False, css_paths=Path("src/ui/styles.css"))
