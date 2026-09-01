import os, json, gradio as gr
from pathlib import Path
from src.core.media_info import probe, format_info
from src.core.config import load_settings, save_settings, load_presets
from src.core.diagnostics import collect
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.video.ffmpeg import preview_frame
from src.core.paths import TEMP

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
def status_html():
    d=collect(); return " | ".join(f"<b>{k.replace('_',' ').upper()}</b>: {v['state'] if isinstance(v,dict) else v}" for k,v in [("RTX VSR",d['rtx_vsr']),("DLSS5",d['dlss5']),("FFmpeg",d['ffmpeg'])])
def inspect(path):
    if not path: return "No video selected.", None
    try: i=probe(path); return format_info(i) + ("\n\nWARNING: HDR/high-bit-depth detected; DLSS5 path is SDR RGBA8 only." if i['hdr'] else ""), i
    except Exception as e: return f"Inspection failed: {e}", None
def do_frame(path, timestamp, mode):
    if not path: return None, "Choose an input video."
    try:
        available = DLSS5Backend().status().available if mode.startswith("DLSS") else RTXVSRBackend().status().available
        if not available:
            return None, f"{mode} unavailable. No substitute processing was performed. Install and audit the genuine runtime first."
        out=TEMP/f"preview_{os.getpid()}.png"; preview_frame(path,timestamp,out)
        return None, "Backend adapter is not yet enabled for this SDK build; no output was labeled as processed."
    except Exception as e: return None, str(e)
def apply_preset(name):
    p=load_presets().get(name,{}); return [p.get(k) for k in ["dlss_preset","dlss_style","dlss_intensity","local_tone","local_structure","skin_structure","automatic_mask"]]
def unavailable_action(mode, action):
    status = DLSS5Backend().status() if mode.startswith("DLSS") else RTXVSRBackend().status()
    if not status.available:
        return f"{action} blocked: {status.name} unavailable. {status.reason}"
    return f"{action} is gated until the installed SDK adapter passes its smoke test."
def build():
    with gr.Blocks(title="NVIDIA Video Enhancer") as ui:
        gr.Markdown("# NVIDIA Video Enhancer\n**RTX Video Super Resolution + DLSS 5 Neural Rendering**")
        status=gr.HTML(status_html())
        with gr.Row():
            with gr.Column(scale=1):
                inp=gr.Video(label="Input video"); info=gr.Textbox(label="Media inspection", lines=5, interactive=False); state=gr.State()
                mode=gr.Radio(["RTX VSR only","DLSS 5 only","DLSS 5 → RTX VSR"], value="DLSS 5 only", label="Processing order")
            with gr.Column(scale=1):
                with gr.Tab("RTX Super Resolution"):
                    scale=gr.Dropdown([1.0,1.5,2.0,2.5,3.0,4.0],value=2.0,label="Scale factor"); quality=gr.Dropdown(["LOW","MEDIUM","HIGH","ULTRA"],value="ULTRA",label="Quality")
                    gr.Markdown("Presets: 720p / 1080p / 1440p / 2160p are available through target dimensions in the next revision. Dimensions are aligned by the NVIDIA adapter.")
                with gr.Tab("DLSS 5"):
                    preset=gr.Dropdown(list(load_presets())+["Default"],value="Photoreal Balanced",label="User preset"); nrpreset=gr.Dropdown(["Default","Preset #1","Preset #2","Preset #3"],value="Default",label="NR preset"); style=gr.Dropdown(["Default","Natural","Cinematic"],value="Natural",label="NR style")
                    intensity=gr.Slider(0,2,.55,.05,label="NR intensity"); tone=gr.Slider(0,2,.35,.05,label="Local tone strength"); structure=gr.Slider(0,2,.35,.05,label="Local structure strength"); skin=gr.Slider(-1,2,.15,.05,label="Skin structure strength"); mask=gr.Dropdown(["Off","On"],value="Off",label="Automatic mask")
                with gr.Tab("Output"):
                    codec=gr.Dropdown(["H.264","HEVC","AV1"],value="H.264",label="Codec"); container=gr.Dropdown(["MP4","MKV","MOV"],value="MP4",label="Container"); encq=gr.Dropdown(["Auto","Good","Best","Lossless/Max"],value="Good",label="Quality"); cq=gr.Number(19,label="Advanced CQ",precision=0); ep=gr.Dropdown(["p1","p4","p5","p7"],value="p5",label="NVENC preset")
            with gr.Column(scale=1):
                before=gr.Image(label="Before / source frame", type="filepath"); after=gr.Image(label="After / processed preview", type="filepath"); timestamp=gr.Number(0,label="Preview timestamp (seconds)");
                with gr.Row(): frame=gr.Button("Preview Frame",variant="primary"); clip=gr.Button("Preview Clip (3s)"); render=gr.Button("Render Full Video",variant="primary"); stop=gr.Button("Stop / Cancel")
                job=gr.Markdown("Ready. One GPU job at a time.")
        inp.change(inspect,inp,[info,state]); preset.change(apply_preset,preset,[nrpreset,style,intensity,tone,structure,skin,mask]); frame.click(do_frame,[inp,timestamp,mode],[after,job]); clip.click(lambda m: unavailable_action(m,"Preview clip"), mode, job); render.click(lambda m: unavailable_action(m,"Full render"), mode, job); stop.click(lambda: "No active job.", None, job)
        gr.Markdown("### Runtime notes\nA missing backend is never substituted with sharpening or another upscaler. Configure legitimate NVIDIA runtimes, then restart and refresh diagnostics.")
    return ui
def launch(): build().launch(server_name="127.0.0.1",share=False,analytics_enabled=False,css=Path("src/ui/styles.css").read_text())
