import json

import pytest

from src.core import user_presets


def test_independent_unicode_user_presets_and_last_used(tmp_path, monkeypatch):
    monkeypatch.setattr(user_presets, "USER_PRESETS", tmp_path / "user_presets.json")
    monkeypatch.setattr(user_presets, "LOCAL_SETTINGS", tmp_path / "settings.local.json")
    rtx = {"mode": "Super Resolution", "scale": 2.0, "quality": "ULTRA"}
    dlss = {"scale": 1.0, "nr_preset": "Default", "nr_style": "Natural", "model_preset": "Default", "intensity": .6, "local_tone": .4, "local_structure": .4, "skin_structure": .15, "automatic_mask": False}
    user_presets.save_user_preset("rtx_vsr", "我的 RTX", rtx)
    user_presets.save_user_preset("dlss5", "我的 DLSS", dlss)
    assert user_presets.get_user_preset("rtx_vsr", "我的 RTX") == rtx
    assert user_presets.get_user_preset("dlss5", "我的 DLSS") == dlss
    with pytest.raises(FileExistsError):
        user_presets.save_user_preset("rtx_vsr", "我的 RTX", rtx)
    user_presets.save_last_used("dlss5", dlss)
    assert user_presets.load_last_used()["dlss5"] == dlss
    user_presets.delete_user_preset("rtx_vsr", "我的 RTX")
    assert user_presets.list_user_presets("rtx_vsr") == []


def test_corrupt_store_is_backed_up(tmp_path, monkeypatch):
    path = tmp_path / "user_presets.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(user_presets, "USER_PRESETS", path)
    assert user_presets.load_user_presets()["rtx_vsr"] == {}
    assert list(tmp_path.glob("user_presets.json.corrupt-*"))
