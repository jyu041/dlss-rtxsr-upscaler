"""Inspect a DLSS5 candidate archive without extracting or executing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import PurePosixPath
from pathlib import Path
import sys
import zipfile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def inspect(path: Path, expected_sha256: str | None = None) -> dict[str, object]:
    path = path.resolve()
    actual = sha256(path)
    if expected_sha256 and actual != expected_sha256.upper():
        raise ValueError(f"archive SHA-256 mismatch: {actual} != {expected_sha256.upper()}")
    seen: set[str] = set()
    files: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            normalized = str(PurePosixPath(name))
            if info.is_dir():
                continue
            if not name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                raise ValueError(f"unsafe archive member: {name}")
            if normalized in seen:
                raise ValueError(f"duplicate archive member: {name}")
            seen.add(normalized)
            files.append({"path": normalized, "size_bytes": info.file_size})
    binaries = [item for item in files if Path(str(item["path"])).suffix.lower() in {".dll", ".exe", ".sys", ".pyd"}]
    licenses = [item["path"] for item in files if "license" in str(item["path"]).lower() or "notice" in str(item["path"]).lower()]
    return {
        "archive": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": actual,
        "file_count": len(files),
        "binary_count": len(binaries),
        "binaries": binaries,
        "licenses_and_notices": sorted(licenses),
        "executed": False,
        "extracted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect(args.archive, args.sha256), indent=2))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"candidate inspection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
