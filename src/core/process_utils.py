import subprocess
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def run(args, *, timeout=30, capture=True, encoding=None, errors=None):
    kwargs = {
        "text": True,
        "capture_output": capture,
        "timeout": timeout,
        "check": False,
    }
    if encoding is not None:
        kwargs["encoding"] = encoding
    if errors is not None:
        kwargs["errors"] = errors
    return subprocess.run([str(x) for x in args], **kwargs)
def tool(name):
    override = os.environ.get(f"NVE_{name.upper()}_PATH")
    if override and Path(override).is_file():
        return override
    if os.name == "nt":
        bundled = PROJECT_ROOT / "runtime" / "tools" / "ffmpeg" / f"{name}.exe"
        if bundled.is_file():
            return str(bundled)
    return shutil.which(name)
def owned_process(args):
    return subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
