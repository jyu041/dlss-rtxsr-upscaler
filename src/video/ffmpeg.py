from pathlib import Path
from src.core.process_utils import tool, run
def validate(codec, container):
    if container == "MP4" and codec == "ProRes": raise ValueError("ProRes is not offered in MP4.")
    if container == "MOV" and codec == "AV1": raise ValueError("AV1 is not offered in MOV.")
def preview_frame(path, timestamp, output):
    if not tool("ffmpeg"): raise RuntimeError("ffmpeg was not found")
    r=run(["ffmpeg","-y","-ss",str(max(0,float(timestamp))),"-i",Path(path),"-frames:v","1","-f","image2",output], timeout=60)
    if r.returncode: raise RuntimeError(r.stderr[-1000:])
    return str(output)
