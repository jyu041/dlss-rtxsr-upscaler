"""Non-executing isolated-host scaffold for DLSS5 v10.

Only --contract-selftest is implemented. --serve is intentionally blocked so
no v10 DLL can be loaded during this milestone.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .dlss5_v10_contract import (
    BRIDGE_ABI_VERSION,
    EXPECTED_STRUCT_SIZES,
    REQUIRED_EXPORTS,
    validate_static_contract,
)
from .dlss5_v10_protocol import MAGIC, PROTOCOL_VERSION
from .dlss5_v10_static import V10_EXPECTED_FILES


def contract_report() -> dict[str, object]:
    validate_static_contract()
    return {
        "status": "PASS",
        "native_loaded": False,
        "execution_allowed": False,
        "protocol_magic": MAGIC.decode("ascii"),
        "protocol_version": PROTOCOL_VERSION,
        "bridge_abi_version": BRIDGE_ABI_VERSION,
        "struct_sizes": EXPECTED_STRUCT_SIZES,
        "required_exports": list(REQUIRED_EXPORTS),
        "expected_files": V10_EXPECTED_FILES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-selftest", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args(argv)

    if args.contract_selftest:
        print(json.dumps(contract_report(), indent=2, sort_keys=True))
        return 0

    if args.serve:
        print(
            "BLOCKED: DLSS5 v10 host execution is not implemented at the "
            "static-adapter milestone.",
            file=sys.stderr,
        )
        return 78

    parser.error("choose --contract-selftest")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
