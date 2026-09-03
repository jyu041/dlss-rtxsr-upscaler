"""Low-overhead cached system metrics for the UI."""

from __future__ import annotations

import subprocess
import threading
import time
import atexit
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True)
class MetricSnapshot:
    timestamp: float
    cpu_percent: float
    ram_percent: float
    ram_used: int
    ram_total: int
    gpu_percent: float | None
    vram_percent: float | None
    vram_used: int | None
    vram_total: int | None
    gpu_name: str | None

    def as_dict(self) -> dict:
        return asdict(self)


class SystemMonitor:
    def __init__(self, gpu_index: int = 0) -> None:
        self.gpu_index = gpu_index
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._active = threading.Event()
        self._thread: threading.Thread | None = None
        self._nvml = None
        self._handle = None
        self._snapshot = MetricSnapshot(time.time(), 0.0, 0.0, 0, 0, None, None, None, None, None)

    def start(self) -> "SystemMonitor":
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self
            psutil.cpu_percent(interval=None)
            self._initialize_nvml()
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="system-monitor", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml = None
            self._handle = None

    def set_active(self, active: bool) -> None:
        if active:
            self._active.set()
        else:
            self._active.clear()
        self._wake.set()

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            return self._snapshot

    def _initialize_nvml(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self.gpu_index)
        except Exception:
            self._nvml = None
            self._handle = None

    def _sample_gpu(self) -> tuple[float | None, float | None, int | None, int | None, str | None]:
        if self._nvml is not None and self._handle is not None:
            try:
                utilization = self._nvml.nvmlDeviceGetUtilizationRates(self._handle)
                memory = self._nvml.nvmlDeviceGetMemoryInfo(self._handle)
                name = self._nvml.nvmlDeviceGetName(self._handle)
                if isinstance(name, bytes):
                    name = name.decode(errors="replace")
                return utilization.gpu, memory.used / memory.total * 100 if memory.total else 0.0, memory.used, memory.total, name
            except Exception:
                pass
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--id={self.gpu_index}", "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            values = [part.strip() for part in result.stdout.strip().split(",")]
            if result.returncode == 0 and len(values) == 4:
                used, total = int(values[2]) * 1024 * 1024, int(values[3]) * 1024 * 1024
                return float(values[1]), used / total * 100 if total else 0.0, used, total, values[0]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None, None, None, None, None

    def _sample(self) -> MetricSnapshot:
        memory = psutil.virtual_memory()
        gpu, vram_percent, vram_used, vram_total, gpu_name = self._sample_gpu()
        return MetricSnapshot(time.time(), psutil.cpu_percent(interval=None), memory.percent, memory.used, memory.total, gpu, vram_percent, vram_used, vram_total, gpu_name)

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._sample()
            with self._lock:
                self._snapshot = sample
            self._wake.wait(1.0 if self._active.is_set() else 2.0)
            self._wake.clear()


MONITOR = SystemMonitor().start()
atexit.register(MONITOR.stop)
