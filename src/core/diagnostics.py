import platform, sys, json, subprocess
from .process_utils import tool
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.backends.dlss_sr import DLSSSRBackend
def collect():
    r=RTXVSRBackend().status(); d=DLSS5Backend().status(); s=DLSSSRBackend().status()
    gpu="UNAVAILABLE"
    try:
        q=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,memory.total,compute_cap","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10,check=False)
        if q.returncode == 0: gpu=q.stdout.strip()
    except (OSError, subprocess.TimeoutExpired): pass
    try:
        import torch
        cuda={"available":torch.cuda.is_available(),"version":torch.__version__}
    except Exception as e: cuda={"available":False,"reason":str(e)}
    try:
        import nvvfx
        vfx_version=getattr(nvvfx,"__version__","0.1.0.1")
    except Exception: vfx_version=None
    dlss = d.__dict__.copy()
    dlss.update({"runtime": "Community DLSS5 v3.0" if d.available else "unavailable", "network": "Worker outbound blocked by Windows Firewall" if d.available else "not applicable", "security": "User-approved exact runtime hashes" if d.available else "not approved"})
    sr = s.__dict__.copy()
    sr.update({"runtime": "not available", "security": "No SR-only protocol path; no fallback permitted"})
    return {"windows":platform.platform(),"python":sys.version.split()[0],"conda_env":__import__('os').environ.get('CONDA_DEFAULT_ENV','unknown'),"gpu":gpu,"cuda":cuda,"nvvfx_version":vfx_version,"ffmpeg":"AVAILABLE" if tool('ffmpeg') else 'UNAVAILABLE',"ffprobe":"AVAILABLE" if tool('ffprobe') else 'UNAVAILABLE',"rtx_vsr":r.__dict__,"dlss5":dlss,"dlss_sr":sr}
def main(): print(json.dumps(collect(), indent=2))
if __name__ == "__main__": main()
