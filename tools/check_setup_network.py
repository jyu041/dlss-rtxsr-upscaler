"""Fail-fast network/proxy checks for setup-time upstream downloads.

This does not bypass configured proxies. It detects the known local discard
proxy pattern (127.0.0.1/localhost/::1 on port 9) that makes Conda/urllib retry
for a long time, and reports an actionable error instead.
"""

from __future__ import annotations

import argparse
import urllib.parse
import urllib.request

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DISCARD_PORT = 9


def _parsed_proxy(value: str) -> urllib.parse.SplitResult:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = "http://" + candidate
    return urllib.parse.urlsplit(candidate)


def blocked_discard_proxies() -> dict[str, str]:
    blocked: dict[str, str] = {}
    for scheme, value in urllib.request.getproxies().items():
        if not value or scheme.lower() not in {"http", "https", "all"}:
            continue
        try:
            parsed = _parsed_proxy(value)
            host = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            continue
        if host in LOOPBACK_HOSTS and port == DISCARD_PORT:
            blocked[scheme] = value
    return blocked


def require_download_network_context() -> None:
    blocked = blocked_discard_proxies()
    if not blocked:
        return
    details = ", ".join(f"{scheme}={value}" for scheme, value in sorted(blocked.items()))
    raise RuntimeError(
        "setup download is blocked by a local discard proxy "
        f"({details}). This commonly appears in sandboxed/automation shells. "
        "Run setup from a normal interactive shell with network access, or provide "
        "the exact pinned DLSS5 v3 archive through NVE_DLSS5_ARCHIVE. The project "
        "will not silently bypass a configured proxy/security boundary."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-download", action="store_true")
    args = parser.parse_args()
    if args.require_download:
        try:
            require_download_network_context()
        except RuntimeError as exc:
            print(f"NETWORK BLOCKED: {exc}")
            return 2
    print("Setup network/proxy preflight: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
