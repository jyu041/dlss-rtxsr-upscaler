import subprocess
from pathlib import Path

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
    import shutil
    return shutil.which(name)
def owned_process(args):
    return subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
