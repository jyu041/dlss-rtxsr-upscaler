"""Explicit command-line lifecycle controls for manifest-managed runtimes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.runtime_manager import RuntimeManager


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "src" / "runtime_manager" / "manifest.json"
DEFAULT_INSTALL_ROOT = ROOT / "runtime"


def _manager(args: argparse.Namespace) -> RuntimeManager:
    return RuntimeManager(Path(args.manifest), Path(args.root))


def _progress(done: int, total: int | None) -> None:
    if total:
        print(f"download: {done}/{total} bytes ({done / total:.0%})", flush=True)
    else:
        print(f"download: {done} bytes", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or explicitly manage pinned optional runtimes.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="runtime manifest path")
    parser.add_argument("--root", default=str(DEFAULT_INSTALL_ROOT), help="managed runtime install root")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory", help="show lifecycle state without changing files")
    verify = commands.add_parser("verify", help="verify managed state without downloading")
    verify.add_argument("runtime_id")
    for name in ("install", "repair"):
        action = commands.add_parser(name, help=f"explicitly {name} a pinned upstream runtime")
        action.add_argument("runtime_id")
        action.add_argument("--archive-target", type=Path, help="temporary archive path for archive-based runtimes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manager = _manager(args)
        if args.command == "inventory":
            print(json.dumps(manager.inventory(), indent=2))
            return 0
        if args.command == "verify":
            result = manager.verify(args.runtime_id)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        method = getattr(manager, args.command)
        destination = method(args.runtime_id, target=args.archive_target, progress=_progress)
        print(f"{args.command}: {destination}")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"runtime command failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
