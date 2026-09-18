import ctypes
from pathlib import Path

import pytest

import src.backends.dlss5_v10_native as native
from src.backends.dlss5_v10_contract import REQUIRED_EXPORTS
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


def test_v10_production_host_does_not_import_native_binding_module():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "backends"
        / "dlss5_v10_host.py"
    ).read_text(encoding="utf-8")
    assert "dlss5_v10_native" not in source
    assert "load_bridge" not in source
