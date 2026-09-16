from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

import src.backends.dlss5 as dlss5


class Session:
    def __init__(self, report, log):
        self._report = report
        self._log = log

    def feature_report(self):
        return self._report

    def reshade_log(self):
        return self._log


def report(*, verified=True, native_fallback=False, evidence=None):
    return {"verified": verified, "native_fallback": native_fallback, "evidence": evidence or []}


def test_feature18_verified_and_clean_passes():
    assert dlss5._validate_feature_report(Session(report(), "feature 18 evaluation succeeded"))["verified"]


def test_structured_native_fallback_fails():
    with pytest.raises(RuntimeError, match="fell back to the native path"):
        dlss5._validate_feature_report(Session(report(native_fallback=True), "feature 18 evaluation succeeded"))


def test_log_failure_and_native_path_fallback_fails():
    log = "feature 18 evaluate failed with 0xbad00005\nfollowing frames use the native path"
    with pytest.raises(RuntimeError, match="0xbad00005"):
        dlss5._validate_feature_report(Session(report(), log))


def test_unverified_feature18_fails():
    with pytest.raises(RuntimeError, match="verification failed"):
        dlss5._validate_feature_report(Session(report(verified=False), ""))


def test_ordinary_native_wording_is_not_a_false_positive():
    result = dlss5._validate_feature_report(Session(report(evidence=["native dimensions negotiated"]), "native dimensions negotiated"))
    assert result["verified"]


@pytest.mark.parametrize("generation", [40, 50])
def test_scaled_output_remains_available_for_unrestricted_generations(generation):
    assert dlss5.output_scale_supported({"generation": generation}, {"known_ampere_pair": True}, 2.0)


def test_rtx30_ampere_scaled_output_is_rejected_before_session_launch(monkeypatch):
    _fake_dlss_modules(monkeypatch, report(), "")
    backend = _backend(monkeypatch)
    backend.gpu = {"generation": 30, "name": "RTX 3070 Ti"}
    backend.bundle = {"known_ampere_pair": True}
    class ExplodingSession:
        def __init__(self, *args, **kwargs):
            raise AssertionError("DLSS5 session must not be constructed for a gated scale")
    __import__("sys").modules["dlss5.session"].DlssSession = ExplodingSession
    options = SimpleNamespace(upscaling_factor=2.0, flow_width=2, scene_change_threshold=0.0, wants_motion=lambda count: False)
    with pytest.raises(RuntimeError, match="output scaling above 1.0x"):
        list(backend.process_frames([np.zeros((2, 2, 4), dtype=np.uint8)], width=2, height=2, frame_count=1, options=options))


def _fake_dlss_modules(monkeypatch, report_value, log):
    package = ModuleType("dlss5")
    imaging = ModuleType("dlss5.imaging")
    imaging.fit_frame = lambda frame, width, height: frame
    motion = ModuleType("dlss5.motion")

    class Guide:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, frame):
            return SimpleNamespace(motion=None, reset=True, scene_score=0.0)

    motion.TemporalGuide = Guide
    session_module = ModuleType("dlss5.session")

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.render_width = kwargs.get("input_width", 2)
            self.render_height = kwargs.get("input_height", 2)
            self.output_width = self.render_width
            self.output_height = self.render_height
            self._closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def submit(self, *, rgba, **kwargs):
            return rgba, kwargs.get("pts", 0)

        def close(self):
            self._closed = True

        def feature_report(self):
            return report_value

        def reshade_log(self):
            return log

    session_module.DlssSession = FakeSession
    for name, module in (("dlss5", package), ("dlss5.imaging", imaging), ("dlss5.motion", motion), ("dlss5.session", session_module)):
        monkeypatch.setitem(__import__("sys").modules, name, module)


def _backend(monkeypatch):
    backend = dlss5.DLSS5Backend.__new__(dlss5.DLSS5Backend)
    backend.available = True
    backend.layout = object()
    backend.gpu = {"name": "test"}
    backend._require_ready = lambda: None
    monkeypatch.setattr(dlss5, "_client_root", lambda: None)
    return backend


def test_process_frame_applies_fail_closed_validator(monkeypatch):
    log = "feature 18 evaluate failed with 0xbad00005; following frames use the native path"
    _fake_dlss_modules(monkeypatch, report(), log)
    backend = _backend(monkeypatch)
    options = SimpleNamespace(upscaling_factor=1.0)
    with pytest.raises(RuntimeError, match="fell back to the native path"):
        backend.process_frame(np.zeros((2, 2, 4), dtype=np.uint8), options=options)


def test_process_frames_propagates_fail_closed_validator(monkeypatch):
    log = "feature 18 evaluate failed with 0xbad00005; following frames use the native path"
    _fake_dlss_modules(monkeypatch, report(), log)
    backend = _backend(monkeypatch)
    options = SimpleNamespace(upscaling_factor=1.0, flow_width=2, scene_change_threshold=0.0, wants_motion=lambda count: False)
    with pytest.raises(RuntimeError, match="fell back to the native path"):
        list(backend.process_frames([np.zeros((2, 2, 4), dtype=np.uint8)], width=2, height=2, frame_count=1, options=options))
