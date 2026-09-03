"""Run the separate native standalone SR self-test."""

from __future__ import annotations

from .dlss_sr import DLSSSRBackend


def main() -> int:
    backend = DLSSSRBackend()
    try:
        print(backend.selftest())
        return 0
    except RuntimeError as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
