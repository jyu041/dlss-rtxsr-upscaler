"""Controlled OpenCV DIS motion experiments; output stays under runtime/."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.backends.dlss_sr import DLSSSRBackend
from src.video.dlss_sr import INPUT_HEADER, INPUT_MAGIC, _read_response, _target

OUT = ROOT / "runtime" / "benchmarks" / "dlss-sr" / "dis"
WIDTH, HEIGHT, FRAMES, SHIFT = 640, 360, 60, 8


def scenes() -> dict[str, list[np.ndarray]]:
    yy, xx = np.indices((HEIGHT, WIDTH))
    background = (28 + ((xx * 13 + yy * 7) & 31)).astype(np.uint8)
    result = {}
    for name in ("textured", "flat", "partial"):
        frames = []
        for index in range(FRAMES):
            image = np.repeat(background[:, :, None], 4, axis=2)
            x = 80 + SHIFT * index
            if name == "textured":
                object_image = (40 + ((xx * 29 + yy * 17) & 191)).astype(np.uint8)
            elif name == "flat":
                object_image = np.full((HEIGHT, WIDTH), 120, np.uint8)
            else:
                object_image = (120 + ((xx // 8 & 1) * 100)).astype(np.uint8)
            image[120:200, x:x + 80, :3] = object_image[120:200, 80:160, None]
            image[120:200, x:x + 80, 3] = 255
            frames.append(image)
        result[name] = frames
    return result


class Guide:
    def __init__(self, width: int, height: int, flow_width: int, preset: str, strategy: str):
        self.width, self.height, self.flow_width, self.strategy = width, height, flow_width, strategy
        self.flow_height = max(64, int(round(height * flow_width / width / 2) * 2))
        presets = {"ultrafast": cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST, "fast": cv2.DISOPTICAL_FLOW_PRESET_FAST, "medium": cv2.DISOPTICAL_FLOW_PRESET_MEDIUM}
        self.flow = cv2.DISOpticalFlow_create(presets[preset])
        self.flow.setUseSpatialPropagation(True)
        self.flow.setFinestScale(1)
        self.previous = None

    def gray(self, rgba: np.ndarray) -> np.ndarray:
        return cv2.resize(cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY), (self.flow_width, self.flow_height), interpolation=cv2.INTER_AREA)

    def process(self, rgba: np.ndarray) -> tuple[np.ndarray, bool]:
        current = self.gray(rgba)
        if self.previous is None:
            self.previous = current
            return np.zeros((self.height, self.width, 2), np.float32), True
        score = float(np.mean(cv2.absdiff(current, self.previous))) / 255.0
        if score > 0.24:
            self.previous = current
            return np.zeros((self.height, self.width, 2), np.float32), True
        backward = self.flow.calc(current, self.previous, None)
        forward = None
        if self.strategy != "baseline":
            forward = self.flow.calc(self.previous, current, None)
        flow = cv2.resize(backward, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        flow[..., 0] *= self.width / self.flow_width
        flow[..., 1] *= self.height / self.flow_height
        if forward is not None:
            forward = cv2.resize(forward, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
            forward[..., 0] *= self.width / self.flow_width
            forward[..., 1] *= self.height / self.flow_height
            grid_x, grid_y = np.meshgrid(np.arange(self.width, dtype=np.float32), np.arange(self.height, dtype=np.float32))
            sample_x = np.clip(grid_x + flow[..., 0], 0, self.width - 1)
            sample_y = np.clip(grid_y + flow[..., 1], 0, self.height - 1)
            sampled = np.stack((cv2.remap(forward[..., 0], sample_x, sample_y, cv2.INTER_LINEAR), cv2.remap(forward[..., 1], sample_x, sample_y, cv2.INTER_LINEAR)), axis=-1)
            invalid = np.linalg.norm(flow + sampled, axis=-1) > 1.5
            if self.strategy == "zero-invalid":
                flow[invalid] = 0
            elif self.strategy == "conservative-clamp":
                flow[invalid] *= 0.25
                flow[np.linalg.norm(flow, axis=-1) > 64] = 0
            elif self.strategy == "neighbor-fill":
                valid = (~invalid).astype(np.uint8)
                for _ in range(5):
                    for channel in (0, 1):
                        replacement = cv2.medianBlur(flow[..., channel].astype(np.float32), 5)
                        flow[..., channel] = np.where(invalid & (valid == 0), replacement, flow[..., channel])
                    valid = cv2.dilate(valid, np.ones((3, 3), np.uint8))
                flow[invalid] = cv2.medianBlur(flow.astype(np.float32), 5)[invalid]
        self.previous = current
        return np.ascontiguousarray(flow), False


def mask(name: str, index: int) -> np.ndarray:
    x = 80 + SHIFT * index
    result = np.zeros((HEIGHT, WIDTH), bool)
    if name == "interior": result[140:180, x + 16:x + 64] = True
    elif name == "leading": result[140:180, x + 64:x + 72] = True
    elif name == "trailing": result[140:180, x + 8:x + 16] = True
    elif name == "static": result[80:280, 400:600] = True
    elif name == "disocclusion": result[120:200, x - 8:x] = True
    elif name == "occlusion": result[120:200, x + 72:x + 80] = True
    return result


def summarize(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, np.float32)
    return {key: float(value) for key, value in zip(("p10", "p50", "p90", "mean", "std"), (np.percentile(array, 10), np.percentile(array, 50), np.percentile(array, 90), np.mean(array), np.std(array)))}


def run_scene(name: str, frames: list[np.ndarray], preset: str, flow_width: int, strategy: str) -> dict:
    guide = Guide(WIDTH, HEIGHT, flow_width, preset, strategy)
    regions = {region: {"x": [], "y": [], "error": [], "magnitude": []} for region in ("interior", "leading", "trailing", "static", "disocclusion", "occlusion")}
    started = time.perf_counter()
    for index, frame in enumerate(frames):
        flow, reset = guide.process(frame)
        if reset: continue
        for region, values in regions.items():
            selected = flow[mask(region, index)]
            values["x"].extend(selected[:, 0].tolist()); values["y"].extend(selected[:, 1].tolist()); values["magnitude"].extend(np.linalg.norm(selected, axis=1).tolist())
            truth_x, truth_y = ((-SHIFT, 0) if region in ("interior", "leading", "trailing") else (0, 0))
            if region not in ("disocclusion", "occlusion"):
                values["error"].extend(np.linalg.norm(selected - (truth_x, truth_y), axis=1).tolist())
    output = {"scene": name, "preset": preset, "flow_width": flow_width, "strategy": strategy, "ms_per_frame": (time.perf_counter() - started) * 1000 / (FRAMES - 1), "regions": {}}
    for region, values in regions.items():
        output["regions"][region] = {"count": len(values["x"]), "x": summarize(values["x"]), "y": summarize(values["y"]), "error": summarize(values["error"]) if values["error"] else None, "magnitude": summarize(values["magnitude"])}
    return output


def run_dlss(name: str, frames: list[np.ndarray], strategy: str) -> dict:
    guide = Guide(WIDTH, HEIGHT, 640, "medium", strategy)
    out_width, out_height = _target(WIDTH, HEIGHT, "Quality")
    host = subprocess.Popen([str(DLSSSRBackend().host), "stream", str(WIDTH), str(HEIGHT), str(out_width), str(out_height), "quality", "Default"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    digest = hashlib.sha256(); residuals = []; baseline = []
    try:
        for frame in frames:
            motion, reset = guide.process(frame)
            packet = INPUT_HEADER.pack(INPUT_MAGIC, len(baseline), WIDTH, HEIGHT, int(reset), frame.nbytes, motion.nbytes) + frame.tobytes() + motion.astype(np.float32).tobytes()
            host.stdin.write(packet); host.stdin.flush(); values, payload = _read_response(host.stdout, out_width * out_height * 4)
            digest.update(payload); image = np.frombuffer(payload, np.uint8).reshape(out_height, out_width, 4); expected = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_LINEAR)
            x = (80 + SHIFT * len(baseline)) * out_width // WIDTH; y0, y1 = 120 * out_height // HEIGHT, 200 * out_height // HEIGHT; trailing = image[y0:y1, x:x + max(1, SHIFT * out_width // WIDTH)]
            target = expected[y0:y1, x:x + max(1, SHIFT * out_width // WIDTH)]; residuals.append(float(np.mean(cv2.absdiff(trailing, target))))
            baseline.append(image)
    finally:
        host.terminate(); host.wait(10)
    return {"scene": name, "strategy": strategy, "output_sha256": digest.hexdigest().upper(), "trailing_residual_mean": float(np.mean(residuals)), "trailing_residual_p90": float(np.percentile(residuals, 90)), "frames": len(baseline)}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--scene", choices=("all", "textured", "flat", "partial"), default="all"); parser.add_argument("--quick", action="store_true"); parser.add_argument("--dlss", action="store_true"); args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); selected = scenes(); names = selected if args.scene == "all" else {args.scene: selected[args.scene]}; rows = []
    configurations = [("medium", 640, "baseline"), ("fast", 640, "baseline"), ("ultrafast", 640, "baseline"), ("medium", 480, "baseline"), ("medium", 640, "zero-invalid"), ("medium", 640, "neighbor-fill"), ("medium", 640, "conservative-clamp")]
    if args.quick: configurations = configurations[:1]
    for name, frames in names.items():
        for preset, width, strategy in configurations: print(f"scene={name} preset={preset} flow_width={width} strategy={strategy}", flush=True); rows.append(run_scene(name, frames, preset, width, strategy))
    result = {"width": WIDTH, "height": HEIGHT, "frames": FRAMES, "shift": SHIFT, "rows": rows}
    if args.dlss:
        result["dlss"] = [run_dlss(name, frames, strategy) for name, frames in names.items() for strategy in ("baseline", "zero-invalid", "neighbor-fill")]
    (OUT / "dis_motion_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
