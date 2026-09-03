import os, json, gradio as gr
from pathlib import Path
from src.core.media_info import probe, format_info
from src.core.config import load_settings, save_settings, load_presets
from src.core.diagnostics import collect
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.backends.dlss_sr import DLSSSRBackend
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
from src.ui.tooltips import RTX_TOOLTIPS, DLSS5_TOOLTIPS, setting_label
from src.ui.preset_controls import delete_dlss, delete_rtx, load_dlss, load_rtx, preset_choices, save_dlss, save_rtx
from src.video.stream import render_vsr
from src.video.dlss5 import render_dlss5

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
CONTROLLER = JobController()
def status_html():
    d = collect()
    rtx = "Ready" if d["rtx_vsr"]["available"] else "Unavailable"
    dlss = "Experimental Ready" if d["dlss5"]["available"] else "Unavailable"
    ffmpeg = "Ready" if d["ffmpeg"] == "AVAILABLE" else "Unavailable"
    return f"<div class=\"app-header\"><h1>NVIDIA Video Enhancer</h1><p>RTX Video Super Resolution + DLSS 5 Neural Rendering</p></div><div class=\"backend-status\"><span class=\"status-badge\">RTX VSR <b>● {rtx}</b></span><span class=\"status-badge\">DLSS 5 <b>● {dlss}</b></span><span class=\"status-badge\">FFmpeg <b>● {ffmpeg}</b></span></div>"

def _tip(mapping, key, label):
    return gr.HTML(setting_label(label, mapping[key]), show_label=False, elem_classes="setting-label")

def _save_last(backend, values):
    try:
        save_last_used(backend, values)
    except Exception:
        pass
def inspect(path):
    if not path: return "<span class=\"muted\">No video selected.</span>", "No video selected."
    try:
        i = probe(path)
        summary = f"<div class=\"media-summary\"><b>{i['width']} × {i['height']}</b><span>{i['fps']:.3g} FPS</span><span>{i['duration']:.2f} sec</span><span>{i['codec']}</span><span>Audio: {i['audio_codec']}</span></div>"
        detail = format_info(i) + ("\n\nWARNING: HDR/high-bit-depth detected; DLSS5 path is SDR RGBA8 only." if i['hdr'] else "")
        return summary, detail
    except Exception as e: return f"<span class=\"error\">Inspection failed: {e}</span>", f"Inspection failed: {e}"
