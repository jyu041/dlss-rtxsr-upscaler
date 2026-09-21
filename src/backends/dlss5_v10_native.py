"""Reviewed ctypes binding plan for the pinned DLSS5 v10 bridge.

Importing this module performs no native load. Native loading remains explicit:
callers must pass allow_native_load=True after the surrounding v10 preflight and
execution gates have been satisfied.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .dlss5_v10_contract import (
    BRIDGE_ABI_VERSION,
    FORMAT_RGBA8,
    MEMORY_HOST,
    MEMORY_NONE,
    FrameDescriptorV1,
    FrameResultV1,
    RenderParametersV6,
)
from .dlss5_v10_protocol import (
    CreateRequest,
    FrameRequest,
    OutputEvidence,
    rgba_bytes,
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
    """Bind the ABI-6 subset used by the isolated v10 host."""
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


def build_host_rgba_descriptors(
    request: CreateRequest,
    source_bytes: bytearray,
    destination_bytes: bytearray,
    *,
    timestamp: int,
) -> tuple[FrameDescriptorV1, FrameDescriptorV1, tuple[Any, Any]]:
    """Build source/destination ABI descriptors without invoking native code."""
    request.validate()
    output_width, output_height = request.output_size
    expected_source = rgba_bytes(request.input_width, request.input_height)
    expected_destination = rgba_bytes(output_width, output_height)
    if len(source_bytes) != expected_source:
        raise ValueError(
            f"source RGBA8 buffer is {len(source_bytes)} bytes; expected {expected_source}"
        )
    if len(destination_bytes) != expected_destination:
        raise ValueError(
            f"destination RGBA8 buffer is {len(destination_bytes)} bytes; expected {expected_destination}"
        )

    source_owner = (ctypes.c_ubyte * len(source_bytes)).from_buffer(source_bytes)
    destination_owner = (ctypes.c_ubyte * len(destination_bytes)).from_buffer(destination_bytes)

    source = FrameDescriptorV1.empty()
    source.memory_type = MEMORY_HOST
    source.pixel_format = FORMAT_RGBA8
    source.width = request.input_width
    source.height = request.input_height
    source.planes[0] = ctypes.addressof(source_owner)
    source.strides[0] = request.input_width * 4
    source.timestamp = int(timestamp)

    destination = FrameDescriptorV1.empty()
    destination.memory_type = MEMORY_HOST
    destination.pixel_format = FORMAT_RGBA8
    destination.width = output_width
    destination.height = output_height
    destination.planes[0] = ctypes.addressof(destination_owner)
    destination.strides[0] = output_width * 4
    destination.timestamp = int(timestamp)

    return source, destination, (source_owner, destination_owner)


def build_render_parameters(
    request: CreateRequest,
    *,
    reset: bool,
) -> RenderParametersV6:
    request.validate()
    value = RenderParametersV6.defaults()
    value.style = request.style
    value.intensity = float(request.intensity)
    value.tone = float(request.local_tone)
    value.structure = float(request.local_structure)
    value.skin = float(request.skin_structure)
    value.automask = int(request.automatic_mask)
    value.reset = int(bool(reset))
    value.color_strength = float(request.color_strength)
    value.tone_preservation = float(request.tone_preservation)
    value.face_skin_protection = float(request.face_skin_protection)
    value.grain_preservation = float(request.grain_preservation)
    value.nr_passes = request.nr_passes
    value.shimmer_suppression = float(request.shimmer_suppression)
    value.prefer_nvof = int(request.prefer_nvof)
    value.mask_memory_type = MEMORY_NONE
    value.mask_width = 0
    value.mask_height = 0
    value.mask_stride = 0
    value.mask_plane = 0
    return value


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

    The isolated host calls this only from acknowledged, preflight-validated
    bounded or application execution modes.
    """
    runtime = verify_runtime_before_load(runtime_dir)
    if not allow_native_load:
        raise V10NativeLoadDisabled(
            "DLSS5 v10 native loading is disabled without an explicit acknowledged execution gate"
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


class V10NativeSessionError(RuntimeError):
    pass


class V10NativeSession:
    """One-process, one-CREATE host-memory ABI-6 session.

    The isolated v10 host owns this session for bounded research and the
    explicitly acknowledged application path. Parent-process timeout/termination
    remains the hard watchdog for native hangs.
    """

    def __init__(
        self,
        bound: BoundBridge,
        runtime_dir: str | Path,
        request: CreateRequest,
    ) -> None:
        self.bound = bound
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.request = request.validate()
        self.initialized = False
        self.closed = False
        self.poisoned = False
        self.poison_reason: str | None = None

    def _poison(self, reason: str) -> None:
        self.poisoned = True
        self.poison_reason = str(reason)[:2048] or "unspecified native failure"

    def _require_live(self) -> None:
        if self.closed:
            raise V10NativeSessionError("v10 native session is closed")
        if self.poisoned:
            raise V10NativeSessionError(
                f"v10 native session is poisoned: {self.poison_reason}"
            )

    def initialize(self) -> dict[str, object]:
        self._require_live()
        if self.initialized:
            raise V10NativeSessionError("v10 native session is already initialized")
        error = ctypes.create_string_buffer(4096)
        try:
            ok = self.bound.library.dlss5nr_init(
                self.request.gpu_ordinal,
                str(self.runtime_dir),
                error,
                len(error),
            )
        except BaseException as exc:
            self._poison(f"native initialization exception: {exc}")
            raise V10NativeSessionError(self.poison_reason) from exc
        if not ok:
            detail = _text(error.value) or "unknown initialization failure"
            self._poison(detail)
            raise V10NativeSessionError(
                f"Feature-18 bridge initialization failed: {detail}"
            )
        self.initialized = True
        return {
            "bridge_version": self.bound.version,
            "bridge_abi_version": self.bound.frame_abi_version,
            "gpu_name": _text(self.bound.library.dlss5nr_gpu_name()) or self.bound.gpu_name,
            "adapter_luid": _text(self.bound.library.dlss5nr_adapter_luid()) or self.bound.adapter_luid,
            "gpu_ordinal": self.request.gpu_ordinal,
        }

    def process_frame(self, frame: FrameRequest) -> OutputEvidence:
        self._require_live()
        if not self.initialized:
            raise V10NativeSessionError("v10 native session is not initialized")
        frame.validate(self.request.input_width, self.request.input_height)

        source_bytes = bytearray(frame.rgba)
        output_width, output_height = self.request.output_size
        destination_bytes = bytearray(rgba_bytes(output_width, output_height))
        source, destination, owners = build_host_rgba_descriptors(
            self.request,
            source_bytes,
            destination_bytes,
            timestamp=frame.timestamp,
        )
        params = build_render_parameters(self.request, reset=frame.reset)
        result = FrameResultV1.empty()
        error = ctypes.create_string_buffer(4096)

        try:
            ok = self.bound.library.dlss5nr_process_frame_v6(
                ctypes.byref(source),
                ctypes.byref(destination),
                ctypes.byref(params),
                ctypes.byref(result),
                error,
                len(error),
            )
            # Keep host buffers alive through return from native code.
            _ = owners
        except BaseException as exc:
            self._poison(f"native evaluation exception: {exc}")
            raise V10NativeSessionError(self.poison_reason) from exc

        if not ok:
            detail = _text(error.value) or "unknown Feature-18 evaluation failure"
            self._poison(detail)
            raise V10NativeSessionError(
                f"Feature-18 evaluation failed: {detail}"
            )

        return OutputEvidence(
            width=output_width,
            height=output_height,
            timestamp=int(result.timestamp or frame.timestamp),
            ngx_create_result=int(result.ngx_create_result),
            ngx_evaluate_result=int(result.ngx_evaluate_result),
            cuda_result=int(result.cuda_result),
            scene_reset=int(result.scene_reset),
            scene_score=float(result.scene_score),
            upload_bytes=int(result.upload_bytes),
            download_bytes=int(result.download_bytes),
            rgba=bytes(destination_bytes),
        )

    def close(self) -> str:
        if self.closed:
            return "ALREADY_CLOSED"
        self.closed = True
        release = getattr(self.bound.library, "dlss5nr_release_session", None)
        if release is None:
            return "CLOSED_NO_RELEASE_EXPORT"
        if self.poisoned:
            return "CLOSED_POISONED_RELEASE_SKIPPED"
        try:
            ok = release()
        except BaseException as exc:
            self._poison(f"session release exception: {exc}")
            return "CLOSED_RELEASE_EXCEPTION"
        if not ok:
            self._poison("session release returned failure")
            return "CLOSED_RELEASE_FAILED"
        return "CLOSED_RELEASED"

    def close_process_lifetime(self) -> str:
        """Close the logical session without invoking optional native teardown.

        The v10 application host is an isolated, single-job process and the
        audited upstream lifecycle keeps D3D12/NGX state process-lifetime after
        Feature-18 evaluation. The process boundary therefore owns final native
        teardown. Calling the optional release export here can itself fail after
        an otherwise successful render and must not be a prerequisite for
        returning the completed video.
        """
        if self.closed:
            return "ALREADY_CLOSED"
        self.closed = True
        return "CLOSED_PROCESS_LIFETIME"

    def __enter__(self) -> "V10NativeSession":
        self.initialize()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def pinned_runtime_hashes() -> dict[str, str]:
    return {
        name: str(record["sha256"])
        for name, record in V10_EXPECTED_FILES.items()
    }
