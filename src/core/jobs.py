import threading, time, json
from dataclasses import dataclass, field
@dataclass
class Job:
    cancel_event: threading.Event=field(default_factory=threading.Event)
    process: object=None
    def cancel(self):
        self.cancel_event.set()
        if self.process and self.process.poll() is None: self.process.terminate()
class JobController:
    def __init__(self): self.lock=threading.Lock(); self.active=None
    def start(self):
        with self.lock:
            if self.active: raise RuntimeError("Only one GPU job may run at a time")
            self.active=Job(); return self.active
    def finish(self):
        with self.lock: self.active=None
