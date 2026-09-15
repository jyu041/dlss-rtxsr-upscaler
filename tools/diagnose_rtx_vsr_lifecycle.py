"""Bounded diagnostic-only RTX VSR lifecycle matrix.

Each case runs in a separate child. This file must not be used as the
production render path; its purpose is to identify native teardown boundaries.
"""
import argparse
import json
import subprocess
import sys
import time


CHILD = r'''
import gc, sys, torch
print("M01 import torch", flush=True)
import nvvfx
print("M02 import nvvfx", flush=True)
level = nvvfx.VideoSuperRes.QualityLevel.LOW
print("M03 before construct", flush=True)
sr = nvvfx.VideoSuperRes(level)
print("M04 after construct", flush=True)
sr.output_width = 128; sr.output_height = 128
print("M05 after dimensions", flush=True)
sr.load()
print("M06 after load", flush=True)
frame = torch.zeros((3, 64, 64), device="cuda", dtype=torch.float32)
print("M07 after input CUDA", flush=True)
def run_one(index):
    print(f"M08.{index} before run", flush=True)
    native = sr.run(frame)
    print(f"M09.{index} after run", flush=True)
    image = native.image
    print(f"M10.{index} after result.image", flush=True)
    owned = torch.from_dlpack(image).clone()
    print(f"M11.{index} after from_dlpack clone", flush=True)
    del owned, image, native
    print(f"M12.{index} after delete result refs", flush=True)
    return
case = sys.argv[1]
if case != "A":
    run_one(1)
if case in ("C", "D"):
    for index in range(2, 11 if case == "C" else 101):
        run_one(index)
if case == "E":
    print("M13 retain references until exit", flush=True)
elif case == "F":
    print("M13 before explicit delete", flush=True)
    del frame, sr
    gc.collect()
    print("M14 after explicit delete/gc", flush=True)
else:
    print("M13 before close", flush=True)
    sr.close()
    print("M14 after close", flush=True)
print("M15 before interpreter shutdown", flush=True)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    for case in "ABCDEF":
        started = time.perf_counter()
        child = subprocess.Popen([sys.executable, "-u", "-c", CHILD, case], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            output, _ = child.communicate(timeout=args.timeout)
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            child.kill()
            output, _ = child.communicate()
        lines = [line for line in output.splitlines() if line]
        result = {"case": case, "timeout": timed_out, "last_marker": lines[-1] if lines else None, "output_produced": any("after run" in line for line in lines), "exit_code": child.returncode, "elapsed_seconds": round(time.perf_counter() - started, 2), "residual_process": child.poll() is None, "markers": lines}
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
