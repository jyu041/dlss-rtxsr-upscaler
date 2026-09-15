"""Print the local fail-closed DLSS SR readiness state."""
import json
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backends.dlss_sr import DLSSSRBackend


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect DLSS SR identity, or run its bounded local self-test")
    parser.add_argument("--selftest", action="store_true", help="run the native bounded self-test and create a local attestation")
    args = parser.parse_args()
    backend = DLSSSRBackend()
    if args.selftest:
        try:
            result = backend.selftest()
            status = backend.status()
            print(json.dumps({"selftest": result, "state": status.state, "available": status.available, "reason": status.reason}, indent=2))
            raise SystemExit(0 if status.state == "READY" else 1)
        except Exception as exc:
            print(json.dumps({"state": "SELFTEST FAILED", "available": False, "reason": str(exc)}, indent=2))
            raise SystemExit(1)
    status = backend.status()
    print(json.dumps({"state": status.state, "available": status.available,
                      "reason": status.reason, "identity": backend.validate_runtime()}, indent=2))
    raise SystemExit(0 if status.available else 1)
