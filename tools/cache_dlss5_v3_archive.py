"""Fetch and persist the exact pinned DLSS 5 v3 upstream archive.

Normal setup uses this cache so a later provisioning/self-test retry does not
redownload the ~467 MB release. Existing cache entries are trusted only after
the same size and SHA-256 verification used by the provisioner.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_setup_network import require_download_network_context
from tools.provision_dlss5_v3 import download_archive, verify_archive

CACHE_ARCHIVE = (
    ROOT
    / "runtime"
    / "cache"
    / "dlss5-v3"
    / "DLSS.5.Visual.Enhancer.v3.0.zip"
)


def ensure_cached_archive() -> Path:
    if CACHE_ARCHIVE.is_file():
        try:
            verify_archive(CACHE_ARCHIVE)
        except (OSError, ValueError):
            CACHE_ARCHIVE.unlink(missing_ok=True)
        else:
            print(f"Using verified cached DLSS5 v3 archive: {CACHE_ARCHIVE}")
            return CACHE_ARCHIVE

    require_download_network_context()
    print(f"Downloading pinned DLSS5 v3 archive to cache: {CACHE_ARCHIVE}")
    download_archive(CACHE_ARCHIVE)
    verify_archive(CACHE_ARCHIVE)
    return CACHE_ARCHIVE


def main() -> int:
    try:
        path = ensure_cached_archive()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"DLSS5 v3 archive cache failed: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
