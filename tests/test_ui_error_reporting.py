from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "ui" / "app.py"


def test_ui_suppresses_only_known_starlette_422_warning():
    source = APP.read_text(encoding="utf-8")
    assert "warnings.filterwarnings(" in source
    assert "HTTP_422_UNPROCESSABLE_ENTITY" in source
    assert "HTTP_422_UNPROCESSABLE_CONTENT" in source


def test_ui_preserves_tracebacks_for_render_and_preview_failures():
    source = APP.read_text(encoding="utf-8")
    assert 'def _log_ui_exception(' in source
    assert '_log_ui_exception("Render", exc)' in source
    assert '_log_ui_exception("Clip preview", exc)' in source
    assert '_log_ui_exception("Frame preview", e)' in source


def test_source_upload_does_not_require_browser_video_playback():
    source = APP.read_text(encoding="utf-8")
    assert 'inp = gr.File(' in source
    assert 'file_types=["video"]' in source
    assert 'type="filepath"' in source
    assert 'inp = gr.Video(label="Upload video"' not in source


def test_source_upload_generates_browser_safe_preview_proxy():
    source = APP.read_text(encoding="utf-8")
    assert 'def _browser_preview(' in source
    assert '"libx264"' in source
    assert '"yuv420p"' in source
    assert '"+faststart"' in source
    assert 'source_preview = gr.Video(' in source
    assert 'source_state = gr.State(None)' in source
    assert 'inp.upload(' in source
    assert 'select_source,' in source
    assert 'replace_input.click(' in source
    assert 'frame.click(do_frame, [source_state,' in source
    assert 'clip.click(preview_clip, [source_state,' in source
    assert 'render.click(render_video, [source_state,' in source


def test_render_result_uses_browser_safe_preview_proxy():
    source = APP.read_text(encoding="utf-8")
    assert 'browser_preview = _browser_preview(destination)' in source
    assert 'browser preview: first 12s' in source
