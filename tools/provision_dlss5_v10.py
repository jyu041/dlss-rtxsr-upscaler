"""Provision the preferred DLSS 5 v10 runtime for normal application use.

This is the single setup/repair entry point for DLSS 5. It downloads (or
accepts) the exact pinned v10 archive, verifies it through Runtime Manager,
stages only the allowlisted runtime payload, performs the required Microsoft
Defender preflight, and verifies that the application-facing backend is ready.

The verified archive is retained under runtime/downloads so a stale Defender
preflight can be refreshed locally without another network download.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backends.dlss5_v10_app import DLSS5V10ExperimentalBackend  # noqa: E402
from src.runtime_manager.core import RuntimeManager, verify_artifact  # noqa: E402
from tools.prepare_dlss5_v10_candidate import (  # noqa: E402
    DEFAULT_ARCHIVE,
    DEFAULT_DESTINATION,
    DEFAULT_REPORT,
    MANIFEST,
    RUNTIME_ID,
    stage_candidate,
)


def _progress(done: int, total: int | None) -> None:
    if total:
        percent = min(100, int(done * 100 / total))
        print(f"DLSS 5 download: {done}/{total} bytes ({percent}%)", flush=True)
    else:
        print(f"DLSS 5 download: {done} bytes", flush=True)


def _cache_supplied_archive(source: Path) -> Path:
    source = Path(source).expanduser().resolve()
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    spec = manager.specs[RUNTIME_ID]
    verify_artifact(source, spec)

    destination = DEFAULT_ARCHIVE.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source == destination:
        return destination

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    try:
        verify_artifact(temporary, spec)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def ensure_cached_archive(
    archive: Path | None = None,
    *,
    allow_download: bool = True,
) -> Path:
    """Return the exact pinned archive at the canonical local cache path."""
    manager = RuntimeManager(MANIFEST, ROOT / "runtime")
    spec = manager.specs[RUNTIME_ID]
    canonical = DEFAULT_ARCHIVE.resolve()

    if archive is not None:
        return _cache_supplied_archive(Path(archive))

    if canonical.is_file():
        try:
            verify_artifact(canonical, spec)
            return canonical
        except Exception:
            canonical.unlink(missing_ok=True)

    if not allow_download:
        raise RuntimeError(
            f"verified DLSS 5 v10 archive is not cached at {canonical}"
        )

    print("Downloading the pinned DLSS 5 v10 runtime...", flush=True)
    return manager.download(RUNTIME_ID, canonical, progress=_progress)


def prepare_dlss5_v10(
    archive: Path | None = None,
    *,
    allow_download: bool = True,
) -> dict[str, object]:
    """Make the preferred DLSS 5 runtime application-ready."""
    cached = ensure_cached_archive(archive, allow_download=allow_download)
    report = stage_candidate(
        cached,
        destination=DEFAULT_DESTINATION,
        report_path=DEFAULT_REPORT,
    )
    status = DLSS5V10ExperimentalBackend().status()
    if not status.available:
        raise RuntimeError(
            f"DLSS 5 v10 staging completed but backend is not ready: "
            f"{status.state} — {status.reason}"
        )
    return {
        "archive": str(cached),
        "runtime": str(DEFAULT_DESTINATION),
        "preflight": str(DEFAULT_REPORT),
        "state": status.state,
        "reason": status.reason,
        "report": report,
    }


def refresh_preflight_from_cache() -> bool:
    """Refresh a stale/missing local preflight without network access.

    Returns True only when the preferred backend is ready afterwards.
    """
    try:
        prepare_dlss5_v10(allow_download=False)
    except Exception:
        return False
    return DLSS5V10ExperimentalBackend().status().available


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="optional exact pinned v10 archive; copied into the managed cache",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="use only an already-cached or explicitly supplied archive",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = prepare_dlss5_v10(
            args.archive,
            allow_download=not args.no_download,
        )
    except Exception as exc:
        print(f"DLSS 5 provisioning failed: {exc}", file=sys.stderr)
        return 1

    print(f"DLSS 5: {result['state']} — {result['reason']}")
    print("DLSS 5 setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
