"""One-command, non-mutating DLSS-G readiness check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Running a file under tools/ does not put the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.dlssg_readiness import assess, format_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DLSS-G SYSTEM/PROJECT/COMMUNITY/OFFICIAL readiness.")
    parser.add_argument("--worker")
    parser.add_argument("--community-runtime", help="absolute user-supplied version.dll path")
    parser.add_argument("--official-runtime-dir", help="absolute user-supplied NVIDIA NGX runtime directory")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--verbose", action="store_true", help="include local paths and observed hashes")
    args = parser.parse_args()
    report = assess(worker=args.worker, community_runtime=args.community_runtime,
                    official_runtime_dir=args.official_runtime_dir, verbose=args.verbose)
    print(json.dumps(report, indent=2) if args.as_json else format_summary(report))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
