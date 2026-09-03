from src.ui.tooltips import DLSS5_TOOLTIPS, RTX_TOOLTIPS, help_icon


def test_all_backend_controls_have_help_and_html_is_escaped():
    assert all(text.strip() for text in RTX_TOOLTIPS.values())
    assert all(text.strip() for text in DLSS5_TOOLTIPS.values())
    assert "&lt;script&gt;" in help_icon("<script>")
