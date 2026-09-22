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


def test_source_upload_uses_full_length_browser_display_video():
    source = APP.read_text(encoding="utf-8")
    helper = source[source.index("def _browser_display_video("):source.index("\n\ndef select_source(")]
    assert 'full-length browser-playable MP4' in helper
    assert 'command += ["-c:v", "copy"]' in helper
    assert '"-movflags"' in helper
    assert '"+faststart"' in helper
    assert '"-t"' not in helper
    assert '"-vf"' not in helper
    assert 'source_state = gr.State(None)' in source
    assert 'source_preview = gr.Video(' in source
    assert 'format="mp4"' in source
    assert 'inp.upload(' in source
    assert 'select_source,' in source
    assert 'replace_input.click(' in source
    assert 'frame_event = frame.click(do_frame, [source_state,' in source
    assert 'clip_event = clip.click(preview_clip, [source_state,' in source
    assert 'render_event = render.click(render_video, [source_state,' in source
    assert 'browser-safe proxy' not in source


def test_render_result_uses_full_length_video_and_selects_video_tab():
    source = APP.read_text(encoding="utf-8")
    assert 'browser_video = _browser_display_video(destination)' in source
    assert 'browser preview: first 12s' not in source
    assert 'with gr.Tabs(selected="video"' in source
    assert 'with gr.Tab("Video", id="video")' in source
    assert 'with gr.Tab("Frame", id="frame")' in source
    assert 'render_event.then(lambda: gr.Tabs(selected="video")' in source
    assert 'clip_event.then(lambda: gr.Tabs(selected="video")' in source
    assert 'frame_event.then(lambda: gr.Tabs(selected="frame")' in source
    assert "output {stats['output_fps']:.3f} FPS" in source
    assert "render throughput {stats['end_to_end_fps']:.2f} output frames/s" in source



def test_render_status_reports_automatic_vsr_codec_fallback():
    source = APP.read_text(encoding="utf-8")
    assert 'if stats.get("codec_fallback"):' in source
    assert "automatic fallback from" in source
    assert "{codec_note}{display_note}" in source



def test_webui_mfg_does_not_emit_diagnostic_sidecars():
    source = APP.read_text(encoding="utf-8")
    calls = [line for line in source.splitlines() if "render_dlssg(" in line]
    assert len(calls) >= 2
    assert all("write_sidecars=False" in line for line in calls)


def test_dlssg_sidecar_writes_are_explicitly_gated():
    source = (ROOT / "src" / "video" / "dlssg.py").read_text(encoding="utf-8")
    assert "write_sidecars: bool = True" in source
    assert 'if write_sidecars\n        else open(os.devnull, "w", encoding="utf-8")' in source
    assert 'manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")' in source
    assert '"worker_diagnostics": str(log_path) if write_sidecars else None' in source



def test_deblur_and_denoise_frame_preview_use_reference_helper():
    source = APP.read_text(encoding="utf-8")
    assert "process_same_resolution_frame" in source
    assert 'if vsr_mode in {"Deblur", "Denoise"}:' in source
    assert "using NVIDIA reference path" in source
