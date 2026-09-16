import platform, sys, json, subprocess
from pathlib import Path
from .process_utils import tool
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
from src.backends.dlss_sr import DLSSSRBackend
from src.backends.dlssg import DLSSGBackend
from src.runtime_manager import RuntimeManager

RUNTIME_MANIFEST = Path(__file__).resolve().parents[1] / "runtime_manager" / "manifest.json"
RUNTIME_INSTALL_ROOT = Path(__file__).resolve().parents[2] / "runtime"


def runtime_inventory():
    try:
        return RuntimeManager(RUNTIME_MANIFEST, RUNTIME_INSTALL_ROOT).inventory()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return [{"state": "INVALID", "action": "REVIEW", "detail": f"Runtime manifest unavailable: {exc}"}]
def collect():
    r=RTXVSRBackend().status(); d=DLSS5Backend().status(); sr_backend=DLSSSRBackend(); s=sr_backend.status(); fg=DLSSGBackend().status()
    gpu="UNAVAILABLE"
    try:
        q=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,memory.total,compute_cap","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10,check=False)
        if q.returncode == 0: gpu=q.stdout.strip()
    except (OSError, subprocess.TimeoutExpired): pass
    try:
        import torch
        cuda={"available":torch.cuda.is_available(),"version":torch.__version__}
    except Exception as e: cuda={"available":False,"reason":str(e)}
    vfx_version = getattr(getattr(r, "_readiness", None), "version", None)
    dlss = d.__dict__.copy()
    dlss.update({"runtime": "Community DLSS5 v3.0" if d.available else "unavailable", "network": "Worker outbound blocked by Windows Firewall" if d.available else "not applicable", "security": "User-approved exact runtime hashes" if d.available else "not approved"})
    sr = s.__dict__.copy()
    sr.update({"runtime": str(sr_backend.runtime) if sr_backend.runtime.is_file() else "unavailable",
               "validated_runtime_sha256": sr_backend.validate_runtime().get("runtime_sha256"),
               "security": "Exact validated NVIDIA runtime hash required; no fallback permitted"})
    try:
        from src.video.dlssg import ffmpeg_executable
        ffmpeg = "AVAILABLE" if ffmpeg_executable() else "UNAVAILABLE"
    except RuntimeError:
        ffmpeg = "UNAVAILABLE"
    return {"windows":platform.platform(),"python":sys.version.split()[0],"conda_env":__import__('os').environ.get('CONDA_DEFAULT_ENV','unknown'),"gpu":gpu,"cuda":cuda,"nvvfx_version":vfx_version,"ffmpeg":ffmpeg,"ffprobe":"AVAILABLE" if tool('ffprobe') else 'UNAVAILABLE',"runtimes":runtime_inventory(),"rtx_vsr":r.__dict__,"dlss5":dlss,"dlss_sr":sr,"dlssg":fg.__dict__}
def main(): print(json.dumps(collect(), indent=2))
if __name__ == "__main__": main()
