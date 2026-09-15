"""Ten bounded RTX VSR helper jobs with per-job device-memory samples."""
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.video.rtx_vsr_worker import RTXVSRSession


def memory():
    result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def main():
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    records = []
    for job in range(1, 11):
        before = memory()
        started = time.perf_counter()
        session = RTXVSRSession(timeout=30)
        try:
            session.start(64, 64, 128, 128, "Super Resolution", "LOW")
            output = session.process_frame(0, frame)
            peak = memory()
            teardown = session.finish()
            after = memory()
            records.append({"job": job, "pid": session.pid, "before_mib": before, "peak_mib": peak, "after_mib": after, "teardown": teardown, "shape": list(output.shape), "elapsed_seconds": round(time.perf_counter() - started, 2), "alive": session.process.poll() is None})
        finally:
            session.close()
        print(records[-1], flush=True)
    print({"jobs": len(records), "records": records}, flush=True)


if __name__ == "__main__":
    main()
