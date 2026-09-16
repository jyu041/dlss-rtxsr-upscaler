"""Offline manifest audit; network verification is intentionally opt-in and separate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.runtime_manager.core import RuntimeManager


def audit(manifest: Path) -> list[str]:
    manager = RuntimeManager(manifest, Path("runtime"))
    errors: list[str] = []
    destinations: set[str] = set()
    identities: dict[str, str] = {}
    for runtime_id, spec in manager.specs.items():
        folded_destination = spec.destination.casefold()
        if folded_destination in destinations:
            errors.append(f"destination collision: {spec.destination}")
        destinations.add(folded_destination)
        for item in spec.files:
            if item.url.lower().startswith("http://"):
                errors.append(f"non-HTTPS file URL: {runtime_id}:{item.path}")
            previous = identities.get(item.sha256)
            if previous and previous != f"{runtime_id}:{item.path}":
                errors.append(f"unexpected identity alias: {previous} == {runtime_id}:{item.path}")
            identities[item.sha256] = f"{runtime_id}:{item.path}"
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit committed runtime manifest metadata without network access")
    parser.add_argument("--manifest", type=Path, default=Path("src/runtime_manager/manifest.json"))
    args = parser.parse_args(argv)
    errors = audit(args.manifest)
    print(json.dumps({"manifest": str(args.manifest), "errors": errors, "ok": not errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
