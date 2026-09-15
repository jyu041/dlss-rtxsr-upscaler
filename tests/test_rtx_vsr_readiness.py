from types import SimpleNamespace

from src.core.rtx_vsr_readiness import inspect_api


def _module(*missing):
    names = {prefix + quality for prefix in ("", "HIGHBITRATE_", "DEBLUR_", "DENOISE_") for quality in ("LOW", "MEDIUM", "HIGH", "ULTRA")} - set(missing)
    quality = SimpleNamespace(**{name: name for name in names})
    return SimpleNamespace(__version__="0.1.0.1", get_sdk_version=lambda: "1.2.0", VideoSuperRes=SimpleNamespace(QualityLevel=quality))


def test_vsr_import_is_only_static_readiness():
    status = inspect_api(_module())
    assert status.state == "STATICALLY READY"
    assert status.available
    assert "GPU" not in status.reason


def test_vsr_capability_probe_reports_missing_mode():
    status = inspect_api(_module("DEBLUR_ULTRA"))
    assert status.state == "UNSUPPORTED API"
    assert not status.available
    assert "DEBLUR_ULTRA" in status.reason


def test_vsr_wrong_package_version_is_unvalidated():
    module = _module()
    module.__version__ = "9.9.9"
    status = inspect_api(module)
    assert status.state == "UNVALIDATED PACKAGE"
    assert not status.available


def test_vsr_wrong_sdk_version_is_unvalidated():
    module = _module()
    module.get_sdk_version = lambda: "9.9.9"
    status = inspect_api(module)
    assert status.state == "UNVALIDATED PACKAGE"
    assert not status.available
