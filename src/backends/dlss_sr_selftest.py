"""Refuse the standalone SR self-test when the protocol cannot express it."""

from __future__ import annotations

from .dlss_sr import DLSSSRBackend


def main() -> int:
    backend = DLSSSRBackend()
    print(backend.status())
    print(backend.reason)
    print("No native worker was launched: a DLSS5 Feature-18 run is not evidence of standalone DLSS SR.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
