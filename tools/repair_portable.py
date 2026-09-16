"""Bounded local repair/provisioning diagnostic for the portable layout.

This command never falls back to Conda or system tools and never downloads an
unverifiable runtime. It reports the exact missing component and the pinned
artifact required by the builder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    metadata = root / "tools" / "portable_toolchain.json"
    if not metadata.is_file():
        print(f"portable repair: missing toolchain metadata: {metadata}")
        return 1
    data = json.loads(metadata.read_text(encoding="utf-8"))
    missing = [
        root / "runtime" / "python" / "python.exe",
        root / "runtime" / "tools" / "ffmpeg" / "ffmpeg.exe",
        root / "runtime" / "tools" / "ffmpeg" / "ffprobe.exe",
    ]
    missing = [str(path.relative_to(root)) for path in missing if not path.is_file()]
    if not missing:
        print("portable repair: runtime layout is present; run check_portable_runtime.py")
        return 0
    print("portable repair: incomplete candidate")
    print("missing: " + ", ".join(missing))
    print("pinned Python artifact: " + data["python"]["archive"] + " (" + data["python"]["sha256"] + ")")
    print("pinned FFmpeg provider: " + data["ffmpeg"]["provider"] + " " + data["ffmpeg"]["version"])
    print("Use tools/build_portable_candidate.py with these verified external inputs.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