def do_frame(path, timestamp, mode, vsr_mode, scale_value, quality_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, None, "Choose an input video."
    try:
        if mode.startswith("DLSS SR"):
            status = DLSSSRBackend().status()
            return None, None, f"{status.name} {status.state}: {status.reason}"
        available = DLSS5Backend().status().available if mode.startswith("DLSS") else RTXVSRBackend().status().available
        if not available:
            return None, None, f"{mode} unavailable. No substitute processing was performed. Install and audit the genuine runtime first."
        source_frame=TEMP/f"preview_source_{os.getpid()}.png"; preview_frame(path,timestamp,source_frame)
        if mode.startswith("DLSS"):
            _save_last("dlss5", {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On"})
        else:
            _save_last("rtx_vsr", {"mode": vsr_mode, "scale": float(scale_value), "quality": quality_value})
        from PIL import Image
        import numpy as np
        image=np.asarray(Image.open(source_frame).convert("RGB"), dtype=np.uint8); h,w=image.shape[:2]
        if mode.startswith("DLSS"):
            backend = DLSS5Backend()
            options = backend.options(upscaling_mode=dlss_scale, nr_preset=nrpreset, nr_style=style, nr_intensity=float(intensity), local_tone_strength=float(tone), local_structure_strength=float(structure), skin_structure_strength=float(skin), automatic_mask=mask == "On", dlss_model_preset=model, motion_mode="none")
            enhanced = backend.process_frame(image, options=options)[..., :3]
            out=TEMP/f"preview_{os.getpid()}.png"; Image.fromarray(enhanced).save(out)
            return str(source_frame), str(out), f"DLSS5 Feature-18 verified | {dlss_scale}x | {style} | Intensity {float(intensity):.2f} | Output {enhanced.shape[1]}x{enhanced.shape[0]}"
        target=(w,h) if vsr_mode in {"Deblur","Denoise"} else aligned_dimensions(w,h,float(scale_value))
        import torch
        tensor=torch.from_numpy(image.copy()).to("cuda",dtype=torch.float32).div_(255)
        result=RTXVSRBackend().process_frame(tensor,*target,quality_value) if vsr_mode == "Super Resolution" else None
        if result is None:
            backend=RTXVSRBackend(); level=backend.mode_quality(vsr_mode,quality_value)
            with backend.nvvfx.VideoSuperRes(level) as effect:
                effect.output_width,effect.output_height=target; effect.load(); native=effect.run(tensor); result=torch.from_dlpack(native.image).clone(); del native
        enhanced=(result.clamp(0,1).mul(255).byte().cpu().numpy()) if vsr_mode == "Super Resolution" else (result.clamp(0,1).mul(255).byte().permute(1,2,0).cpu().numpy())
        out=TEMP/f"preview_{os.getpid()}.png"; Image.fromarray(enhanced).save(out)
        del result,tensor,image,enhanced
        return str(source_frame), str(out), f"RTX VSR {vsr_mode} preview completed at {target[0]}x{target[1]}."
    except Exception as e: return None, None, str(e)
def apply_preset(name):
    p=load_presets().get(name,{}); return [p.get(k) for k in ["dlss_preset","dlss_style","dlss_intensity","local_tone","local_structure","skin_structure","automatic_mask"]]
def unavailable_action(mode, action):
    status = DLSS5Backend().status() if mode.startswith("DLSS") else RTXVSRBackend().status()
    if not status.available:
        return f"{action} blocked: {status.name} unavailable. {status.reason}"
    return f"{action} is gated until the installed SDK adapter passes its smoke test."
def _dlss_options(backend, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    return backend.options(upscaling_mode=dlss_scale, nr_preset=nrpreset, nr_style=style, nr_intensity=float(intensity), local_tone_strength=float(tone), local_structure_strength=float(structure), skin_structure_strength=float(skin), automatic_mask=mask == "On", dlss_model_preset=model, motion_mode="optical_flow")


def mode_visibility(selected):
    """Return visibility for the selected backend and its settings group."""
    return selected == "RTX VSR only", selected == "DLSS 5 only", selected == "DLSS SR only"


def available_mode_choices():
    choices = [("RTX VSR", "RTX VSR only"), ("DLSS 5", "DLSS 5 only")]
    if DLSSSRBackend().status().available:
        choices.append(("DLSS SR", "DLSS SR only"))
    return choices


def load_last_render():
    path = load_last_successful_render()
    if not path:
        return None, '<span class="muted">No previous render available.</span>', "No previous render available.", None, None, None, "No previous render available.", gr.update(interactive=False)
    summary, detail = inspect(path)
    if detail.startswith("Inspection failed"):
        clear_last_successful_render()
        return None, '<span class="error">Previous render is not a readable video.</span>', detail, None, None, None, "Previous render is not a readable video.", gr.update(interactive=False)
    return path, summary, detail, None, None, None, f"Loaded last successful render: {Path(path).name}", gr.update(interactive=True)

def render_video(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, codec_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, "Choose an input video."
    if processing_mode.startswith("DLSS SR"):
        return None, "DLSS SR unavailable: " + DLSSSRBackend().status().reason
    job = None
    try:
        job = CONTROLLER.start(); MONITOR.set_active(True); destination = output_path(Path(path), processing_mode, container_value, float(dlss_scale))
        _save_last("dlss5" if processing_mode == "DLSS 5 only" else "rtx_vsr", {"mode": vsr_mode, "scale": float(scale_value), "quality": quality_value} if processing_mode != "DLSS 5 only" else {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On"})
        progress = tracker_callback(job.progress)
        if processing_mode == "DLSS 5 only":
            backend = DLSS5Backend(); stats = render_dlss5(path, destination, backend, _dlss_options(backend, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model), codec=codec_value, cancel=job.cancel_event, progress=progress)
        else:
            stats = render_vsr(path, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event, progress=progress)
        MONITOR.set_active(False); CONTROLLER.finish("COMPLETED", f"Completed: {stats['frames']} frames")
        save_last_successful_render(destination)
        return str(destination), f"Completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}; audio preserved: {stats['audio_preserved']}"
    except InterruptedError:
        if job: MONITOR.set_active(False); CONTROLLER.finish("CANCELLED", "Render cancelled")
        return None, "Render cancelled; partial output removed."
    except Exception as exc:
        if job: MONITOR.set_active(False); CONTROLLER.finish("FAILED", str(exc))
        return None, f"Render failed: {exc}"

def preview_clip(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, start_timestamp, duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, "Choose an input video."
    if processing_mode.startswith("DLSS SR"):
        return None, "DLSS SR unavailable: " + DLSSSRBackend().status().reason
    job = None
    try:
        job = CONTROLLER.start(); MONITOR.set_active(True); progress = tracker_callback(job.progress); destination = TEMP / f"preview_clip_{os.getpid()}.{container_value.lower()}"
        _save_last("dlss5" if processing_mode == "DLSS 5 only" else "rtx_vsr", {"mode": vsr_mode, "scale": float(scale_value), "quality": quality_value} if processing_mode != "DLSS 5 only" else {"scale": float(dlss_scale), "nr_preset": nrpreset, "nr_style": style, "model_preset": model, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On"})
        if processing_mode == "DLSS 5 only":
            backend = DLSS5Backend(); stats = render_dlss5(path, destination, backend, _dlss_options(backend, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model), start=float(start_timestamp), duration=float(duration), codec="H.264", cancel=job.cancel_event, progress=progress)
        else:
            clip_source = TEMP / f"preview_input_{os.getpid()}.mp4"
            from src.core.process_utils import run
            result = run(["ffmpeg", "-y", "-v", "error", "-ss", str(float(start_timestamp)), "-t", str(float(duration)), "-i", str(path), "-c", "copy", str(clip_source)])
            if result.returncode: raise RuntimeError(result.stderr[-1000:])
            stats = render_vsr(clip_source, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event, progress=progress)
            clip_source.unlink(missing_ok=True)
        MONITOR.set_active(False); CONTROLLER.finish("COMPLETED", f"Preview completed: {stats['frames']} frames"); return str(destination), f"Preview completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}"
    except InterruptedError:
        if job: MONITOR.set_active(False); CONTROLLER.finish("CANCELLED", "Preview cancelled")
        return None, "Preview cancelled; partial output removed."
    except Exception as exc:
        if job: MONITOR.set_active(False); CONTROLLER.finish("FAILED", str(exc))
        return None, f"Preview failed: {exc}"
def build():
    last = load_last_used()
    rlast = last.get("rtx_vsr", {})
    dlast = last.get("dlss5", {})
    previous_render = load_last_successful_render()
    with gr.Blocks(title="NVIDIA Video Enhancer", analytics_enabled=False) as ui:
        status = gr.HTML(status_html(), elem_classes="status-header")
        gr.HTML('<details class="advanced-diagnostics"><summary>Advanced diagnostics</summary><div>DLSS SR — unsupported by current protocol. The backend remains available for future capability detection.</div></details>')
        metrics = gr.HTML(metrics_html())
        progress_panel = gr.HTML(progress_html(CONTROLLER.snapshot()))
        refresh_timer = gr.Timer(0.5)
        with gr.Row(elem_classes="main-workspace"):
            with gr.Column(scale=25, min_width=280, elem_classes="input-panel"):
                gr.Markdown("## Input")
                inp = gr.Video(label="Upload video", include_audio=True)
                load_render = gr.Button("Load Last Render", interactive=bool(previous_render), elem_classes="load-render")
                summary = gr.HTML('<span class="muted">No video selected.</span>')
                with gr.Accordion("Media details", open=False):
                    info = gr.Textbox(value="No video selected.", show_label=False, lines=5, interactive=False)
                state = gr.State("DLSS 5 only")
            with gr.Column(scale=35, min_width=360, elem_classes="settings-panel"):
                gr.Markdown("## Enhancement")
                mode = gr.Radio(available_mode_choices(), value="DLSS 5 only", show_label=False, elem_id="enhancement-selector", elem_classes="enhancement-selector")
                with gr.Group(visible=False, elem_classes="backend-group") as rtx_group:
                    gr.Markdown("### RTX VSR Settings")
                    _tip(RTX_TOOLTIPS, "mode", "Mode")
                    vsr_mode = gr.Dropdown(["Super Resolution", "High Bitrate", "Deblur", "Denoise"], value=rlast.get("mode", "Super Resolution"), show_label=False)
                    _tip(RTX_TOOLTIPS, "scale", "Scale factor")
                    scale = gr.Dropdown([1.0, 1.5, 2.0, 2.5, 3.0, 4.0], value=rlast.get("scale", 2.0), show_label=False)
                    _tip(RTX_TOOLTIPS, "quality", "Quality")
                    quality = gr.Dropdown(["LOW", "MEDIUM", "HIGH", "ULTRA"], value=rlast.get("quality", "ULTRA"), show_label=False)
                with gr.Group(visible=True, elem_classes="backend-group") as dlss_group:
                    gr.Markdown("### DLSS5 Settings")
                    _tip(DLSS5_TOOLTIPS, "builtin_preset", "Built-in preset")
                    preset = gr.Dropdown(list(load_presets()) + ["Default"], value="Photoreal Balanced", show_label=False)
                    _tip(DLSS5_TOOLTIPS, "scale", "DLSS scale")
                    dlss_scale = gr.Dropdown([1.0, 1.5, 1.724, 2.0, 3.0], value=dlast.get("scale", 1.0), show_label=False)
                    _tip(DLSS5_TOOLTIPS, "nr_preset", "NR preset")
                    nrpreset = gr.Dropdown(["Default", "Preset #1", "Preset #2", "Preset #3"], value=dlast.get("nr_preset", "Default"), show_label=False)
                    _tip(DLSS5_TOOLTIPS, "nr_style", "NR style")
                    style = gr.Dropdown(["Default", "Natural", "Cinematic"], value=dlast.get("nr_style", "Natural"), show_label=False)
                    _tip(DLSS5_TOOLTIPS, "model_preset", "DLSS model preset")
                    model = gr.Dropdown(["Default", "J", "K", "L", "M"], value=dlast.get("model_preset", "Default"), show_label=False)
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
                with gr.Group(visible=False, elem_classes="backend-group") as sr_group:
                    gr.Markdown("### DLSS SR Settings")
                    gr.Markdown("Standalone DLSS SR is not currently available in the approved runtime.")
                with gr.Accordion("Saved settings", open=False):
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
                with gr.Accordion("Output settings", open=False):
                    codec = gr.Dropdown(["H.264", "HEVC"], value="H.264", label="Codec")
                    container = gr.Dropdown(["MP4", "MKV", "MOV"], value="MP4", label="Container")
            with gr.Column(scale=40, min_width=420, elem_classes="preview-panel"):
                gr.Markdown("## Preview / Output")
                with gr.Row(elem_classes="preview-grid"):
                    before = gr.Image(label="Before / source", type="filepath")
                    after = gr.Image(label="After / processed", type="filepath")
                result_video = gr.Video(label="Rendered / preview video")
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
        def visibility(selected):
            rtx_visible, dlss_visible, sr_visible = mode_visibility(selected)
            return gr.update(visible=rtx_visible), gr.update(visible=dlss_visible), gr.update(visible=sr_visible)
        inp.change(inspect, inp, [summary, info])
        load_render.click(load_last_render, outputs=[inp, summary, info, before, after, result_video, job, load_render])
        mode.change(lambda value: value, mode, state)
        mode.change(visibility, mode, [rtx_group, dlss_group, sr_group])
        preset.change(apply_preset, preset, [nrpreset, style, intensity, tone, structure, skin, mask])
        frame.click(do_frame, [inp, timestamp, state, vsr_mode, scale, quality, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model], [before, after, job])
        clip.click(preview_clip, [inp, state, vsr_mode, scale, quality, container, timestamp, preview_duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model], [result_video, job])
        render.click(render_video, [inp, state, vsr_mode, scale, quality, container, codec, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model], [result_video, job])
        stop.click(lambda: (CONTROLLER.cancel() or "Cancellation requested."), None, job)
        refresh_timer.tick(lambda: (metrics_html(), progress_html(CONTROLLER.snapshot())), outputs=[metrics, progress_panel], show_progress="hidden", queue=False)
        rtx_save.click(save_rtx, [rtx_name, vsr_mode, scale, quality], [rtx_saved, rtx_message])
        rtx_load.click(load_rtx, rtx_saved, [vsr_mode, scale, quality, rtx_message])
        rtx_delete.click(delete_rtx, rtx_saved, [rtx_saved, rtx_message])
        rtx_reset.click(lambda: ("Super Resolution", 2.0, "ULTRA", "RTX settings reset."), outputs=[vsr_mode, scale, quality, rtx_message])
        dlss_save.click(save_dlss, [dlss_name, dlss_scale, nrpreset, style, model, intensity, tone, structure, skin, mask], [dlss_saved, dlss_message])
        dlss_load.click(load_dlss, dlss_saved, [dlss_scale, nrpreset, style, model, intensity, tone, structure, skin, mask, dlss_message])
        dlss_delete.click(delete_dlss, dlss_saved, [dlss_saved, dlss_message])
        dlss_reset.click(lambda: (1.0, "Default", "Natural", "Default", .60, .40, .40, .15, "Off", "DLSS5 settings reset."), outputs=[dlss_scale, nrpreset, style, model, intensity, tone, structure, skin, mask, dlss_message])
        gr.Markdown("### Runtime notes\nA missing backend is never substituted with sharpening or another upscaler. Configure legitimate NVIDIA runtimes, then restart and refresh diagnostics.")
    return ui


def launch():
    build().launch(server_name="127.0.0.1", share=False, enable_monitoring=False, css_paths=Path("src/ui/styles.css"))
