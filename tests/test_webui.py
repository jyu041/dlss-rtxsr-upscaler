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
from src.ui.app import build, default_mode, mode_visibility
from src.core import user_presets


def test_dlss_sr_validation_action_runs_explicitly_and_refreshes_choices(monkeypatch):
    class Status:
        state = "READY"
        reason = "fresh attestation"
    class Backend:
        def selftest(self): return {"status": "success"}
        def status(self): return Status()
    monkeypatch.setattr(webui, "DLSSSRBackend", Backend)
    monkeypatch.setattr(webui, "status_html", lambda: "status")
    monkeypatch.setattr(webui, "available_mode_choices", lambda: [("DLSS SR", "DLSS SR only")])
    status, message, update = webui.validate_dlss_sr()
    assert status == "status"
    assert "READY" in message
    assert update["choices"] == [("DLSS SR", "DLSS SR only")]


def test_dlss_sr_validation_is_reachable_before_ready(monkeypatch):
    class Status:
        state = "SELFTEST REQUIRED"
        reason = "run explicit self-test"

    monkeypatch.setattr(webui, "status_html", lambda: "status")
    monkeypatch.setattr(webui, "available_mode_choices", lambda: [("RTX VSR", "RTX VSR only"), ("DLSS 5", "DLSS 5 only")])
    monkeypatch.setattr(webui, "default_mode", lambda: "RTX VSR only")
    monkeypatch.setattr(webui, "DLSSSRBackend", lambda: type("Backend", (), {"status": lambda self: Status()})())
    ui = build()
    components = ui.config["components"]
    buttons = [item for item in components if item.get("type") == "button" and item.get("props", {}).get("value") == "Validate DLSS SR"]
    readiness_groups = [item for item in components if item.get("type") == "group" and item.get("props", {}).get("elem_classes") == ["backend-readiness"]]
    radios = [item for item in components if item.get("type") == "radio" and item.get("props", {}).get("elem_id") == "enhancement-selector"]
    assert len(buttons) == 1
    assert buttons[0]["props"].get("visible", True) is True
    assert len(readiness_groups) == 1 and readiness_groups[0]["props"].get("visible", True) is True
    assert ("DLSS SR", "DLSS SR only") not in radios[0]["props"]["choices"]


def test_dlss_sr_ready_state_adds_processing_choice(monkeypatch):
    class Status:
        state = "READY"
        reason = "current attestation"

    monkeypatch.setattr(webui, "DLSSSRBackend", lambda: type("Backend", (), {"status": lambda self: Status()})())
    monkeypatch.setattr(webui, "default_mode", lambda: "RTX VSR only")
    ui = build()
    radios = [item for item in ui.config["components"] if item.get("type") == "radio" and item.get("props", {}).get("elem_id") == "enhancement-selector"]
    assert ("DLSS SR", "DLSS SR only") in radios[0]["props"]["choices"]


@pytest.mark.parametrize("state", ["NO HOST", "NO RUNTIME", "IDENTITY MISMATCH"])
def test_dlss_sr_unavailable_states_are_visible_and_non_actionable(monkeypatch, state):
    class Status:
        reason = "exact validated native files are required"
    Status.state = state
    monkeypatch.setattr(webui, "DLSSSRBackend", lambda: type("Backend", (), {"status": lambda self: Status()})())
    monkeypatch.setattr(webui, "default_mode", lambda: "RTX VSR only")
    ui = build()
    components = ui.config["components"]
    button = next(item for item in components if item.get("type") == "button" and item.get("props", {}).get("value") == "Validate DLSS SR")
    readiness = next(item for item in components if item.get("type") == "markdown" and "Current state:" in item.get("props", {}).get("value", ""))
    assert state in readiness["props"]["value"]
    assert button["props"]["interactive"] is False


