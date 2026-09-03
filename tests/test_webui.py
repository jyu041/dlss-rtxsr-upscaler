import inspect
import subprocess
import sys
import time
from urllib.request import urlopen

import gradio as gr

from src.ui.app import build, mode_visibility

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
    assert mode_visibility("RTX VSR only") == (True, False, False, True, True)
    assert mode_visibility("DLSS 5 only") == (False, True, False, True, True)
    assert mode_visibility("DLSS 5 → RTX VSR") == (True, True, True, False, False)


def test_ui_has_no_redundant_processing_or_sr_workflow():
    source = open("src/ui/app.py", encoding="utf-8").read()
    assert 'label="Processing order"' not in source
    assert '"DLSS SR only"' not in source
    assert 'gr.Tab("DLSS Super Resolution")' not in source
    assert 'gr.Tab("Output")' not in source
    assert 'show_label=False' in source
