"""Persistent PyTorch CUDA residual compositor for reduced-resolution NR."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F


def select_cuda_device(preferred_name: str | None = None) -> torch.device | None:
    if not torch.cuda.is_available():
        return None
    matches = [index for index in range(torch.cuda.device_count()) if not preferred_name or preferred_name == torch.cuda.get_device_name(index)]
    if len(matches) != 1:
        return None
    return torch.device(f"cuda:{matches[0]}")


class CudaResidualCompositor:
    """Reuse device and host staging storage for one fixed frame geometry."""

    def __init__(self, native_width: int, native_height: int, working_width: int, working_height: int, *, device: torch.device | str):
        selected = torch.device(device)
        if selected.type != "cuda" or not torch.cuda.is_available():
            raise RuntimeError("CUDA residual composition requires an available CUDA device")
        self.device = selected
        self.native_width, self.native_height = int(native_width), int(native_height)
        self.working_width, self.working_height = int(working_width), int(working_height)
        if min(self.native_width, self.native_height, self.working_width, self.working_height) < 1:
            raise ValueError("Compositor dimensions must be positive")
        self.stream = torch.cuda.Stream(device=self.device)
        with torch.cuda.device(self.device):
            self.native_host = torch.empty((self.native_height, self.native_width, 4), dtype=torch.uint8, pin_memory=True)
            self.source_host = torch.empty((self.working_height, self.working_width, 4), dtype=torch.uint8, pin_memory=True)
            self.nr_host = torch.empty((self.working_height, self.working_width, 4), dtype=torch.uint8, pin_memory=True)
            self.output_host = torch.empty((self.native_height, self.native_width, 4), dtype=torch.uint8, pin_memory=True)
            self.native_device = torch.empty((self.native_height, self.native_width, 3), dtype=torch.float32, device=self.device)
            self.source_device = torch.empty((self.working_height, self.working_width, 3), dtype=torch.float32, device=self.device)
            self.nr_device = torch.empty((self.working_height, self.working_width, 3), dtype=torch.float32, device=self.device)
            self.output_device = torch.empty((self.native_height, self.native_width, 3), dtype=torch.uint8, device=self.device)
            self.residual_device = torch.empty((self.working_height, self.working_width, 3), dtype=torch.float32, device=self.device)
        self._closed = False

    def compose(self, native_rgba: np.ndarray, working_source: np.ndarray, working_nr: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        if self._closed:
            raise RuntimeError("CUDA residual compositor is closed")
        native = np.asarray(native_rgba, dtype=np.uint8)
        source = np.asarray(working_source, dtype=np.uint8)
        nr = np.asarray(working_nr, dtype=np.uint8)
        if native.shape != (self.native_height, self.native_width, 4) or source.shape != (self.working_height, self.working_width, 4) or nr.shape != source.shape:
            raise ValueError("CUDA compositor received a frame with unexpected dimensions")
        started = time.perf_counter()
        np.copyto(self.native_host.numpy(), native)
        np.copyto(self.source_host.numpy(), source)
        np.copyto(self.nr_host.numpy(), nr)
        with torch.cuda.stream(self.stream):
            total_start = torch.cuda.Event(enable_timing=True)
            h2d_start = torch.cuda.Event(enable_timing=True)
            h2d_end = torch.cuda.Event(enable_timing=True)
            compute_start = torch.cuda.Event(enable_timing=True)
            compute_end = torch.cuda.Event(enable_timing=True)
            d2h_start = torch.cuda.Event(enable_timing=True)
            d2h_end = torch.cuda.Event(enable_timing=True)
            total_end = torch.cuda.Event(enable_timing=True)
            total_start.record(self.stream)
            h2d_start.record(self.stream)
            self.native_device.copy_(self.native_host[:, :, :3], non_blocking=True)
            self.source_device.copy_(self.source_host[:, :, :3], non_blocking=True)
            self.nr_device.copy_(self.nr_host[:, :, :3], non_blocking=True)
            h2d_end.record(self.stream)
            compute_start.record(self.stream)
            self.residual_device.copy_(self.nr_device - self.source_device)
            resized = F.interpolate(self.residual_device.permute(2, 0, 1).unsqueeze(0), size=(self.native_height, self.native_width), mode="bilinear", align_corners=False)[0].permute(1, 2, 0)
            self.output_device.copy_(torch.round((self.native_device + resized).clamp(0.0, 255.0)))
            compute_end.record(self.stream)
            d2h_start.record(self.stream)
            self.output_host[:, :, :3].copy_(self.output_device, non_blocking=True)
            self.output_host[:, :, 3].copy_(self.native_host[:, :, 3], non_blocking=False)
            d2h_end.record(self.stream)
            total_end.record(self.stream)
        self.stream.synchronize()
        output = self.output_host.numpy().copy()
        wall_ms = (time.perf_counter() - started) * 1000
        return output, {"recompose_wall_ms": wall_ms, "gpu_h2d_ms": h2d_start.elapsed_time(h2d_end), "gpu_residual_compute_ms": compute_start.elapsed_time(compute_end), "gpu_d2h_ms": d2h_start.elapsed_time(d2h_end), "gpu_total_ms": total_start.elapsed_time(total_end), "cuda_device_index": self.device.index, "cuda_device_name": torch.cuda.get_device_name(self.device), "torch_version": torch.__version__, "torch_cuda_version": torch.version.cuda}

    def allocator_stats(self) -> dict[str, float]:
        return {"torch_memory_allocated_mib": torch.cuda.memory_allocated(self.device) / 1048576, "torch_max_memory_allocated_mib": torch.cuda.max_memory_allocated(self.device) / 1048576, "torch_memory_reserved_mib": torch.cuda.memory_reserved(self.device) / 1048576}

    def close(self) -> None:
        if not self._closed:
            self.stream.synchronize()
            for name in ("native_host", "source_host", "nr_host", "output_host", "native_device", "source_device", "nr_device", "output_device", "residual_device"):
                setattr(self, name, None)
            self._closed = True

    def __enter__(self) -> "CudaResidualCompositor":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
