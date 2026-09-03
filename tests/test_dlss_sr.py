import pytest

from src.backends.dlss_sr import DLSSSRBackend
from src.ui.tooltips import DLSS_SR_TOOLTIPS


def test_dlss_sr_is_explicitly_unavailable_without_fallback():
    backend = DLSSSRBackend()
    status = backend.status()
    assert not status.available
    assert "SR is not exposed" in status.reason
    with pytest.raises(RuntimeError, match="DLSS SR unavailable"):
        backend.process_frame(None)


def test_dlss_sr_tooltip_mapping_is_nonempty():
    assert all(value.strip() for value in DLSS_SR_TOOLTIPS.values())
