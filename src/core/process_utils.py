import subprocess
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def run(args, *, timeout=30, capture=True, encoding="utf-8", errors="replace"):
    """Run a text-mode helper without allowing malformed output to crash the UI.

    FFmpeg, FFprobe, PowerShell, NVIDIA utilities, and native validation tools
    are external processes. Their diagnostic streams are not part of a binary
    protocol and may contain bytes that are invalid UTF-8 on Windows. Decode
    those streams lossily by default so an error message cannot become the
    render failure itself. Binary protocol callers must use subprocess directly
    with text=False.
    """
    kwargs = {
        "text": True,
        "capture_output": capture,
        "timeout": timeout,
        "check": False,
        "encoding": encoding,
        "errors": errors,
    }
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
