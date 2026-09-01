import json
from .process_utils import run, tool
from .paths import safe_input

def probe(path):
    p = safe_input(path)
    if not tool("ffprobe"): raise RuntimeError("ffprobe was not found in this Conda environment.")
    r = run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",p])
    if r.returncode: raise RuntimeError(r.stderr.strip() or "ffprobe failed")
    d=json.loads(r.stdout); streams=d.get("streams",[]); v=next((s for s in streams if s.get("codec_type")=="video"),{})
    a=next((s for s in streams if s.get("codec_type")=="audio"),{})
    fps=v.get("avg_frame_rate", "0/1"); n, q=(fps.split("/")+['1'])[:2]
    return {"filename":p.name,"path":str(p),"width":v.get("width"),"height":v.get("height"),"fps":float(n)/float(q) if float(q) else 0,"frames":v.get("nb_frames","unknown"),"duration":float(d.get("format",{}).get("duration",0) or 0),"codec":v.get("codec_name","unknown"),"pixel_format":v.get("pix_fmt","unknown"),"bit_depth":v.get("bits_per_raw_sample", "8"),"audio_codec":a.get("codec_name","none"),"size":int(d.get("format",{}).get("size",0) or 0),"hdr":bool(v.get("color_transfer") in {"smpte2084","arib-std-b67"} or v.get("pix_fmt","").endswith("10le"))}

def format_info(i): return f"{i['filename']}\n{i['width']} x {i['height']} | {i['fps']:.3g} FPS | {i['duration']:.2f}s\nVideo: {i['codec']} / {i['pixel_format']} / {i['bit_depth']}-bit\nAudio: {i['audio_codec']} | Frames: {i['frames']}"
