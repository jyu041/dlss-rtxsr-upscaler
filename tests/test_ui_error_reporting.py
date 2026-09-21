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
