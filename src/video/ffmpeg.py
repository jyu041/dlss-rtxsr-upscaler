from pathlib import Path
from src.core.process_utils import tool, run
def validate(codec, container):
    if container == "MP4" and codec == "ProRes": raise ValueError("ProRes is not offered in MP4.")
    if container == "MOV" and codec == "AV1": raise ValueError("AV1 is not offered in MOV.")
def preview_frame(path, timestamp, output):
    executable = tool("ffmpeg")
    if not executable: raise RuntimeError("ffmpeg was not found in the bundled runtime or on PATH.")
    r=run([executable,"-y","-ss",str(max(0,float(timestamp))),"-i",Path(path),"-frames:v","1","-f","image2",output], timeout=60, encoding="utf-8", errors="replace")
    if r.returncode: raise RuntimeError(r.stderr[-1000:])
    return str(output)
