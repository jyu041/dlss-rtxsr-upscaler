"""Repeatable DLSS SR measurement harness; generated artifacts stay under runtime/."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.backends.dlss_sr import DLSSSRBackend
from src.video.dlss_sr import INPUT_HEADER, INPUT_MAGIC, PRESETS, MODES, _read_response, _target

sys.path.insert(0, str(ROOT / "third_party" / "ComfyUI-DLSS5-Enhancer"))
from dlss5.motion import TemporalGuide

OUT = ROOT / "runtime" / "benchmarks" / "dlss-sr"
COMPARISON = OUT / "comparison"
WIDTH, HEIGHT, FPS, FRAMES, CUT = 640, 360, 24, 150, 75
WARMUP, MEASURED = 15, 120


def source_frames() -> list[np.ndarray]:
    frames = []
    for index in range(FRAMES):
        cut = index >= CUT
        image = np.full((HEIGHT, WIDTH, 4), 28 if not cut else 205, np.uint8)
        for y in range(0, HEIGHT, 16):
            cv2.line(image, (0, y), (WIDTH - 1, y), (65 if not cut else 150,) * 3 + (255,), 1)
        for x in range(0, WIDTH, 16):
            cv2.line(image, (x, 0), (x, HEIGHT - 1), (85 if not cut else 125,) * 3 + (255,), 1)
        for x in range(-HEIGHT, WIDTH, 24):
            cv2.line(image, (x, 0), (x + HEIGHT, HEIGHT), (220, 220, 220, 255), 1)
        cv2.putText(image, f"DLSS SR {index:03d}", (18, 42), cv2.FONT_HERSHEY_SIMPLEX, .8, (250, 250, 250, 255), 2)
        x = 24 + 8 * (index % 48)
        cv2.rectangle(image, (x, 125), (x + 79, 195), (20, 20, 240, 255), -1)
        for stripe in range(x + 5, x + 75, 10):
            cv2.line(image, (stripe, 130), (stripe, 190), (240, 240, 240, 255), 2)
        cv2.rectangle(image, (WIDTH - 180, 205), (WIDTH - 90, 295), (20, 230, 20, 255), 2)
        if 45 <= index < 60:
            cv2.rectangle(image, (x + 20, 115), (x + 55, 180), (230, 230, 30, 255), -1)
        frames.append(image)
    return frames


def write_source(frames: list[np.ndarray]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "synthetic_source.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not create the synthetic source video")
    for frame in frames:
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR))
    writer.release()
    return path


class GPUSampler:
    def __init__(self):
        self.values: list[tuple[float, float]] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.is_set():
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    util, memory = result.stdout.strip().split(",")[:2]
                    self.values.append((float(util), float(memory)))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            self.stop.wait(.2)

    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *_): self.stop.set(); self.thread.join(3)


def run_one(frames, mode, preset, run, save_output):
    width, height = WIDTH, HEIGHT
    out_width, out_height = _target(width, height, mode)
    command = [str(DLSSSRBackend().host), "stream", str(width), str(height), str(out_width), str(out_height), mode.lower().replace(" ", ""), preset]
    started = time.perf_counter()
    host = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    process_start_ms = (time.perf_counter() - started) * 1000
    guide = TemporalGuide(width, height, flow_width=min(640, width), enabled=True)
    warmup_total = measured_total = flow_total = host_total = 0.0
    resets = []
    sequence_hash = hashlib.sha256()
    selected = {}
    previous_output = None
    interframe_total = post_cut_total = edge_total = 0.0
    measured_count = post_cut_count = 0
    output_writer = None
    if save_output:
        output_writer = cv2.VideoWriter(str(COMPARISON / (f"{mode.lower().replace(' ', '_')}_{preset}.mp4")), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (out_width, out_height))
    first_response_ms = None
    flow_samples = []
    try:
        with GPUSampler() as gpu:
            for index, frame in enumerate(frames[:WARMUP + MEASURED]):
                flow_started = time.perf_counter(); guide_frame = guide.process(frame); flow_ms = (time.perf_counter() - flow_started) * 1000
                flow_total += flow_ms
                if guide_frame.reset: resets.append(index)
                if 10 <= index <= 40 and not guide_frame.reset:
                    x = 24 + 8 * (index % 48)
                    moving = np.zeros((HEIGHT, WIDTH), dtype=bool)
                    moving[125:196, x:x + 80] = True
                    flow_samples.extend(guide_frame.motion[..., 0][moving].astype(np.float32).ravel().tolist())
                motion = np.asarray(guide_frame.motion, dtype=np.float32)
                packet = INPUT_HEADER.pack(INPUT_MAGIC, index, width, height, int(guide_frame.reset), frame.nbytes, motion.nbytes) + frame.tobytes() + motion.tobytes()
                host_started = time.perf_counter(); host.stdin.write(packet); host.stdin.flush()
                _, payload = _read_response(host.stdout, out_width * out_height * 4); host_ms = (time.perf_counter() - host_started) * 1000
                if first_response_ms is None: first_response_ms = (time.perf_counter() - started) * 1000
                if index < WARMUP:
                    warmup_total += flow_ms + host_ms
                else:
                    measured_total += flow_ms + host_ms; host_total += host_ms
                    array = np.frombuffer(payload, dtype=np.uint8).reshape(out_height, out_width, 4)
                    sequence_hash.update(payload)
                    gray = cv2.cvtColor(array, cv2.COLOR_RGBA2GRAY)
                    edges = cv2.Canny(gray, 80, 160)
                    if previous_output is not None:
                        previous_gray, previous_edges = previous_output
                        interframe_total += float(np.mean(cv2.absdiff(gray, previous_gray)))
                        edge_total += float(np.mean(edges != previous_edges))
                        measured_count += 1
                        if index in {CUT, CUT + 1, CUT + 2}:
                            post_cut_total += float(np.mean(cv2.absdiff(gray, previous_gray)))
                            post_cut_count += 1
                    previous_output = (gray, edges)
                    if index in {WARMUP, WARMUP + 30, WARMUP + 60, WARMUP + 74, WARMUP + 75, WARMUP + 90, WARMUP + 119}:
                        selected[str(index)] = hashlib.sha256(payload).hexdigest().upper()
                        if save_output:
                            cv2.imwrite(str(COMPARISON / f"{mode.lower().replace(' ', '_')}_{preset}_frame_{index:03d}.png"), cv2.cvtColor(array, cv2.COLOR_RGBA2BGRA))
                    if output_writer is not None: output_writer.write(cv2.cvtColor(array, cv2.COLOR_RGBA2BGR))
    finally:
        if output_writer is not None: output_writer.release()
        host.terminate(); host.wait(10)
    gpu_values = gpu.values
    return {"mode": mode, "preset": preset, "run": run, "input_resolution": [width, height], "output_resolution": [out_width, out_height], "warmup_frames": WARMUP, "measured_frames": MEASURED, "process_start_ms": process_start_ms, "initialization_ms": first_response_ms, "d3d12_init_ms": None, "ngx_init_ms": None, "feature_creation_ms": None, "warmup_duration_ms": warmup_total, "measured_processing_ms": measured_total, "decode_ms": None, "flow_ms": flow_total * MEASURED / (WARMUP + MEASURED), "host_ipc_evaluation_ms": host_total * MEASURED / (WARMUP + MEASURED), "encode_ms": None, "fps": MEASURED / (measured_total / 1000), "ms_per_frame": measured_total / MEASURED, "peak_vram_mb": max((x[1] for x in gpu_values), default=None), "average_gpu_percent": sum(x[0] for x in gpu_values) / len(gpu_values) if gpu_values else None, "output_hash": sequence_hash.hexdigest().upper(), "frame_hashes": selected, "reset_frames": resets, "motion_expected_x": -8.0, "motion_p50_x": float(np.percentile(flow_samples, 50)) if flow_samples else None, "motion_p10_x": float(np.percentile(flow_samples, 10)) if flow_samples else None, "motion_p90_x": float(np.percentile(flow_samples, 90)) if flow_samples else None, "mean_interframe_difference": interframe_total / max(1, measured_count), "post_cut_difference": post_cut_total / max(1, post_cut_count), "edge_instability": edge_total / max(1, measured_count)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); COMPARISON.mkdir(parents=True, exist_ok=True)
    frames = source_frames(); source = write_source(frames)
    (COMPARISON / "original.mp4").write_bytes(source.read_bytes())
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest().upper()
    for index in (0, 30, 60, 74, 75, 76, 90, 119):
        cv2.imwrite(str(COMPARISON / f"original_frame_{index:03d}.png"), cv2.cvtColor(frames[index], cv2.COLOR_RGBA2BGRA))
    configurations = [(mode, "K") for mode in MODES] + [("Quality", preset) for preset in PRESETS]
    order = [configurations[i:] + configurations[:i] for i in range(args.repeats)]
    rows = []
    for run, configs in enumerate(order, 1):
        for mode, preset in configs:
            print(f"run={run} mode={mode} preset={preset}", flush=True)
            rows.append(run_one(frames, mode, preset, run, run == 1))
    payload = {"source": str(source), "source_sha256": source_hash, "fps": FPS, "frames": FRAMES, "cut_frame": CUT, "warmup_frames": WARMUP, "measured_frames": MEASURED, "flow_conversion": "DIS backward flow resized from 640x360 to render input; no additional scale", "native_phase_timing": "unavailable from host protocol; initialization_ms is process-to-first-response", "runs": rows}
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    fields = [k for k in rows[0] if k not in {"frame_hashes"}]
    with (OUT / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for row in rows: writer.writerow({k: row[k] for k in fields})
    print(json.dumps({"source_sha256": source_hash, "runs": len(rows), "results": str(OUT / "results.json")}, indent=2))


if __name__ == "__main__": main()
