"""Fail-closed launcher check for the explicitly built portable runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--full", action="store_true", help="hash every recorded runtime file; use for repair/explicit verification")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    from src.core.portable_runtime import inspect

    result = inspect(root, full=args.full)
    print(f"portable runtime: {result['state']} — {result['detail']}")
    return 0 if result["state"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
