from html import escape

RTX_TOOLTIPS = {
    "mode": "Super Resolution provides general NVIDIA VSR reconstruction and upscaling. High Bitrate targets clean source material. Deblur reduces mild softness at 1x. Denoise reduces visible noise at 1x.",
    "scale": "Target spatial scale. For example, 720p at 2x produces approximately 1440p dimensions. Deblur and Denoise remain 1x-only.",
    "quality": "LOW, MEDIUM, HIGH, and ULTRA trade processing cost against reconstruction quality. ULTRA is not guaranteed to look better on every source.",
}

DLSS5_TOOLTIPS = {
    "builtin_preset": "Built-in application preset that fills the DLSS5 controls. It is separate from named user settings.",
    "scale": "DLSS5 Neural Rendering output scale. The preferred runtime is currently validated at 1.0x output; use NR Working Resolution to trade neural workload against quality without changing final dimensions. The retained compatibility runtime may expose separately validated scale choices.",
    "working_scale": "Experimental. Runs optical flow and Neural Rendering at a smaller resolution, then applies the neural residual to the native frame. This is separate from DLSS output scale and currently requires 1.0x output.",
    "recompose": "Reduced-resolution NR only. CUDA performs residual upscaling and composition on the GPU; CPU remains available as a compatibility fallback.",
    "shimmer_suppression": "Application-level temporal stabilization. Stabilizes only the Neural Rendering residual with motion compensation and resets history at scene cuts; 0 disables it.",
    "color_strength": "Controls how much Neural Rendering chroma/color change is retained. 0 keeps source chroma while preserving structural/luma edits; 1 keeps full neural color.",
    "tone_preservation": "Removes broad Neural Rendering luma shifts while retaining local structural detail. 0 keeps the full neural tone; 1 maximizes source-tone preservation.",
    "v10_nr_passes": "Neural Rendering pass count on the preferred runtime. More passes strengthen the processed effect and cost more time; they are enhancement-strength choices, not a simple quality ranking.",
    "v10_shimmer": "Native shimmer-suppression control on the preferred runtime. It is separate from the application-level temporal residual stabilizer. The retained default is 0.70.",
    "v10_nvof": "Experimental preference for NVIDIA Optical Flow on the preferred runtime. Keep off unless bounded A/B testing on the target hardware proves a benefit.",
    "nr_preset": "Selects the Neural Rendering profile exposed by the runtime. Preset #1, #2, and #3 are runtime profiles; no universal quality ranking is assumed.",
    "nr_style": "Rendering character. Natural is more restrained; Cinematic applies a stronger stylized response; Default leaves the runtime choice active.",
    "model_preset": "NVIDIA model-preset hint affecting fine detail, temporal behavior, and reconstruction. Default is the safest general choice.",
    "intensity": "Overall Neural Rendering strength. Higher values allow stronger material, lighting, and detail changes; the runtime may clamp or saturate the response.",
    "tone": "Local luminance and contrast reconstruction strength. High values can produce stronger lighting contrast or local shading.",
    "structure": "Local structural/detail enhancement strength. Higher values may reveal skin, hair, and material structure but can amplify artifacts or temporal instability.",
    "skin": "Skin-specific structural detail when the applicable mask path is active. Higher values can make pores and surface detail harsher or artificial.",
    "mask": "Enables the runtime automatic targeted mask. It gates the skin-specific processing path where supported; it does not guarantee face detection accuracy.",
}

DLSS_SR_TOOLTIPS = {
    "mode": "DLAA runs genuine DLSS Super Resolution at native output resolution. Quality is approximately 1.5x, Balanced 1.724x, Performance 2x, and Ultra Performance 3x output scaling. Larger ratios trade fine reconstruction quality for higher output resolution.",
    "model_preset": "Controls the NVIDIA NGX render/model preset hint. Different hints can affect temporal behavior and fine reconstruction. Default is the general-purpose starting choice.",
}


def help_icon(text: str, label: str = "More information") -> str:
    return f'<span class="setting-help" tabindex="0" role="button" aria-label="{escape(label)}">&#9432;<span class="setting-tooltip">{escape(text)}</span></span>'


def help_html(text: str, label: str):
    return help_icon(text, label)


def setting_label(label: str, tooltip: str) -> str:
    """Render the label and accessible help affordance as one compact row."""
    return f'<div class="setting-label-row"><span class="setting-label-text">{escape(label)}</span>{help_icon(tooltip, "Help for " + label)}</div>'
