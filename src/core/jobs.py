"""Single-job coordination and thread-safe progress state."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class JobProgress:
    phase: str = "IDLE"
    frames_done: int = 0
    frames_total: int | None = None
    percent: float | None = 0.0
    elapsed_seconds: float = 0.0
    current_fps: float = 0.0
    average_fps: float = 0.0
    smoothed_fps: float = 0.0
    eta_seconds: float | None = None
    message: str = "Ready"
    started_at: float | None = None
    updated_at: float | None = None
    state: str = "IDLE"

    def as_dict(self) -> dict:
        return asdict(self)


class ProgressTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.perf_counter()
        self._processing_started: float | None = None
        self._last_time = self._started
        self._last_done = 0
        self._smoothed = 0.0
        self._progress = JobProgress(started_at=time.time(), updated_at=time.time())

    def update(self, *, frames_done=None, frames_total=None, phase=None, state=None, message=None) -> JobProgress:
        now = time.perf_counter()
        with self._lock:
            old = self._progress
            done = old.frames_done if frames_done is None else max(0, int(frames_done))
            total = old.frames_total if frames_total is None else (int(frames_total) if frames_total is not None else None)
            phase_value = phase or old.phase
            if phase_value == "PROCESSING" and self._processing_started is None:
                self._processing_started = now
            delta_time = now - self._last_time
            delta_frames = done - self._last_done
            current = delta_frames / delta_time if delta_time > 0 and delta_frames > 0 else old.current_fps
            if delta_frames > 0 and delta_time > 0:
                instant = delta_frames / delta_time
                self._smoothed = instant if not self._smoothed else 0.2 * instant + 0.8 * self._smoothed
            processing_elapsed = now - self._processing_started if self._processing_started else 0.0
            average = done / processing_elapsed if done and processing_elapsed > 0 else 0.0
            percent = min(100.0, done / total * 100.0) if total and total > 0 else None
            eta = None
            if total and total > done and done >= 5 and processing_elapsed >= 2 and self._smoothed > 0:
                eta = max(0.0, (total - done) / self._smoothed)
            self._last_time, self._last_done = now, done
            self._progress = JobProgress(phase_value, done, total, percent, time.perf_counter() - self._started, current, average, self._smoothed, eta, message or old.message, old.started_at, time.time(), state or old.state)
            return self._progress

    def set_state(self, state: str, *, phase: str | None = None, message: str | None = None) -> JobProgress:
        return self.update(state=state, phase=phase or state, message=message)

    def snapshot(self) -> JobProgress:
        with self._lock:
            return self._progress


@dataclass
class Job:
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: object = None
    progress: ProgressTracker = field(default_factory=ProgressTracker)

    def cancel(self):
        self.cancel_event.set()
        self.progress.set_state("CANCELLED", phase="CANCELLED", message="Cancellation requested")
        if self.process and self.process.poll() is None:
            self.process.terminate()


class JobController:
    def __init__(self):
        self.lock = threading.Lock()
        self.active: Job | None = None
        self.last_progress = JobProgress()

    def start(self):
        with self.lock:
            if self.active:
                raise RuntimeError("Only one GPU job may run at a time")
            self.active = Job()
            self.active.progress.set_state("PREPARING", phase="PREPARING", message="Preparing job")
            return self.active

    def finish(self, state="COMPLETED", message=None):
        with self.lock:
            if self.active:
                if state == "COMPLETED":
                    current = self.active.progress.snapshot()
                    if current.frames_total is not None:
                        self.active.progress.update(frames_done=current.frames_total)
                self.active.progress.set_state(state, phase=state, message=message or state.title())
                self.last_progress = self.active.progress.snapshot()
                self.active = None

    def snapshot(self) -> JobProgress:
        with self.lock:
            return self.active.progress.snapshot() if self.active else self.last_progress

    def cancel(self):
        with self.lock:
            if self.active:
                self.active.cancel()
