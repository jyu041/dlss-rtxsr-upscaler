from src.core.user_presets import delete_user_preset, get_user_preset, list_user_presets, save_user_preset


def preset_choices(backend):
    return list_user_presets(backend)


def save_preset(backend, name, values):
    try:
        save_user_preset(backend, name, values)
        return list_user_presets(backend), f"Saved {name!r}."
    except FileExistsError as exc:
        return list_user_presets(backend), f"{exc}. Use a new name to avoid accidental overwrite."
    except Exception as exc:
        return list_user_presets(backend), f"Save failed: {exc}"


def load_preset(backend, name):
    if not name:
        return {}, "Choose a saved preset."
    values = get_user_preset(backend, name)
    return values or {}, "Loaded " + name + "."


def delete_preset(backend, name):
    if not name:
        return list_user_presets(backend), "Choose a saved preset."
    delete_user_preset(backend, name)
    return list_user_presets(backend), "Deleted " + name + "."


def save_rtx(name, mode, scale, quality):
    return save_preset("rtx_vsr", name, {"mode": mode, "scale": float(scale), "quality": quality})


def load_rtx(name):
    values, message = load_preset("rtx_vsr", name)
    return [values.get("mode"), values.get("scale"), values.get("quality"), message]


def delete_rtx(name):
    return delete_preset("rtx_vsr", name)


def save_dlss(name, scale, nr_preset, nr_style, model_preset, intensity, tone, structure, skin, mask):
    return save_preset("dlss5", name, {"scale": float(scale), "nr_preset": nr_preset, "nr_style": nr_style, "model_preset": model_preset, "intensity": float(intensity), "local_tone": float(tone), "local_structure": float(structure), "skin_structure": float(skin), "automatic_mask": mask == "On"})


def load_dlss(name):
    values, message = load_preset("dlss5", name)
    return [values.get("scale"), values.get("nr_preset"), values.get("nr_style"), values.get("model_preset"), values.get("intensity"), values.get("local_tone"), values.get("local_structure"), values.get("skin_structure"), "On" if values.get("automatic_mask") else "Off", message]


def delete_dlss(name):
    return delete_preset("dlss5", name)
