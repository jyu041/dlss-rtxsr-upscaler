"""Run the bounded RTX VSR readiness check with visible progress."""
import argparse
import json

from src.core.rtx_vsr_readiness import assess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0, help="hard child-process timeout in seconds")
    args = parser.parse_args()
    print("RTX VSR readiness: static API inspection", flush=True)
    result = assess(timeout_seconds=args.timeout, heartbeat=lambda line: print(line, flush=True))
    print(json.dumps(result.as_dict(), indent=2), flush=True)
    raise SystemExit(0 if result.available else 1)


if __name__ == "__main__":
    main()
