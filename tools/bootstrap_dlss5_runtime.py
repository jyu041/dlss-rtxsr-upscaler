"""Install the DLSS 5 v3 runtime used by the retained protocol client.

The archive is downloaded directly from the upstream DLSS 5 Visual Enhancer
GitHub release.  This project does not re-host those third-party binaries.
Integrity verification is automatic; there is no user approval manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TARGET = ROOT / "runtime" / "dlss5-v3"
RELEASE_URL = (
    "https://github.com/Merserk/dlss5-visual-enhancer/releases/download/3.0/"
    "DLSS.5.Visual.Enhancer.v3.0.zip"
)
RELEASE_SIZE = 466_919_995
RELEASE_SHA256 = "6F0590D81677484F4ECDFaa5C44FC2A0E1A3835D33EEFC59D656E6C3BCF35F6A".upper()
RUNTIME_MARKER = "bin/runtime/"
REQUIRED_RUNTIME_FILES = (
    "nvngx.dll",
    "dxgi.dll",
    "renodx-dlss5.addon64",
    "nvngx_dlss.dll",
    "nvngx_dlssnr.dll",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def runtime_complete(path: Path = RUNTIME_TARGET) -> bool:
    return path.is_dir() and all((path / name).is_file() for name in REQUIRED_RUNTIME_FILES)


def _safe_relative(value: str) -> bool:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ":" in normalized:
        return False
    return all(part not in {"", "."} for part in path.parts)


def _relative_after_marker(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    lower = normalized.lower()
    index = lower.find(RUNTIME_MARKER)
    if index < 0:
        return None
    relative = normalized[index + len(RUNTIME_MARKER) :]
    return relative if _safe_relative(relative) else None


def _download(target: Path) -> Path:
    request = urllib.request.Request(RELEASE_URL, headers={"User-Agent": "NVIDIA-Video-Enhancer-setup"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        final_url = str(response.geturl())
        if not final_url.lower().startswith("https://"):
            raise RuntimeError(f"DLSS5 download redirected to non-HTTPS URL: {final_url}")
        copied = 0
        total = int(response.headers.get("Content-Length", "0")) or None
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            copied += len(block)
            if total:
                print(f"\rDLSS5 download: {copied / total:.0%} ({copied / 1e6:.1f}/{total / 1e6:.1f} MB)", end="", flush=True)
            else:
                print(f"\rDLSS5 download: {copied / 1e6:.1f} MB", end="", flush=True)
    print()
    if target.stat().st_size != RELEASE_SIZE:
        raise RuntimeError(f"DLSS5 archive size mismatch: {target.stat().st_size} != {RELEASE_SIZE}")
    actual = sha256_file(target)
    if actual != RELEASE_SHA256:
        raise RuntimeError(f"DLSS5 archive integrity check failed: {actual}")
    return target


def _extract_runtime(archive_path: Path, staging: Path) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _relative_after_marker(info.filename)
            if relative is None:
                continue
            folded = relative.casefold()
            if folded in seen:
                raise RuntimeError(f"Duplicate DLSS5 runtime archive entry: {relative}")
            seen.add(folded)
            target = staging / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if not seen:
        raise RuntimeError("DLSS5 archive contains no bin/runtime payload")
    missing = [name for name in REQUIRED_RUNTIME_FILES if not (staging / name).is_file()]
    if missing:
        raise RuntimeError("DLSS5 archive is missing required runtime files: " + ", ".join(missing))


def _activate(staging: Path, destination: Path = RUNTIME_TARGET) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
        if not runtime_complete(destination):
            raise RuntimeError("DLSS5 runtime activation produced an incomplete runtime")
        if backup.exists():
            shutil.rmtree(backup)
        return destination
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if had_previous and backup.exists():
            os.replace(backup, destination)
        raise


def install_from_archive(archive_path: Path) -> Path:
    parent = RUNTIME_TARGET.parent
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="dlss5-v3-", dir=parent))
    staging = workspace / "payload"
    try:
        _extract_runtime(archive_path, staging)
        result = _activate(staging)
        return result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def install_from_directory(source: Path) -> Path:
    source = source.expanduser().resolve()
    missing = [name for name in REQUIRED_RUNTIME_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"{source} is not a complete DLSS5 runtime; missing: {', '.join(missing)}")
    parent = RUNTIME_TARGET.parent
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="dlss5-v3-", dir=parent))
    staging = workspace / "payload"
    try:
        shutil.copytree(source, staging)
        return _activate(staging)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the supported DLSS5 v3 runtime automatically.")
    parser.add_argument("--check", action="store_true", help="only check whether the managed runtime is complete")
    parser.add_argument("--runtime-dir", type=Path, help="copy an existing compatible bin/runtime directory instead of downloading")
    args = parser.parse_args(argv)

    if args.check:
        print(str(RUNTIME_TARGET) if runtime_complete() else "NOT_INSTALLED")
        return 0 if runtime_complete() else 1
    if runtime_complete() and args.runtime_dir is None:
        print(f"DLSS5 runtime already installed: {RUNTIME_TARGET}")
        return 0
    if args.runtime_dir is not None:
        result = install_from_directory(args.runtime_dir)
        print(f"DLSS5 runtime installed from existing directory: {result}")
        return 0

    with tempfile.TemporaryDirectory(prefix="nve-dlss5-download-") as temporary:
        archive = _download(Path(temporary) / "DLSS.5.Visual.Enhancer.v3.0.zip")
        result = install_from_archive(archive)
    print(f"DLSS5 runtime installed from upstream GitHub release: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
