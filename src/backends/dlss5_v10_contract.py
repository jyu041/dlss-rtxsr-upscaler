"""Static Visual Enhancer v10 Neural Rendering bridge contract.

This module describes the ABI observed in Merserk/dlss5-visual-enhancer at
commit 7781107b89057f4d62d7c0a35fc3c1e90e7d9c31.  Importing it never loads a
native library and never executes DLSS5 code.
"""

from __future__ import annotations

import ctypes


UPSTREAM_COMMIT = "7781107b89057f4d62d7c0a35fc3c1e90e7d9c31"
BRIDGE_ABI_VERSION = 6

MEMORY_HOST = 0
MEMORY_CUDA = 1
MEMORY_NONE = 2

FORMAT_RGBA8 = 1
FORMAT_NV12 = 2
FORMAT_P010 = 3

REQUIRED_EXPORTS = (
    "dlss5nr_version",
    "dlss5nr_gpu_name",
    "dlss5nr_adapter_luid",
    "dlss5nr_frame_abi_version",
    "dlss5nr_init",
    "dlss5nr_rebind",
    "dlss5nr_process_v6",
    "dlss5nr_process_cuda_v6",
    "dlss5nr_process_frame_v6",
    "dlss5nr_temporal_status",
    "dlss5nr_scene_score_v1",
    "dlss5nr_surface_create",
    "dlss5nr_surface_frame_desc",
    "dlss5nr_surface_retain",
    "dlss5nr_surface_release",
)

OPTIONAL_EXPORTS = (
    "dlss5nr_release_session",
)


class FrameDescriptorV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("memory_type", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("planes", ctypes.c_uint64 * 3),
        ("strides", ctypes.c_uint32 * 3),
        ("color_matrix", ctypes.c_uint32),
        ("color_range", ctypes.c_uint32),
        ("rotation", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("timestamp", ctypes.c_int64),
    ]

    @classmethod
    def empty(cls) -> "FrameDescriptorV1":
        value = cls()
        value.struct_size = ctypes.sizeof(cls)
        value.abi_version = BRIDGE_ABI_VERSION
        return value


class RenderParametersV3(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("style", ctypes.c_int32),
        ("intensity", ctypes.c_float),
        ("tone", ctypes.c_float),
        ("structure", ctypes.c_float),
        ("skin", ctypes.c_float),
        ("automask", ctypes.c_int32),
        ("reset", ctypes.c_int32),
        ("color_strength", ctypes.c_float),
        ("tone_preservation", ctypes.c_float),
        ("mask_memory_type", ctypes.c_uint32),
        ("mask_width", ctypes.c_uint32),
        ("mask_height", ctypes.c_uint32),
        ("mask_stride", ctypes.c_uint32),
        ("mask_plane", ctypes.c_uint64),
    ]


class RenderParametersV4(ctypes.Structure):
    _fields_ = [
        *RenderParametersV3._fields_,
        ("face_skin_protection", ctypes.c_float),
        ("grain_preservation", ctypes.c_float),
    ]


class RenderParametersV5(ctypes.Structure):
    _fields_ = [
        *RenderParametersV4._fields_,
        ("nr_passes", ctypes.c_int32),
    ]


class RenderParametersV6(ctypes.Structure):
    _fields_ = [
        *RenderParametersV5._fields_,
        ("shimmer_suppression", ctypes.c_float),
        ("prefer_nvof", ctypes.c_int32),
    ]

    @classmethod
    def defaults(cls) -> "RenderParametersV6":
        value = cls()
        value.struct_size = ctypes.sizeof(cls)
        value.abi_version = BRIDGE_ABI_VERSION
        return value


class FrameResultV1(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("ngx_create_result", ctypes.c_int32),
        ("ngx_evaluate_result", ctypes.c_int32),
        ("cuda_result", ctypes.c_int32),
        ("scene_reset", ctypes.c_int32),
        ("scene_score", ctypes.c_float),
        ("reserved", ctypes.c_uint32),
        ("upload_bytes", ctypes.c_uint64),
        ("download_bytes", ctypes.c_uint64),
        ("timestamp", ctypes.c_int64),
    ]

    @classmethod
    def empty(cls) -> "FrameResultV1":
        value = cls()
        value.struct_size = ctypes.sizeof(cls)
        value.abi_version = BRIDGE_ABI_VERSION
        return value


EXPECTED_STRUCT_SIZES = {
    "FrameDescriptorV1": 88,
    "RenderParametersV3": 72,
    "RenderParametersV4": 80,
    "RenderParametersV5": 88,
    "RenderParametersV6": 96,
    "FrameResultV1": 56,
}


def struct_sizes() -> dict[str, int]:
    return {
        "FrameDescriptorV1": ctypes.sizeof(FrameDescriptorV1),
        "RenderParametersV3": ctypes.sizeof(RenderParametersV3),
        "RenderParametersV4": ctypes.sizeof(RenderParametersV4),
        "RenderParametersV5": ctypes.sizeof(RenderParametersV5),
        "RenderParametersV6": ctypes.sizeof(RenderParametersV6),
        "FrameResultV1": ctypes.sizeof(FrameResultV1),
    }


def validate_static_contract() -> None:
    actual = struct_sizes()
    if actual != EXPECTED_STRUCT_SIZES:
        raise RuntimeError(
            f"DLSS5 v10 ABI layout mismatch: actual={actual}, expected={EXPECTED_STRUCT_SIZES}"
        )
