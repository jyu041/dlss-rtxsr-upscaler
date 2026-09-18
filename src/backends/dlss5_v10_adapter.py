"""Fail-closed parent-side plan for an isolated DLSS5 v10 host.

This milestone performs static identity/ABI validation and constructs the future
host launch contract. It deliberately contains no native-load implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from .dlss5_v10_static import V10_EXPECTED_FILES, inspect_v10_runtime


ROOT = Path(__file__).resolve().parents[2]
MANAGED_DESTINATION = ROOT / "runtime" / "dlss5" / "neuroframe-v10-candidate"
MANAGED_RUNTIME_RELATIVE = Path("bin") / "runtime" / "dlssnr"


class V10ExecutionDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class V10HostPlan:
    runtime_dir: Path
    bridge: Path
    caller_shim: Path
    neural_runtime: Path
    python: Path
    module: str
    protocol_version: int
    expected_hashes: dict[str, str]
    execution_allowed: bool = False

    @property
    def command(self) -> tuple[str, ...]:
        return (
            str(self.python),
            "-u",
            "-m",
            self.module,
            "--serve",
            "--runtime-dir",
            str(self.runtime_dir),
        )


def resolve_runtime_dir(root: str | Path = MANAGED_DESTINATION) -> Path:
    root = Path(root).expanduser().resolve()
    nested = root / MANAGED_RUNTIME_RELATIVE
    if nested.is_dir():
        return nested
    # Allow tests/development to point directly at the allowlisted directory.
    if all((root / name).is_file() for name in V10_EXPECTED_FILES):
        return root
    return nested


def prepare_host_plan(
    root: str | Path = MANAGED_DESTINATION,
    *,
    python: str | Path | None = None,
) -> V10HostPlan:
    runtime_dir = resolve_runtime_dir(root)
    status = inspect_v10_runtime(runtime_dir)
    if status.state != "STATIC_AUDIT_COMPLETE" or not status.valid:
        raise RuntimeError(
            f"DLSS5 v10 static host gate failed: {status.state}; {status.detail}"
        )
    if status.execution_allowed:
        raise RuntimeError("static v10 inspector unexpectedly allowed execution")

    from .dlss5_v10_protocol import PROTOCOL_VERSION

    expected_hashes = {
        name: str(record["sha256"])
        for name, record in V10_EXPECTED_FILES.items()
    }
    return V10HostPlan(
        runtime_dir=runtime_dir,
        bridge=runtime_dir / "neuroframe_engine_neural_rendering.dll",
        caller_shim=runtime_dir / "neuroframe_caller.dll",
        neural_runtime=runtime_dir / "nvngx_dlssnr.dll",
        python=Path(python or sys.executable).expanduser().resolve(),
        module="src.backends.dlss5_v10_host",
        protocol_version=PROTOCOL_VERSION,
        expected_hashes=expected_hashes,
        execution_allowed=False,
    )


def launch_host(*_args, **_kwargs):
    raise V10ExecutionDisabled(
        "DLSS5 v10 execution is disabled at the static-adapter milestone. "
        "Complete isolated host implementation and bounded RTX 30 validation first."
    )
