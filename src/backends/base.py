from dataclasses import dataclass
@dataclass
class BackendStatus:
    name: str; available: bool; state: str; reason: str
class Backend:
    def status(self): raise NotImplementedError
    def process(self, *args, **kwargs): raise NotImplementedError