def test_dlss_sr_failed_validation_does_not_enable_processing(monkeypatch):
    class Status:
        state = "IDENTITY MISMATCH"
        reason = "hash mismatch"
    class Backend:
        def selftest(self):
            raise RuntimeError("hash mismatch")
        def status(self):
            return Status()
    monkeypatch.setattr(webui, "DLSSSRBackend", Backend)
    monkeypatch.setattr(webui, "status_html", lambda: "status")
    monkeypatch.setattr(webui, "available_mode_choices", lambda: [("RTX VSR", "RTX VSR only"), ("DLSS 5", "DLSS 5 only")])
    status, message, update = webui.validate_dlss_sr()
    assert status == "status"
    assert "failed" in message.lower()
    assert "IDENTITY MISMATCH" in message
    assert ("DLSS SR", "DLSS SR only") not in update["choices"]


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
    assert mode_visibility("DLSS 5 v10 Experimental") == (False, False, False, False)
    assert mode_visibility("DLSS SR only") == (False, False, True, False)
    assert mode_visibility("DLSS Frame Generation 2X") == (False, False, False, True)


def test_dlss5_exposes_one_mode_and_unified_backend_can_be_default(monkeypatch):
    choices = webui.available_mode_choices()
    assert ("DLSS 5", "DLSS 5 only") in choices
    assert all("v10 Experimental" not in label for label, _value in choices)

    class NotReady:
        available = False
        state = "UNAVAILABLE"

    class Ready:
        available = True

    monkeypatch.setattr(webui, "RTXVSRBackend", lambda: type("Backend", (), {"status": lambda self: NotReady()})())
    monkeypatch.setattr(webui, "DLSSSRBackend", lambda: type("Backend", (), {"status": lambda self: NotReady()})())
    monkeypatch.setattr(webui, "DLSSGBackend", lambda: type("Backend", (), {"status": lambda self: NotReady()})())
    monkeypatch.setattr(webui, "DLSS5UnifiedBackend", lambda: type("Backend", (), {"status": lambda self: Ready()})())
    assert webui.default_mode() == "DLSS 5 only"


def test_dlss5_ui_has_one_mode_and_simple_install_repair_action():
    source = open("src/ui/app.py", encoding="utf-8").read()
    assert '("DLSS 5", "DLSS 5 only")' in source
    assert '("DLSS 5 v10 Experimental", "DLSS 5 v10 Experimental")' not in source
    assert 'gr.Button("Install / Repair DLSS 5")' in source
    assert 'gr.Markdown("### DLSS 5 runtime")' in source
    assert "DLSS5UnifiedBackend()" in source
    assert "render_dlss5_unified(" in source
    assert "refresh_dlss5_v10_preflight" in source
    assert "prepare_dlss5_v10()" in source
    assert "mode.change(dlss_scale_update_for_mode" not in source
    assert "dlss_scale = gr.State(dlss_default_scale)" in source
    assert "nrpreset = gr.State" in source
    assert "model = gr.State" in source


def test_default_mode_prefers_ready_rtx_vsr(monkeypatch):
    class Ready:
        available = True
    monkeypatch.setattr(webui, "RTXVSRBackend", lambda: type("Backend", (), {"status": lambda self: Ready()})())
    assert default_mode() == "RTX VSR only"


def test_ui_build_uses_saved_dlssg_controls_without_runtime_paths(tmp_path, monkeypatch):
    settings = tmp_path / "settings.local.json"
    monkeypatch.setattr(user_presets, "LOCAL_SETTINGS", settings)
    user_presets.save_last_used(
        "dlssg",
        {
            "motion_provider": "NVIDIA Optical Flow",
            "depth_mode": "Constant 0.5",
            "multiplier": 4,
            "nvof_profile": "grid4-gpu-candidate",
        },
    )
    monkeypatch.setattr(webui, "default_mode", lambda: "RTX VSR only")
    ui = build()
    fields = {component.get("props", {}).get("label"): component.get("props", {}).get("value") for component in ui.config["components"]}
    assert "Community runtime (absolute version.dll path)" not in fields
    assert "Official NGX runtime directory" not in fields
    assert "Runtime profile" not in fields
    assert fields["Frame multiplier"] == 4
    assert fields["NVOF profile"] == "grid4-gpu-candidate"
    assert webui.DEFAULT_DLSSG_PROFILE == "legacy"





