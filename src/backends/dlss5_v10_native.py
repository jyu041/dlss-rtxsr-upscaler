"""Reviewed ctypes binding plan for the pinned DLSS5 v10 bridge.

Importing this module performs no native load. The actual load function is
explicitly disabled unless allow_native_load=True, and the production host does
not call it at this milestone.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .dlss5_v10_contract import (
    BRIDGE_ABI_VERSION,
    FrameDescriptorV1,
    FrameResultV1,
    RenderParametersV6,
)
from .dlss5_v10_static import V10_EXPECTED_FILES, inspect_v10_runtime


class V10NativeLoadDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class BoundBridge:
    library: Any
    version: str
    frame_abi_version: int
    gpu_name: str
    adapter_luid: str


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def bind_required_exports(library: Any) -> None:
    """Bind the ABI-6 subset used/planned by the isolated host."""
    c_float_p = ctypes.POINTER(ctypes.c_float)

    library.dlss5nr_version.argtypes = []
    library.dlss5nr_version.restype = ctypes.c_char_p
    library.dlss5nr_gpu_name.argtypes = []
    library.dlss5nr_gpu_name.restype = ctypes.c_char_p
    library.dlss5nr_adapter_luid.argtypes = []
    library.dlss5nr_adapter_luid.restype = ctypes.c_char_p
    library.dlss5nr_frame_abi_version.argtypes = []
    library.dlss5nr_frame_abi_version.restype = ctypes.c_uint32

    library.dlss5nr_init.argtypes = [
        ctypes.c_int,
        ctypes.c_wchar_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_init.restype = ctypes.c_int
    library.dlss5nr_rebind.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_rebind.restype = ctypes.c_int

    library.dlss5nr_process_v6.argtypes = [
        c_float_p,
        c_float_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(RenderParametersV6),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_process_v6.restype = ctypes.c_int
    library.dlss5nr_process_cuda_v6.argtypes = [
        ctypes.c_uint64,
        ctypes.c_uint64,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.POINTER(RenderParametersV6),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_process_cuda_v6.restype = ctypes.c_int
    library.dlss5nr_cuda_supported.argtypes = []
    library.dlss5nr_cuda_supported.restype = ctypes.c_int
    library.dlss5nr_cuda_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.dlss5nr_cuda_status.restype = ctypes.c_int

    library.dlss5nr_process_frame_v6.argtypes = [
        ctypes.POINTER(FrameDescriptorV1),
        ctypes.POINTER(FrameDescriptorV1),
        ctypes.POINTER(RenderParametersV6),
        ctypes.POINTER(FrameResultV1),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_process_frame_v6.restype = ctypes.c_int
    library.dlss5nr_temporal_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.dlss5nr_temporal_status.restype = ctypes.c_int
    library.dlss5nr_scene_score_v1.argtypes = [
        ctypes.POINTER(FrameDescriptorV1),
        ctypes.c_float,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_scene_score_v1.restype = ctypes.c_int

    library.dlss5nr_surface_create.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    library.dlss5nr_surface_create.restype = ctypes.c_void_p
    library.dlss5nr_surface_frame_desc.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FrameDescriptorV1),
    ]
    library.dlss5nr_surface_frame_desc.restype = ctypes.c_int
    library.dlss5nr_surface_retain.argtypes = [ctypes.c_void_p]
    library.dlss5nr_surface_retain.restype = None
    library.dlss5nr_surface_release.argtypes = [ctypes.c_void_p]
    library.dlss5nr_surface_release.restype = None

    release = getattr(library, "dlss5nr_release_session", None)
    if release is not None:
        release.argtypes = []
        release.restype = ctypes.c_int


def verify_runtime_before_load(runtime_dir: str | Path) -> Path:
    runtime = Path(runtime_dir).expanduser().resolve()
    status = inspect_v10_runtime(runtime)
    if status.state != "STATIC_AUDIT_COMPLETE" or not status.valid:
        raise RuntimeError(
            f"DLSS5 v10 native pre-load identity gate failed: {status.state}; {status.detail}"
        )
    if status.execution_allowed:
        raise RuntimeError("static v10 inspector unexpectedly allowed native execution")
    return runtime


def load_bridge(
    runtime_dir: str | Path,
    *,
    allow_native_load: bool = False,
    loader: Callable[[str], Any] | None = None,
) -> BoundBridge:
    """Load and bind the exact bridge only after an explicit experimental gate.

    This function is intentionally not called by dlss5_v10_host.py yet.
    """
    runtime = verify_runtime_before_load(runtime_dir)
    if not allow_native_load:
        raise V10NativeLoadDisabled(
            "DLSS5 v10 native loading is disabled until the bounded hardware phase"
        )

    bridge = runtime / "neuroframe_engine_neural_rendering.dll"
    native_loader = loader
    if native_loader is None:
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("DLSS5 v10 native bridge requires Windows")
        native_loader = ctypes.WinDLL

    library = native_loader(str(bridge))
    bind_required_exports(library)

    version = _text(library.dlss5nr_version()) or "unknown"
    frame_abi = int(library.dlss5nr_frame_abi_version())
    if frame_abi != BRIDGE_ABI_VERSION:
        raise RuntimeError(
            f"DLSS5 v10 bridge ABI {frame_abi} != required {BRIDGE_ABI_VERSION}"
        )

    return BoundBridge(
        library=library,
        version=version,
        frame_abi_version=frame_abi,
        gpu_name=_text(library.dlss5nr_gpu_name()) or "unknown",
        adapter_luid=_text(library.dlss5nr_adapter_luid()),
    )


def pinned_runtime_hashes() -> dict[str, str]:
    return {
        name: str(record["sha256"])
        for name, record in V10_EXPECTED_FILES.items()
    }
