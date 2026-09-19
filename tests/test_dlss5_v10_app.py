from pathlib import Path

import pytest

from src.backends import dlss5_v10_app as app_backend
from src.backends.dlss5_v10_adapter import V10ExecutionDisabled
from src.backends.dlss5_v10_client import (
    APP_EXPERIMENT_ACK,
    V10ProtocolClient,
)
from src.backends import dlss5_v10_host as host
from src.core.paths import output_path


def test_v10_app_backend_reports_missing_runtime(tmp_path):
    backend = app_backend.DLSS5V10ExperimentalBackend(
        tmp_path / "runtime",
        tmp_path / "preflight.json",
    )
    status = backend.status()
    assert not status.available
    assert status.state == "RUNTIME NOT STAGED"


def test_v10_app_backend_reports_missing_preflight(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    backend = app_backend.DLSS5V10ExperimentalBackend(
        runtime,
        tmp_path / "preflight.json",
    )
    status = backend.status()
    assert not status.available
    assert status.state == "PREFLIGHT REQUIRED"


def test_v10_app_backend_accepts_current_preflight(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        app_backend,
        "validate_preflight_report",
        lambda *args: {"preflight_age_seconds": 30.0},
    )
    backend = app_backend.DLSS5V10ExperimentalBackend(runtime, preflight)
    status = backend.status()
    assert status.available
    assert status.state == "EXPERIMENTAL READY"
    assert "0.5 minutes old" in status.reason


@pytest.mark.parametrize("width,height", [(1920, 1080), (1080, 1920), (640, 480)])
def test_v10_app_backend_accepts_supported_geometry(width, height):
    app_backend.DLSS5V10ExperimentalBackend.validate_geometry(width, height, 1.0)


@pytest.mark.parametrize(
    "width,height,scale",
    [
        (2560, 1440, 1.0),
        (1440, 2560, 1.0),
        (640, 480, 2.0),
    ],
)
def test_v10_app_backend_rejects_unvalidated_geometry_or_scale(width, height, scale):
    with pytest.raises(RuntimeError):
        app_backend.DLSS5V10ExperimentalBackend.validate_geometry(
            width,
            height,
            scale,
        )


def test_v10_app_create_request_maps_ui_controls():
    backend = app_backend.DLSS5V10ExperimentalBackend()
    request = backend.create_request(
        640,
        480,
        style="Cinematic",
        intensity=0.75,
        local_tone=0.4,
        local_structure=0.6,
        skin_structure=0.2,
        automatic_mask=True,
    )
    assert request.input_width == 640
    assert request.input_height == 480
    assert request.processing_scale == 1.0
    assert request.style == 2
    assert request.intensity == pytest.approx(0.75)
    assert request.local_tone == pytest.approx(0.4)
    assert request.local_structure == pytest.approx(0.6)
    assert request.skin_structure == pytest.approx(0.2)
    assert request.automatic_mask is True


def test_v10_app_client_requires_exact_ack_without_spawning(tmp_path):
    client = V10ProtocolClient()
    with pytest.raises(V10ExecutionDisabled, match="exact acknowledgement"):
        client.start_native_application_experimental(
            tmp_path / "runtime",
            tmp_path / "preflight.json",
            acknowledgement="wrong",
        )
    assert client.process is None


def test_v10_app_host_route_requires_exact_environment_ack(monkeypatch, tmp_path):
    monkeypatch.delenv("NVE_DLSS5_V10_NATIVE", raising=False)
    assert host.main(
        [
            "--experimental-native-app-serve",
            "--runtime-dir",
            str(tmp_path / "runtime"),
            "--preflight-report",
            str(tmp_path / "preflight.json"),
        ]
    ) == 77


def test_v10_app_output_path_is_distinct(tmp_path, monkeypatch):
    from src.core import paths

    monkeypatch.setattr(paths, "OUTPUTS", tmp_path)
    result = output_path(
        tmp_path / "input.mp4",
        "DLSS 5 v10 Experimental",
        "MP4",
        1.0,
    )
    assert result.name == "input_dlss5_v10.mp4"


def test_v10_application_ack_is_separate_from_bounded_research_tokens():
    assert APP_EXPERIMENT_ACK == "EXPERIMENTAL_APP_SCENE_AWARE_V10"
    assert APP_EXPERIMENT_ACK != host.EXPERIMENT_ACK
    assert APP_EXPERIMENT_ACK != host.SCENE_SOAK_EXPERIMENT_ACK
