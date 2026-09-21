import ctypes
from pathlib import Path

import pytest

import src.backends.dlss5_v10_native as native
from src.backends.dlss5_v10_contract import (
    FORMAT_RGBA8,
    MEMORY_HOST,
    MEMORY_NONE,
    REQUIRED_EXPORTS,
)
from src.backends.dlss5_v10_protocol import CreateRequest
from src.backends.dlss5_v10_static import V10StaticStatus


class FakeFunction:
    def __init__(self, result=None):
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.result


class FakeLibrary:
    def __init__(self):
        for name in REQUIRED_EXPORTS:
            setattr(self, name, FakeFunction())
        self.dlss5nr_version.result = b"fake-v10"
        self.dlss5nr_gpu_name.result = b"Fake GPU"
        self.dlss5nr_adapter_luid.result = b"0000:0000"
        self.dlss5nr_frame_abi_version.result = 6
        self.dlss5nr_release_session = FakeFunction(1)


def test_v10_native_binding_sets_required_abi6_signatures():
    library = FakeLibrary()
    native.bind_required_exports(library)

    assert library.dlss5nr_process_frame_v6.restype is ctypes.c_int
    assert len(library.dlss5nr_process_frame_v6.argtypes) == 6
    assert library.dlss5nr_frame_abi_version.restype is ctypes.c_uint32
    assert library.dlss5nr_surface_create.restype is ctypes.c_void_p
    assert library.dlss5nr_surface_release.restype is None
    assert library.dlss5nr_release_session.restype is ctypes.c_int


def test_v10_native_load_is_blocked_before_loader_invocation(monkeypatch, tmp_path):
    called = False

    def fake_loader(path):
        nonlocal called
        called = True
        return FakeLibrary()

    monkeypatch.setattr(
        native,
        "verify_runtime_before_load",
        lambda runtime: tmp_path.resolve(),
    )
    with pytest.raises(native.V10NativeLoadDisabled, match="disabled"):
        native.load_bridge(tmp_path, loader=fake_loader)
    assert called is False


def test_v10_native_load_rechecks_static_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(
        native,
        "inspect_v10_runtime",
        lambda runtime: V10StaticStatus(
            "IDENTITY_MISMATCH", False, False, "changed bytes", {}
        ),
    )
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        native.verify_runtime_before_load(tmp_path)


def test_v10_native_fake_load_checks_runtime_abi(monkeypatch, tmp_path):
    library = FakeLibrary()
    monkeypatch.setattr(
        native,
        "verify_runtime_before_load",
        lambda runtime: tmp_path.resolve(),
    )
    bound = native.load_bridge(
        tmp_path,
        allow_native_load=True,
        loader=lambda path: library,
    )
    assert bound.version == "fake-v10"
    assert bound.frame_abi_version == 6
    assert bound.gpu_name == "Fake GPU"
    assert bound.adapter_luid == "0000:0000"


def test_v10_native_fake_load_rejects_wrong_runtime_abi(monkeypatch, tmp_path):
    library = FakeLibrary()
    library.dlss5nr_frame_abi_version.result = 5
    monkeypatch.setattr(
        native,
        "verify_runtime_before_load",
        lambda runtime: tmp_path.resolve(),
    )
    with pytest.raises(RuntimeError, match="bridge ABI 5"):
        native.load_bridge(
            tmp_path,
            allow_native_load=True,
            loader=lambda path: library,
        )


def test_v10_native_binding_is_only_reachable_inside_experimental_host_function():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "backends"
        / "dlss5_v10_host.py"
    ).read_text(encoding="utf-8")
    function = source.index("def experimental_native_server")
    native_import = source.index("from .dlss5_v10_native import V10NativeSession, load_bridge")
    assert native_import > function
    top_level = source[:function]
    assert "dlss5_v10_native" not in top_level
    assert "load_bridge" not in top_level
    assert 'if args.serve:' in source
    assert "return 78" in source


def test_v10_host_descriptor_builder_matches_upstream_host_rgba_contract():
    request = CreateRequest(
        64,
        64,
        gpu_ordinal=2,
        processing_scale=1.0,
        style=1,
        intensity=1.25,
        nr_passes=2,
        local_tone=0.8,
        local_structure=0.7,
        skin_structure=-0.5,
        color_strength=0.6,
        tone_preservation=0.2,
        face_skin_protection=0.3,
        grain_preservation=0.4,
        shimmer_suppression=0.5,
        automatic_mask=False,
        prefer_nvof=True,
    )
    source_bytes = bytearray(64 * 64 * 4)
    destination_bytes = bytearray(64 * 64 * 4)
    source, destination, owners = native.build_host_rgba_descriptors(
        request, source_bytes, destination_bytes, timestamp=123
    )

    assert source.memory_type == MEMORY_HOST
    assert source.pixel_format == FORMAT_RGBA8
    assert (source.width, source.height) == (64, 64)
    assert source.strides[0] == 64 * 4
    assert source.planes[0] != 0
    assert source.timestamp == 123

    assert destination.memory_type == MEMORY_HOST
    assert destination.pixel_format == FORMAT_RGBA8
    assert (destination.width, destination.height) == (64, 64)
    assert destination.strides[0] == 64 * 4
    assert destination.planes[0] != 0
    assert destination.timestamp == 123
    assert len(owners) == 2