def test_dlssg_grid4_profile_is_explicit_and_routes_to_research_backend(monkeypatch):
    captured = {}

    class Status:
        state = "RESEARCH CANDIDATE"
        available = True
        reason = "grid4 ready"

    class Backend:
        def status(self):
            return Status()

    monkeypatch.setattr(
        webui,
        "backend_for_nvof_profile",
        lambda profile: captured.setdefault("profile", profile) or Backend(),
    )
    # setdefault returns the string; use a real helper to keep the assertion explicit.
    def factory(profile):
        captured["profile"] = profile
        return Backend()
    monkeypatch.setattr(webui, "backend_for_nvof_profile", factory)

    message = webui.check_dlssg_readiness("grid4-gpu-candidate")
    assert captured["profile"] == "grid4-gpu-candidate"
    assert "RESEARCH CANDIDATE" in message
    assert "Available: True" in message


def test_dlssg_ui_source_passes_selected_nvof_profile_to_renderer():
    source = open("src/ui/app.py", encoding="utf-8").read()
    assert 'label="NVOF profile"' in source
    assert "NVOF_PROFILE_GRID4_GPU_CANDIDATE" in source
    assert "backend_for_nvof_profile(dlssg_nvof_profile)" in source
    assert "nvof_profile=dlssg_nvof_profile" in source


def test_preview_directory_keeps_recent_playable_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "TEMP", tmp_path)
    created = [webui._preview_directory() for _ in range(5)]
    retained = [directory for directory in created if directory.exists()]
    assert len(retained) == 4
    assert created[-1].exists()


def test_dlssg_backend_discovers_managed_legacy_when_no_override(tmp_path, monkeypatch):
    from src.backends import dlssg
    monkeypatch.delenv("DLSSG_COMMUNITY_RUNTIME", raising=False)
    monkeypatch.delenv("DLSSG_OFFICIAL_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DLSSG_RUNTIME_PROFILE", raising=False)
    monkeypatch.setattr(dlssg, "MANAGED_COMMUNITY_RUNTIME", tmp_path / "legacy" / "version.dll")
    monkeypatch.setattr(dlssg, "MANAGED_OFFICIAL_RUNTIME_DIR", tmp_path / "official")
    backend = dlssg.DLSSGBackend()
    assert backend.configuration.runtime_profile == "legacy"
    assert backend.configuration.community_runtime == (tmp_path / "legacy" / "version.dll").resolve()
    assert backend.configuration.official_runtime_dir == (tmp_path / "official").resolve()


def test_dlssg_backend_still_allows_explicit_candidate_override(tmp_path, monkeypatch):
    from src.backends import dlssg
    monkeypatch.delenv("DLSSG_COMMUNITY_RUNTIME", raising=False)
    monkeypatch.setattr(dlssg, "MANAGED_CANDIDATE_RUNTIME", tmp_path / "candidate" / "version.dll")
    backend = dlssg.DLSSGBackend(runtime_profile="candidate-0.3.1")
    assert backend.configuration.runtime_profile == "candidate-0.3.1"
    assert backend.configuration.community_runtime == (tmp_path / "candidate" / "version.dll").resolve()


def test_ui_has_no_redundant_processing_or_sr_workflow():
    source = open("src/ui/app.py", encoding="utf-8").read()
    assert 'label="Processing order"' not in source
    assert '"DLSS 5 → RTX VSR"' not in source
    assert 'gr.Tab("DLSS Super Resolution")' not in source
    assert 'gr.Tab("Output")' not in source
    assert 'Load Last Render' in source
    assert 'show_label=False' in source
    assert "Community runtime (absolute version.dll path)" not in source
    assert "Official NGX runtime directory" not in source
    assert "2X Frame Generation, 3X Multi Frame Generation, and 4X Multi Frame Generation are hardware-validated" in source



