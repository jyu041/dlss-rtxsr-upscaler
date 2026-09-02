import os, json, gradio as gr
from pathlib import Path
from src.core.media_info import probe, format_info
from src.core.config import load_settings, save_settings, load_presets
from src.core.diagnostics import collect
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.video.ffmpeg import preview_frame
from src.core.paths import TEMP
from src.core.paths import output_path
from src.core.paths import aligned_dimensions
from src.core.jobs import JobController
from src.video.stream import render_vsr
from src.video.dlss5 import render_dlss5

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
CONTROLLER = JobController()
def status_html():
    d=collect(); return " | ".join(f"<b>{k.replace('_',' ').upper()}</b>: {v['state'] if isinstance(v,dict) else v}" for k,v in [("RTX VSR",d['rtx_vsr']),("DLSS5",d['dlss5']),("FFmpeg",d['ffmpeg'])])
def inspect(path):
    if not path: return "No video selected.", None
    try: i=probe(path); return format_info(i) + ("\n\nWARNING: HDR/high-bit-depth detected; DLSS5 path is SDR RGBA8 only." if i['hdr'] else ""), i
    except Exception as e: return f"Inspection failed: {e}", None
def do_frame(path, timestamp, mode, vsr_mode, scale_value, quality_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, None, "Choose an input video."
    try:
        available = DLSS5Backend().status().available if mode.startswith("DLSS") else RTXVSRBackend().status().available
        if not available:
            return None, None, f"{mode} unavailable. No substitute processing was performed. Install and audit the genuine runtime first."
        source_frame=TEMP/f"preview_source_{os.getpid()}.png"; preview_frame(path,timestamp,source_frame)
        from PIL import Image
        import numpy as np
        image=np.asarray(Image.open(source_frame).convert("RGB"), dtype=np.uint8); h,w=image.shape[:2]
        if mode.startswith("DLSS"):
            backend = DLSS5Backend()
            options = backend.options(upscaling_mode=dlss_scale, nr_preset=nrpreset, nr_style=style, nr_intensity=float(intensity), local_tone_strength=float(tone), local_structure_strength=float(structure), skin_structure_strength=float(skin), automatic_mask=mask == "On", dlss_model_preset=model, motion_mode="none")
            enhanced = backend.process_frame(image, options=options)[..., :3]
            if mode == "DLSS 5 → RTX VSR":
                target = aligned_dimensions(enhanced.shape[1], enhanced.shape[0], float(scale_value))
                import torch
                tensor=torch.from_numpy(enhanced.copy()).to("cuda",dtype=torch.float32).div_(255).permute(2,0,1).contiguous()
                enhanced=(RTXVSRBackend().process_frame(tensor,*target,quality_value).clamp(0,1).mul(255).byte().permute(1,2,0).cpu().numpy())
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

def render_video(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, codec_value, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, "Choose an input video."
    if processing_mode == "DLSS 5 → RTX VSR": return None, "Combined full-video mode is deferred until a lossless in-memory bridge is implemented."
    try:
        job = CONTROLLER.start(); destination = output_path(Path(path), processing_mode, container_value, float(dlss_scale))
        if processing_mode == "DLSS 5 only":
            backend = DLSS5Backend(); stats = render_dlss5(path, destination, backend, _dlss_options(backend, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model), codec=codec_value, cancel=job.cancel_event)
        else:
            stats = render_vsr(path, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event)
        CONTROLLER.finish(); return str(destination), f"Completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}; audio preserved: {stats['audio_preserved']}"
    except InterruptedError: CONTROLLER.finish(); return None, "Render cancelled; partial output removed."
    except Exception as exc: CONTROLLER.finish(); return None, f"Render failed: {exc}"

def preview_clip(path, processing_mode, vsr_mode, scale_value, quality_value, container_value, start_timestamp, duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model):
    if not path: return None, "Choose an input video."
    if processing_mode == "DLSS 5 → RTX VSR": return None, "Combined preview mode is deferred until a lossless bridge is implemented."
    try:
        job = CONTROLLER.start(); destination = TEMP / f"preview_clip_{os.getpid()}.{container_value.lower()}"
        if processing_mode == "DLSS 5 only":
            stats = render_dlss5(path, destination, DLSS5Backend(), _dlss_options(DLSS5Backend(), dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model), start=float(start_timestamp), duration=float(duration), codec="H.264", cancel=job.cancel_event)
        else:
            clip_source = TEMP / f"preview_input_{os.getpid()}.mp4"
            from src.core.process_utils import run
            result = run(["ffmpeg", "-y", "-v", "error", "-ss", str(float(start_timestamp)), "-t", str(float(duration)), "-i", str(path), "-c", "copy", str(clip_source)])
            if result.returncode: raise RuntimeError(result.stderr[-1000:])
            stats = render_vsr(clip_source, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event)
            clip_source.unlink(missing_ok=True)
        CONTROLLER.finish(); return str(destination), f"Preview completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}"
    except InterruptedError: CONTROLLER.finish(); return None, "Preview cancelled; partial output removed."
    except Exception as exc: CONTROLLER.finish(); return None, f"Preview failed: {exc}"
def build():
    with gr.Blocks(title="NVIDIA Video Enhancer", analytics_enabled=False) as ui:
        gr.Markdown("# NVIDIA Video Enhancer\n**RTX Video Super Resolution + DLSS 5 Neural Rendering**")
        status = gr.HTML(status_html())
        with gr.Row():
            with gr.Column(scale=1):
                inp = gr.Video(label="Input video")
                info = gr.Textbox(label="Media inspection", lines=5, interactive=False)
                state = gr.State()
                mode = gr.Radio(["RTX VSR only", "DLSS 5 only", "DLSS 5 → RTX VSR"], value="DLSS 5 only", label="Processing order")
            with gr.Column(scale=1):
                with gr.Tab("RTX Super Resolution"):
                    vsr_mode = gr.Dropdown(["Super Resolution", "High Bitrate", "Deblur", "Denoise"], value="Super Resolution", label="Mode")
                    scale = gr.Dropdown([1.0, 1.5, 2.0, 2.5, 3.0, 4.0], value=2.0, label="Scale factor")
                    quality = gr.Dropdown(["LOW", "MEDIUM", "HIGH", "ULTRA"], value="ULTRA", label="Quality")
                with gr.Tab("DLSS 5"):
                    preset = gr.Dropdown(list(load_presets()) + ["Default"], value="Photoreal Balanced", label="User preset")
                    dlss_scale = gr.Dropdown([1.0, 1.5, 1.724, 2.0, 3.0], value=1.0, label="DLSS scale")
                    nrpreset = gr.Dropdown(["Default", "Preset #1", "Preset #2", "Preset #3"], value="Default", label="NR preset")
                    style = gr.Dropdown(["Default", "Natural", "Cinematic"], value="Natural", label="NR style")
                    model = gr.Dropdown(["Default", "J", "K", "L", "M"], value="Default", label="DLSS model preset")
                    intensity = gr.Slider(0, 2, .60, .05, label="NR intensity")
                    tone = gr.Slider(0, 2, .40, .05, label="Local tone strength")
                    structure = gr.Slider(0, 2, .40, .05, label="Local structure strength")
                    skin = gr.Slider(-1, 2, .15, .05, label="Skin structure strength")
                    mask = gr.Dropdown(["Off", "On"], value="Off", label="Automatic mask")
                with gr.Tab("Output"):
                    codec = gr.Dropdown(["H.264", "HEVC"], value="H.264", label="Codec")
                    container = gr.Dropdown(["MP4", "MKV", "MOV"], value="MP4", label="Container")
            with gr.Column(scale=1):
                before = gr.Image(label="Before / source frame", type="filepath")
                after = gr.Image(label="After / processed preview", type="filepath")
                result_video = gr.Video(label="Rendered video")
                timestamp = gr.Number(0, label="Preview timestamp (seconds)")
                preview_duration = gr.Slider(1, 10, 3, step=1, label="Preview duration (seconds)")
                with gr.Row():
                    frame = gr.Button("Preview Frame", variant="primary")
                    clip = gr.Button("Preview Clip (3s)")
                    render = gr.Button("Render Full Video", variant="primary")
                    stop = gr.Button("Stop / Cancel")
                job = gr.Markdown("Ready. One GPU job at a time.")
        clip_inputs = [inp, mode, vsr_mode, scale, quality, container, timestamp, preview_duration, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model]
        render_inputs = [inp, mode, vsr_mode, scale, quality, container, codec, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model]
        inp.change(inspect, inp, [info, state])
        preset.change(apply_preset, preset, [nrpreset, style, intensity, tone, structure, skin, mask])
        frame.click(do_frame, [inp, timestamp, mode, vsr_mode, scale, quality, dlss_scale, nrpreset, style, intensity, tone, structure, skin, mask, model], [before, after, job])
        clip.click(preview_clip, clip_inputs, [result_video, job])
        render.click(render_video, render_inputs, [result_video, job])
        stop.click(lambda: (CONTROLLER.cancel() or "Cancellation requested."), None, job)
        gr.Markdown("### Runtime notes\nA missing backend is never substituted with sharpening or another upscaler. Configure legitimate NVIDIA runtimes, then restart and refresh diagnostics.")
    return ui


def launch():
    build().launch(server_name="127.0.0.1", share=False, enable_monitoring=False, css_paths=Path("src/ui/styles.css"))
