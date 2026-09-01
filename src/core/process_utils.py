import subprocess
from pathlib import Path

def run(args, *, timeout=30, capture=True):
    return subprocess.run([str(x) for x in args], text=True, capture_output=capture, timeout=timeout, check=False)
def tool(name):
    import shutil
    return shutil.which(name)
def owned_process(args):
    return subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
