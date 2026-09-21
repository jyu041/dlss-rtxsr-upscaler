"""Single user-facing DLSS 5 video renderer.

The preferred implementation is the isolated v10 application path. The
validated v3 implementation remains an internal compatibility fallback until
v10 has equivalent hardware coverage. Callers do not select a version.
"""

from __future__ import annotations

from src.backends.dlss5_unified import DLSS5UnifiedBackend
from src.video.dlss5 import render_dlss5
from src.video.dlss5_v10 import render_dlss5_v10


def _legacy_options(
    backend,
    *,
    output_scale: float,
    nr_preset: str,
    style: str,
    model_preset: str,
    intensity: float,
    local_tone: float,
    local_structure: float,
    skin_structure: float,
    automatic_mask: bool,
):
    return backend.options(
        upscaling_mode=float(output_scale),
        nr_preset=nr_preset,
        nr_style=style,
        nr_intensity=float(intensity),
        local_tone_strength=float(local_tone),
        local_structure_strength=float(local_structure),
        skin_structure_strength=float(skin_structure),
        automatic_mask=bool(automatic_mask),
        dlss_model_preset=model_preset,
        motion_mode="optical_flow",
    )


def render_dlss5_unified(
    source,
    destination,
    backend: DLSS5UnifiedBackend,
    *,
    output_scale: float = 1.0,
    nr_preset: str = "Default",
    style: str = "Natural",
    model_preset: str = "Default",
    intensity: float = 0.60,
    local_tone: float = 0.40,
    local_structure: float = 0.40,
    skin_structure: float = 0.15,
    automatic_mask: bool = False,
    nr_working_scale: float | str = 1.0,
    recompose_backend: str = "auto",
    temporal_stabilization: float = 0.0,
    color_strength: float = 1.0,
    tone_preservation: float = 0.0,
    nr_passes: int = 1,
    face_skin_protection: float = 0.0,
    grain_preservation: float = 0.0,
    native_shimmer_suppression: float = 0.70,
    prefer_nvof: bool = False,
    start: float = 0.0,
    duration: float | None = None,
    codec: str = "H.264",
    cancel=None,
    progress=None,
) -> dict[str, object]:
    runtime_name, implementation = backend.runtime()

    if runtime_name == "v10":
        if float(output_scale) != 1.0:
            raise RuntimeError(
                "The preferred DLSS 5 runtime currently supports 1.0x output. "
                "Use NR Working Resolution for the quality/performance tradeoff."
            )
        v10_style = "Natural" if style == "Default" else style
        stats = render_dlss5_v10(
            source,
            destination,
            implementation,
            scale=1.0,
            style=v10_style,
            intensity=float(intensity),
            local_tone=float(local_tone),
            local_structure=float(local_structure),
            skin_structure=float(skin_structure),
            automatic_mask=bool(automatic_mask),
            nr_passes=int(nr_passes),
            color_strength=float(color_strength),
            tone_preservation=float(tone_preservation),
            face_skin_protection=float(face_skin_protection),
            grain_preservation=float(grain_preservation),
            shimmer_suppression=float(native_shimmer_suppression),
            prefer_nvof=bool(prefer_nvof),
            nr_working_scale=nr_working_scale,
            recompose_backend=recompose_backend,
            temporal_stabilization=float(temporal_stabilization),
            start=float(start),
            duration=duration,
            codec=codec,
            cancel=cancel,
            progress=progress,
        )
        stats["dlss5_runtime"] = "v10"
        stats["compatibility_fallback"] = False
        return stats

    unsupported = []
    if int(nr_passes) != 1:
        unsupported.append("NR passes > 1")
    if float(face_skin_protection) != 0.0:
        unsupported.append("face/skin protection")
    if float(grain_preservation) != 0.0:
        unsupported.append("grain preservation")
    if bool(prefer_nvof):
        unsupported.append("Prefer NVIDIA Optical Flow")
    if float(native_shimmer_suppression) != 0.70:
        unsupported.append("native shimmer suppression")
    if unsupported:
        raise RuntimeError(
            "These settings require the preferred DLSS 5 runtime: "
            + ", ".join(unsupported)
            + ". Refresh the DLSS 5 runtime preflight or reset those controls."
        )

    options = _legacy_options(
        implementation,
        output_scale=float(output_scale),
        nr_preset=nr_preset,
        style=style,
        model_preset=model_preset,
        intensity=float(intensity),
        local_tone=float(local_tone),
        local_structure=float(local_structure),
        skin_structure=float(skin_structure),
        automatic_mask=bool(automatic_mask),
    )
    stats = render_dlss5(
        source,
        destination,
        implementation,
        options,
        start=float(start),
        duration=duration,
        codec=codec,
        cancel=cancel,
        progress=progress,
        nr_working_scale=nr_working_scale,
        recompose_backend=recompose_backend,
        shimmer_suppression=float(temporal_stabilization),
        color_strength=float(color_strength),
        tone_preservation=float(tone_preservation),
    )
    stats["dlss5_runtime"] = "v3-fallback"
    stats["compatibility_fallback"] = True
    stats["fallback_note"] = (
        "Preferred DLSS 5 runtime was not ready; the validated compatibility "
        "backend was used internally."
    )
    return stats
