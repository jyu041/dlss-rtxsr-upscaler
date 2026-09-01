import platform, sys, json
from .process_utils import tool
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend
def collect():
    r=RTXVSRBackend().status(); d=DLSS5Backend().status()
    return {"windows":platform.platform(),"python":sys.version.split()[0],"conda_env":__import__('os').environ.get('CONDA_DEFAULT_ENV','unknown'),"ffmpeg":"AVAILABLE" if tool('ffmpeg') else 'UNAVAILABLE',"ffprobe":"AVAILABLE" if tool('ffprobe') else 'UNAVAILABLE',"rtx_vsr":r.__dict__,"dlss5":d.__dict__}
def main(): print(json.dumps(collect(), indent=2))
if __name__ == "__main__": main()
