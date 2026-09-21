import pytest

from src.backends.base import BackendStatus
from src.backends import dlss5_unified as backend_module
from src.video import dlss5_unified as video


class _Selector:
    def __init__(self, name, implementation):
        self.name = name
        self.implementation = implementation

    def runtime(self):
        return self.name, self.implementation


class _Legacy:
    def options(self, **values):
        return values


def test_unified_renderer_prefers_v10_and_passes_shared_pipeline_controls(monkeypatch):
    captured = {}

    def fake_render(source, destination, implementation, **kwargs):
        captured.update(kwargs)
        return {
            "frames": 3,
            "fps": 10.0,
            "dimensions": (640, 480),
            "audio_preserved": False,
        }

    monkeypatch.setattr(video, "render_dlss5_v10", fake_render)
    result = video.render_dlss5_unified(
        "in.mp4",
        "out.mp4",
        _Selector("v10", object()),
        nr_working_scale=0.75,
        recompose_backend="cuda",
        temporal_stabilization=0.5,
        color_strength=0.8,
        tone_preservation=0.2,
        nr_passes=4,
        face_skin_protection=0.3,
        grain_preservation=0.4,
        native_shimmer_suppression=0.6,
        prefer_nvof=True,
    )

    assert result["dlss5_runtime"] == "v10"
    assert result["compatibility_fallback"] is False
    assert captured["nr_working_scale"] == 0.75
    assert captured["recompose_backend"] == "cuda"
    assert captured["temporal_stabilization"] == 0.5
    assert captured["nr_passes"] == 4
    assert captured["prefer_nvof"] is True


def test_unified_renderer_uses_legacy_only_as_internal_compatibility_fallback(monkeypatch):
    captured = {}

    def fake_render(source, destination, implementation, options, **kwargs):
        captured["options"] = options
        captured.update(kwargs)
        return {
            "frames": 3,
            "fps": 10.0,
            "dimensions": (640, 480),
            "audio_preserved": False,
        }

    monkeypatch.setattr(video, "render_dlss5", fake_render)
    result = video.render_dlss5_unified(
        "in.mp4",
        "out.mp4",
        _Selector("v3-fallback", _Legacy()),
        nr_working_scale="auto",
        temporal_stabilization=0.4,
        color_strength=0.9,
        tone_preservation=0.1,
    )

    assert result["dlss5_runtime"] == "v3-fallback"
    assert result["compatibility_fallback"] is True
    assert captured["nr_working_scale"] == "auto"
    assert captured["shimmer_suppression"] == 0.4
    assert captured["color_strength"] == 0.9
    assert captured["tone_preservation"] == 0.1


def test_legacy_fallback_never_silently_ignores_v10_only_user_settings():
    with pytest.raises(RuntimeError, match="require the preferred DLSS 5 runtime"):
        video.render_dlss5_unified(
            "in.mp4",
            "out.mp4",
            _Selector("v3-fallback", _Legacy()),
            nr_passes=2,
        )


def test_unified_backend_prefers_ready_v10(monkeypatch):
    class V10:
        def status(self):
            return BackendStatus("v10", True, "READY", "ok")

        def close(self):
            pass

    class Legacy:
        def status(self):
            return BackendStatus("v3", True, "READY", "ok")

        def close(self):
            pass

    monkeypatch.setattr(backend_module, "DLSS5V10ExperimentalBackend", V10)
    monkeypatch.setattr(backend_module, "DLSS5Backend", Legacy)

    backend = backend_module.DLSS5UnifiedBackend()
    name, implementation = backend.runtime()
    assert name == "v10"
    assert isinstance(implementation, V10)
    assert backend.status().state == "READY"


def test_unified_backend_uses_legacy_when_preferred_runtime_is_not_ready(monkeypatch):
    class V10:
        def status(self):
            return BackendStatus("v10", False, "PREFLIGHT REQUIRED", "refresh")

        def close(self):
            pass

    class Legacy:
        def status(self):
            return BackendStatus("v3", True, "EXPERIMENTAL READY", "ok")

        def close(self):
            pass

    monkeypatch.setattr(backend_module, "DLSS5V10ExperimentalBackend", V10)
    monkeypatch.setattr(backend_module, "DLSS5Backend", Legacy)
    monkeypatch.setattr(backend_module, "refresh_preflight_from_cache", lambda: False)

    backend = backend_module.DLSS5UnifiedBackend()
    name, implementation = backend.runtime()
    assert name == "v3-fallback"
    assert isinstance(implementation, Legacy)
    assert backend.status().state == "READY (COMPATIBILITY)"


def test_unified_backend_refreshes_stale_preflight_from_cached_archive(monkeypatch):
    state = {"ready": False, "refreshes": 0}

    class V10:
        def status(self):
            if state["ready"]:
                return BackendStatus("v10", True, "EXPERIMENTAL READY", "fresh")
            return BackendStatus("v10", False, "PREFLIGHT REQUIRED", "stale")

        def close(self):
            pass

    class Legacy:
        def status(self):
            return BackendStatus("v3", False, "NO RUNTIME", "missing")

        def close(self):
            pass

    def refresh():
        state["refreshes"] += 1
        state["ready"] = True
        return True

    monkeypatch.setattr(backend_module, "DLSS5V10ExperimentalBackend", V10)
    monkeypatch.setattr(backend_module, "DLSS5Backend", Legacy)
    monkeypatch.setattr(backend_module, "refresh_preflight_from_cache", refresh)

    backend = backend_module.DLSS5UnifiedBackend()
    assert backend.status().available is True
    assert backend.status().state == "READY"
    assert state["refreshes"] == 1
