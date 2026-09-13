import inspect
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest

try:
    import gradio as gr
except ImportError as exc:
    pytest.skip(f"WebUI dependency is unavailable in this Python environment: {exc}", allow_module_level=True)

from src.ui import app as webui
from src.ui.app import build, mode_visibility
from src.core import user_presets

def test_gradio_launch_configuration_matches_installed_api():
    blocks_params = inspect.signature(gr.Blocks).parameters
    launch_params = inspect.signature(gr.Blocks.launch).parameters
    assert "analytics_enabled" in blocks_params
    assert "css_paths" in launch_params
    assert "enable_monitoring" in launch_params
    assert "analytics_enabled" not in launch_params
    assert "run_history" not in launch_params
    assert build() is not None

def test_actual_local_webui_launch():
    process = subprocess.Popen([sys.executable, "app.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 30
        response = None
        while time.time() < deadline:
            try:
                response = urlopen("http://127.0.0.1:7860/", timeout=2)
                break
            except Exception:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise AssertionError(f"WebUI exited before serving: {output}")
                time.sleep(0.25)
        assert response is not None
        assert response.status == 200
        assert response.geturl().startswith("http://127.0.0.1:7860")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_enhancement_selector_is_the_single_routing_source():
    assert mode_visibility("RTX VSR only") == (True, False, False, False)
    assert mode_visibility("DLSS 5 only") == (False, True, False, False)
    assert mode_visibility("DLSS SR only") == (False, False, True, False)
    assert mode_visibility("DLSS Frame Generation 2X") == (False, False, False, True)


def test_ui_build_uses_saved_dlssg_values(tmp_path, monkeypatch):
    settings = tmp_path / "settings.local.json"
    monkeypatch.setattr(user_presets, "LOCAL_SETTINGS", settings)
    user_presets.save_last_used("dlssg", {"community_runtime": "C:/saved/version.dll", "official_runtime_dir": "C:/saved/ngx", "motion_provider": "NVIDIA Optical Flow", "depth_mode": "Constant 0.5"})
    ui = build()
    fields = {component.get("props", {}).get("label"): component.get("props", {}).get("value") for component in ui.config["components"]}
    assert fields["Community runtime (absolute version.dll path)"] == "C:/saved/version.dll"
    assert fields["Official NGX runtime directory"] == "C:/saved/ngx"
    assert fields["Frame multiplier"] == 2


def test_preview_directory_keeps_recent_playable_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "TEMP", tmp_path)
    created = [webui._preview_directory() for _ in range(5)]
    retained = [directory for directory in created if directory.exists()]
    assert len(retained) == 4
    assert created[-1].exists()


def test_dlssg_startup_precedence_saved_then_environment_then_default(tmp_path, monkeypatch):
    settings = tmp_path / "settings.local.json"
    monkeypatch.setattr(user_presets, "LOCAL_SETTINGS", settings)
    monkeypatch.setenv("DLSSG_COMMUNITY_RUNTIME", "C:/env/version.dll")
    monkeypatch.setenv("DLSSG_OFFICIAL_RUNTIME_DIR", "C:/env/ngx")
    ui = build()
    fields = {component.get("props", {}).get("label"): component.get("props", {}).get("value") for component in ui.config["components"]}
    assert fields["Community runtime (absolute version.dll path)"] == "C:/env/version.dll"
    user_presets.save_last_used("dlssg", {"community_runtime": "C:/saved/version.dll", "official_runtime_dir": "", "motion_provider": "NVIDIA Optical Flow", "depth_mode": "Constant 0.5"})
    ui = build()
    fields = {component.get("props", {}).get("label"): component.get("props", {}).get("value") for component in ui.config["components"]}
    assert fields["Community runtime (absolute version.dll path)"] == "C:/saved/version.dll"
    assert fields["Official NGX runtime directory"] == ""


def test_ui_has_no_redundant_processing_or_sr_workflow():
    source = open("src/ui/app.py", encoding="utf-8").read()
    assert 'label="Processing order"' not in source
    assert '"DLSS 5 → RTX VSR"' not in source
    assert 'gr.Tab("DLSS Super Resolution")' not in source
    assert 'gr.Tab("Output")' not in source
    assert 'Load Last Render' in source
    assert 'show_label=False' in source
    assert "3X and 4X use the generalized worker contract but remain experimental" in source
