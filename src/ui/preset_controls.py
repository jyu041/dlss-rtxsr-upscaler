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


def save_dlss(
    name, scale, nr_preset, nr_style, model_preset, intensity, tone, structure,
    skin, mask, nr_working_scale=1.0, recompose_backend="auto",
    shimmer_suppression=0.0, color_strength=1.0, tone_preservation=0.0,
    v10_nr_passes=1, v10_face_skin_protection=0.0,
    v10_grain_preservation=0.0, v10_shimmer_suppression=0.70,
    v10_prefer_nvof="Off",
):
    return save_preset("dlss5", name, {
        "scale": 1.0,
        "nr_preset": nr_preset,
        "nr_style": nr_style,
        "model_preset": model_preset,
        "intensity": float(intensity),
        "local_tone": float(tone),
        "local_structure": float(structure),
        "skin_structure": float(skin),
        "automatic_mask": mask == "On",
        "nr_working_scale": nr_working_scale,
        "recompose_backend": recompose_backend,
        "shimmer_suppression": float(shimmer_suppression),
        "color_strength": float(color_strength),
        "tone_preservation": float(tone_preservation),
        "v10_nr_passes": int(v10_nr_passes),
        "v10_face_skin_protection": float(v10_face_skin_protection),
        "v10_grain_preservation": float(v10_grain_preservation),
        "v10_shimmer_suppression": float(v10_shimmer_suppression),
        "v10_prefer_nvof": v10_prefer_nvof == "On",
    })


def load_dlss(name):
    values, message = load_preset("dlss5", name)
    return [
        1.0,
        values.get("nr_preset", "Default"),
        values.get("nr_style", "Natural"),
        values.get("model_preset", "Default"),
        values.get("intensity", 0.60),
        values.get("local_tone", 0.40),
        values.get("local_structure", 0.40),
        values.get("skin_structure", 0.15),
        "On" if values.get("automatic_mask") else "Off",
        values.get("nr_working_scale", 1.0),
        values.get("recompose_backend", "auto"),
        values.get("shimmer_suppression", 0.0),
        values.get("color_strength", 1.0),
        values.get("tone_preservation", 0.0),
        values.get("v10_nr_passes", 1),
        values.get("v10_face_skin_protection", 0.0),
        values.get("v10_grain_preservation", 0.0),
        values.get("v10_shimmer_suppression", 0.70),
        "On" if values.get("v10_prefer_nvof") else "Off",
        message,
    ]


def delete_dlss(name):
    return delete_preset("dlss5", name)


def save_dlss_sr(name, mode, model_preset):
    return save_preset("dlss_sr", name, {"mode": mode, "model_preset": model_preset})


def load_dlss_sr(name):
    values, message = load_preset("dlss_sr", name)
    return [values.get("mode"), values.get("model_preset"), message]


def delete_dlss_sr(name):
    return delete_preset("dlss_sr", name)