def test_v10_render_parameter_builder_matches_create_contract():
    request = CreateRequest(
        64,
        64,
        style=2,
        intensity=1.5,
        nr_passes=4,
        local_tone=1.2,
        local_structure=0.9,
        skin_structure=-0.25,
        color_strength=0.75,
        tone_preservation=0.25,
        face_skin_protection=0.5,
        grain_preservation=0.4,
        shimmer_suppression=0.6,
        automatic_mask=True,
        prefer_nvof=True,
    )
    params = native.build_render_parameters(request, reset=True)
    assert params.style == 2
    assert params.intensity == pytest.approx(1.5)
    assert params.nr_passes == 4
    assert params.tone == pytest.approx(1.2)
    assert params.structure == pytest.approx(0.9)
    assert params.skin == pytest.approx(-0.25)
    assert params.color_strength == pytest.approx(0.75)
    assert params.tone_preservation == pytest.approx(0.25)
    assert params.face_skin_protection == pytest.approx(0.5)
    assert params.grain_preservation == pytest.approx(0.4)
    assert params.shimmer_suppression == pytest.approx(0.6)
    assert params.automask == 1
    assert params.reset == 1
    assert params.prefer_nvof == 1
    assert params.mask_memory_type == MEMORY_NONE
    assert params.mask_plane == 0


def test_v10_host_descriptor_builder_rejects_wrong_buffer_lengths():
    request = CreateRequest(64, 64)
    with pytest.raises(ValueError, match="source RGBA8 buffer"):
        native.build_host_rgba_descriptors(
            request,
            bytearray(1),
            bytearray(64 * 64 * 4),
            timestamp=0,
        )


def test_v10_native_session_fake_lifecycle_never_requires_shutdown(tmp_path):
    library = FakeLibrary()
    library.dlss5nr_init.result = 1
    library.dlss5nr_process_frame_v6.result = 1
    library.dlss5nr_release_session.result = 1
    bound = native.BoundBridge(
        library=library,
        version="fake-v10",
        frame_abi_version=6,
        gpu_name="Fake GPU",
        adapter_luid="fake-luid",
    )
    request = CreateRequest(64, 64, gpu_ordinal=3)
    session = native.V10NativeSession(bound, tmp_path, request)

    initialized = session.initialize()
    assert initialized["gpu_ordinal"] == 3
    assert initialized["bridge_abi_version"] == 6

    frame = native.FrameRequest(
        timestamp=77,
        reset=True,
        rgba=bytes([10, 20, 30, 255]) * (64 * 64),
    )
    output = session.process_frame(frame)
    assert (output.width, output.height) == (64, 64)
    assert output.timestamp == 77
    assert output.ngx_create_result == 0
    assert output.ngx_evaluate_result == 0
    assert output.cuda_result == 0
    assert output.rgba == bytes(64 * 64 * 4)
    assert session.close() == "CLOSED_RELEASED"

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "backends"
        / "dlss5_v10_native.py"
    ).read_text(encoding="utf-8")
    assert "NVSDK_NGX_D3D12_Shutdown" not in source
    assert "FreeLibrary" not in source


def test_v10_native_session_poison_skips_release(tmp_path):
    library = FakeLibrary()
    library.dlss5nr_init.result = 0
    release_calls = {"count": 0}

    def release():
        release_calls["count"] += 1
        return 1

    library.dlss5nr_release_session = release
    bound = native.BoundBridge(
        library=library,
        version="fake-v10",
        frame_abi_version=6,
        gpu_name="Fake GPU",
        adapter_luid="fake-luid",
    )
    session = native.V10NativeSession(
        bound, tmp_path, CreateRequest(64, 64)
    )
    with pytest.raises(native.V10NativeSessionError, match="initialization failed"):
        session.initialize()
    assert session.poisoned is True
    assert session.close() == "CLOSED_POISONED_RELEASE_SKIPPED"
    assert release_calls["count"] == 0



def test_v10_process_lifetime_close_skips_optional_release(tmp_path):
    library = FakeLibrary()
    release_calls = {"count": 0}

    def release():
        release_calls["count"] += 1
        return 0

    library.dlss5nr_release_session = release
    bound = native.BoundBridge(
        library=library,
        version="fake-v10",
        frame_abi_version=6,
        gpu_name="Fake GPU",
        adapter_luid="fake-luid",
    )
    session = native.V10NativeSession(
        bound, tmp_path, CreateRequest(64, 64)
    )

    assert session.close_process_lifetime() == "CLOSED_PROCESS_LIFETIME"
    assert session.closed is True
    assert release_calls["count"] == 0
