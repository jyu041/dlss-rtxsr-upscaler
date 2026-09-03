import json
from pathlib import Path
from .paths import ROOT
from .user_presets import load_last_used

SETTINGS = ROOT / "config/settings.json"; PRESETS = ROOT / "config/presets.json"
def load_settings():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    settings["last_used"] = load_last_used()
    return settings
def save_settings(data):
    SETTINGS.write_text(json.dumps(data, indent=2), encoding="utf-8")
def load_presets(): return json.loads(PRESETS.read_text(encoding="utf-8"))
def valid_dlss(values):
    return 0 <= float(values["dlss_intensity"]) <= 2 and 0 <= float(values["local_tone"]) <= 2 and 0 <= float(values["local_structure"]) <= 2 and -1 <= float(values["skin_structure"]) <= 2