def test_webui_is_task_first_and_separates_configuration_and_diagnostics():
    source = open("src/ui/app.py", encoding="utf-8").read()
    enhance = source.index('with gr.Tab("Enhance")')
    configuration = source.index('with gr.Tab("Configuration")')
    diagnostics = source.index('with gr.Tab("Diagnostics")')
    runtime_manager = source.index('gr.Markdown("### Runtime Manager")')
    progress = source.index('progress_panel = gr.HTML(')

    assert enhance < configuration < diagnostics
    assert runtime_manager > configuration
    assert enhance < progress < configuration

    status_source = source[source.index("def status_html():"):source.index("def runtime_cards_markdown()")]
    assert "Managed components" not in status_source
    assert "runtime_card" not in status_source

    # Gradio 6 left empty framed shells for hidden Group containers. Backend
    # settings now use visibility-controlled Columns instead.
    assert 'with gr.Group(visible=rtx_initial, elem_classes="backend-group")' not in source
    assert 'with gr.Column(visible=rtx_initial, elem_classes=["backend-panel", "backend-rtx"])' in source
    assert 'with gr.Column(visible=dlssg_initial, elem_classes=["backend-panel", "backend-dlssg"])' in source

    # Readiness/admin controls are deliberately kept out of the Enhance tab.
    sr_readiness = source.index('gr.Markdown("### DLSS SR readiness")')
    v10_readiness = source.index('gr.Markdown("### DLSS 5 runtime")')
    assert configuration < sr_readiness < diagnostics
    assert configuration < v10_readiness < diagnostics




def test_webui_progress_is_local_to_preview_and_dlss5_is_compact():
    source = open("src/ui/app.py", encoding="utf-8").read()
    css = open("src/ui/styles.css", encoding="utf-8").read()

    preview_column = source.index('with gr.Column(scale=40, min_width=420, elem_classes=["workspace-card", "preview-panel"])')
    progress = source.index('progress_panel = gr.HTML(')
    preview_heading = source.index('gr.Markdown("## Preview / Output")')
    configuration = source.index('with gr.Tab("Configuration")')
    assert preview_column < progress < preview_heading < configuration
    assert 'elem_classes=["workspace-progress", "preview-progress"]' in source

    dlss5_start = source.index('with gr.Column(visible=dlss_initial, elem_classes=["backend-panel", "backend-dlss"])')
    dlss5_end = source.index('with gr.Column(visible=sr_initial', dlss5_start)
    dlss5 = source[dlss5_start:dlss5_end]
    assert 'with gr.Accordion("Quality tuning", open=False' in dlss5
    assert 'with gr.Accordion("Advanced runtime / neural controls", open=False' in dlss5
    assert 'with gr.Group(elem_classes="compact-control")' not in dlss5
    assert 'elem_classes="compact-control"' in dlss5
    assert 'elem_classes="compact-native-control"' in dlss5
    assert 'gr.Markdown("#### Experimental quality composition")' not in dlss5
    assert 'class="compact-note"' not in dlss5
    assert ".preview-progress .job-progress" in css
    assert ".compact-settings .form" in css
    assert "--form-gap-width: 4px;" in css
    assert "top: calc(100% + 6px);" in css
    assert "z-index: 1000;" in css
    assert ".compact-settings .compact-control.block.padded" in css


def test_webui_second_pass_uses_progressive_disclosure_for_status_and_runtime_inventory():
    source = open("src/ui/app.py", encoding="utf-8").read()
    css = open("src/ui/styles.css", encoding="utf-8").read()

    status_source = source[source.index("def status_html():"):source.index("def runtime_cards_markdown()")]
    assert '<details class="status-menu">' in status_source
    assert '<summary><span class="status-dot"></span>Backend status</summary>' in status_source

    configuration = source.index('with gr.Tab("Configuration")')
    runtime_manager = source.index('gr.Markdown("### Runtime Manager")')
    runtime_action = source.index('runtime_action_button = gr.Button("Run runtime action")')
    inventory = source.index('with gr.Accordion("Managed component inventory", open=False)')
    diagnostics = source.index('with gr.Tab("Diagnostics")')
    assert configuration < runtime_manager < runtime_action < inventory < diagnostics

    assert 'with gr.Row(elem_classes="validation-grid")' in source
    assert 'gr.Markdown("### DLSS SR readiness")' in source
    assert 'gr.Markdown("### DLSS 5 runtime")' in source
    assert "footer {\n  display: none !important;\n}" in css



def test_portable_launcher_verifies_manifest_before_embedded_python():
    source = open("start.bat", encoding="utf-8").read()
    check = source.index("check_portable_runtime.py")
    launch = source.index('call "%~dp0runtime\\python\\python.exe" "%~dp0app.py"')
    assert check < launch
