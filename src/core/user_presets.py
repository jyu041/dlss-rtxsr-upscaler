"""Validated, atomic storage for user presets and last-used settings."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .paths import ROOT

USER_PRESETS = ROOT / "config" / "user_presets.json"
LOCAL_SETTINGS = ROOT / "config" / "settings.local.json"
_LOCK = threading.RLock()

RTX_FIELDS = {"mode", "scale", "quality"}
DLSS_FIELDS = {"scale", "nr_preset", "nr_style", "model_preset", "intensity", "local_tone", "local_structure", "skin_structure", "automatic_mask"}


def _empty() -> dict:
    return {"schema_version": 1, "rtx_vsr": {}, "dlss5": {}}


def _read(path: Path, default: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return default
        data.setdefault("rtx_vsr", {})
        data.setdefault("dlss5", {})
        return data
    except (OSError, ValueError):
        if path.is_file():
            backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(path, backup)
            except OSError:
                pass
        return default


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _backend(backend: str) -> str:
    value = {"rtx": "rtx_vsr", "rtx_vsr": "rtx_vsr", "dlss": "dlss5", "dlss5": "dlss5"}.get(backend)
    if value is None:
        raise ValueError("backend must be rtx_vsr or dlss5")
    return value


def _name(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError("Preset names must be 1-80 characters and contain no control characters")
    return name.strip()


def _validate(backend: str, values: dict) -> dict:
    key = _backend(backend)
    if not isinstance(values, dict):
        raise ValueError("Preset values must be an object")
    fields = RTX_FIELDS if key == "rtx_vsr" else DLSS_FIELDS
    if not set(values).issubset(fields):
        raise ValueError("Preset contains fields for another backend")
    result = dict(values)
    if key == "rtx_vsr":
        if result.get("mode") not in {"Super Resolution", "High Bitrate", "Deblur", "Denoise"} or result.get("quality") not in {"LOW", "MEDIUM", "HIGH", "ULTRA"}:
            raise ValueError("Invalid RTX VSR preset")
        if float(result.get("scale", 0)) not in {1.0, 1.5, 2.0, 2.5, 3.0, 4.0}:
            raise ValueError("Invalid RTX VSR scale")
    else:
        for field, low, high in (("intensity", 0, 2), ("local_tone", 0, 2), ("local_structure", 0, 2), ("skin_structure", -1, 2)):
            if not low <= float(result.get(field, 0)) <= high:
                raise ValueError(f"Invalid DLSS5 {field}")
        if result.get("nr_preset") not in {"Default", "Preset #1", "Preset #2", "Preset #3"} or result.get("nr_style") not in {"Default", "Natural", "Cinematic"} or result.get("model_preset") not in {"Default", "J", "K", "L", "M"}:
            raise ValueError("Invalid DLSS5 preset selection")
        if not isinstance(result.get("automatic_mask"), bool) or float(result.get("scale", 0)) not in {1.0, 1.5, 1.724, 2.0, 3.0}:
            raise ValueError("Invalid DLSS5 preset value")
    return result


def load_user_presets() -> dict:
    with _LOCK:
        return _read(USER_PRESETS, _empty())


def list_user_presets(backend: str) -> list[str]:
    return list(load_user_presets()[_backend(backend)].keys())


def get_user_preset(backend: str, name: str) -> dict | None:
    return load_user_presets()[_backend(backend)].get(_name(name))


def save_user_preset(backend: str, name: str, values: dict, overwrite: bool = False) -> dict:
    key, clean_name, clean_values = _backend(backend), _name(name), _validate(backend, values)
    with _LOCK:
        data = load_user_presets()
        if clean_name in data[key] and not overwrite:
            raise FileExistsError(f"Preset {clean_name!r} already exists; confirm overwrite")
        data[key][clean_name] = clean_values
        _atomic_write(USER_PRESETS, data)
        return clean_values


def delete_user_preset(backend: str, name: str) -> None:
    key, clean_name = _backend(backend), _name(name)
    with _LOCK:
        data = load_user_presets()
        data[key].pop(clean_name, None)
        _atomic_write(USER_PRESETS, data)


def load_last_used() -> dict:
    with _LOCK:
        return _read(LOCAL_SETTINGS, {"schema_version": 1, "last_used": {}}).get("last_used", {})


def save_last_used(backend: str, values: dict) -> None:
    key = _backend(backend)
    clean = _validate(backend, values)
    with _LOCK:
        data = _read(LOCAL_SETTINGS, {"schema_version": 1, "last_used": {}})
        data.setdefault("last_used", {})[key] = clean
        _atomic_write(LOCAL_SETTINGS, data)


def load_last_successful_render() -> str | None:
    """Return the tracked full render only while it remains a supported video."""
    with _LOCK:
        data = _read(LOCAL_SETTINGS, {"schema_version": 1, "last_used": {}})
        value = data.get("last_successful_render")
        path = Path(value).expanduser() if isinstance(value, str) else None
        if path and path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
            return str(path.resolve())
        if value is not None:
            data.pop("last_successful_render", None)
            _atomic_write(LOCAL_SETTINGS, data)
        return None


def save_last_successful_render(path: str | Path) -> None:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file() or candidate.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
        raise ValueError("Last successful render must be an existing supported video")
    with _LOCK:
        data = _read(LOCAL_SETTINGS, {"schema_version": 1, "last_used": {}})
        data["last_successful_render"] = str(candidate)
        _atomic_write(LOCAL_SETTINGS, data)
