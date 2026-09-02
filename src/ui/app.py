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

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
CONTROLLER = JobController()
def status_html():
    d=collect(); return " | ".join(f"<b>{k.replace('_',' ').upper()}</b>: {v['state'] if isinstance(v,dict) else v}" for k,v in [("RTX VSR",d['rtx_vsr']),("DLSS5",d['dlss5']),("FFmpeg",d['ffmpeg'])])
def inspect(path):
    if not path: return "No video selected.", None
    try: i=probe(path); return format_info(i) + ("\n\nWARNING: HDR/high-bit-depth detected; DLSS5 path is SDR RGBA8 only." if i['hdr'] else ""), i
    except Exception as e: return f"Inspection failed: {e}", None
def do_frame(path, timestamp, mode, vsr_mode, scale_value, quality_value):
    if not path: return None, None, "Choose an input video."
    try:
        available = DLSS5Backend().status().available if mode.startswith("DLSS") else RTXVSRBackend().status().available
        if not available:
            return None, None, f"{mode} unavailable. No substitute processing was performed. Install and audit the genuine runtime first."
        source_frame=TEMP/f"preview_source_{os.getpid()}.png"; preview_frame(path,timestamp,source_frame)
        from PIL import Image
        import numpy as np
        image=np.asarray(Image.open(source_frame).convert("RGB"), dtype=np.uint8); h,w=image.shape[:2]
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
def render_video(path, processing_mode, vsr_mode, scale_value, quality_value, container_value):
    if not path: return None, "Choose an input video."
    if processing_mode != "RTX VSR only": return None, f"{processing_mode} is unavailable until its genuine backend is installed."
    try:
        job = CONTROLLER.start(); destination = output_path(Path(path), "RTX VSR only", container_value, float(scale_value))
        stats = render_vsr(path, destination, RTXVSRBackend(), float(scale_value), quality_value, vsr_mode, job.cancel_event)
        CONTROLLER.finish(); return str(destination), f"Completed: {stats['frames']} frames at {stats['fps']:.2f} FPS; {stats['dimensions'][0]}x{stats['dimensions'][1]}; audio preserved: {stats['audio_preserved']}"
    except InterruptedError: CONTROLLER.finish(); return None, "Render cancelled; partial output removed."
    except Exception as exc: CONTROLLER.finish(); return None, f"Render failed: {exc}"
def build():
    with gr.Blocks(title="NVIDIA Video Enhancer", analytics_enabled=False) as ui:
        gr.Markdown("# NVIDIA Video Enhancer\n**RTX Video Super Resolution + DLSS 5 Neural Rendering**")
        status=gr.HTML(status_html())
        with gr.Row():
            with gr.Column(scale=1):
                inp=gr.Video(label="Input video"); info=gr.Textbox(label="Media inspection", lines=5, interactive=False); state=gr.State()
                mode=gr.Radio(["RTX VSR only","DLSS 5 only","DLSS 5 → RTX VSR"], value="DLSS 5 only", label="Processing order")
            with gr.Column(scale=1):
                with gr.Tab("RTX Super Resolution"):
                    vsr_mode=gr.Dropdown(["Super Resolution","High Bitrate","Deblur","Denoise"],value="Super Resolution",label="Mode",info="Super Resolution: general upscale and compression cleanup. High Bitrate: clean generated footage. Deblur: mild softness at 1x. Denoise: noise cleanup at 1x."); scale=gr.Dropdown([1.0,1.5,2.0,2.5,3.0,4.0],value=2.0,label="Scale factor"); quality=gr.Dropdown(["LOW","MEDIUM","HIGH","ULTRA"],value="ULTRA",label="Quality")
                    gr.Markdown("Deblur and Denoise are same-resolution modes in the NVIDIA API. Output dimensions are aligned to 8 pixels for upscaling.")
                with gr.Tab("DLSS 5"):
                    preset=gr.Dropdown(list(load_presets())+["Default"],value="Photoreal Balanced",label="User preset"); nrpreset=gr.Dropdown(["Default","Preset #1","Preset #2","Preset #3"],value="Default",label="NR preset"); style=gr.Dropdown(["Default","Natural","Cinematic"],value="Natural",label="NR style")
                    intensity=gr.Slider(0,2,.55,.05,label="NR intensity"); tone=gr.Slider(0,2,.35,.05,label="Local tone strength"); structure=gr.Slider(0,2,.35,.05,label="Local structure strength"); skin=gr.Slider(-1,2,.15,.05,label="Skin structure strength"); mask=gr.Dropdown(["Off","On"],value="Off",label="Automatic mask")
                with gr.Tab("Output"):
                    codec=gr.Dropdown(["H.264","HEVC","AV1"],value="H.264",label="Codec"); container=gr.Dropdown(["MP4","MKV","MOV"],value="MP4",label="Container"); encq=gr.Dropdown(["Auto","Good","Best","Lossless/Max"],value="Good",label="Quality"); cq=gr.Number(19,label="Advanced CQ",precision=0); ep=gr.Dropdown(["p1","p4","p5","p7"],value="p5",label="NVENC preset")
            with gr.Column(scale=1):
                before=gr.Image(label="Before / source frame", type="filepath"); after=gr.Image(label="After / processed preview", type="filepath"); result_video=gr.Video(label="Rendered video"); timestamp=gr.Number(0,label="Preview timestamp (seconds)");
                with gr.Row(): frame=gr.Button("Preview Frame",variant="primary"); clip=gr.Button("Preview Clip (3s)"); render=gr.Button("Render Full Video",variant="primary"); stop=gr.Button("Stop / Cancel")
                job=gr.Markdown("Ready. One GPU job at a time.")
        inp.change(inspect,inp,[info,state]); preset.change(apply_preset,preset,[nrpreset,style,intensity,tone,structure,skin,mask]); frame.click(do_frame,[inp,timestamp,mode,vsr_mode,scale,quality],[before,after,job]); clip.click(lambda m: unavailable_action(m,"Preview clip"), mode, job); render.click(render_video,[inp,mode,vsr_mode,scale,quality,container],[result_video,job]); stop.click(lambda: (CONTROLLER.cancel() or "Cancellation requested."), None, job)
        gr.Markdown("### Runtime notes\nA missing backend is never substituted with sharpening or another upscaler. Configure legitimate NVIDIA runtimes, then restart and refresh diagnostics.")
    return ui
def launch(): build().launch(server_name="127.0.0.1",share=False,enable_monitoring=False,css_paths=Path("src/ui/styles.css"))
