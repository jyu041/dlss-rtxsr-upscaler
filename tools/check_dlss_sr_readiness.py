"""Print the local fail-closed DLSS SR readiness state."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backends.dlss_sr import DLSSSRBackend


if __name__ == "__main__":
    backend = DLSSSRBackend()
    status = backend.status()
    print(json.dumps({"state": status.state, "available": status.available,
                      "reason": status.reason, "identity": backend.validate_runtime()}, indent=2))
