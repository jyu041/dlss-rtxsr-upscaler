from html import escape

RTX_TOOLTIPS = {
    "mode": "Super Resolution provides general NVIDIA VSR reconstruction and upscaling. High Bitrate targets clean source material. Deblur reduces mild softness at 1x. Denoise reduces visible noise at 1x.",
    "scale": "Target spatial scale. For example, 720p at 2x produces approximately 1440p dimensions. Deblur and Denoise remain 1x-only.",
    "quality": "LOW, MEDIUM, HIGH, and ULTRA trade processing cost against reconstruction quality. ULTRA is not guaranteed to look better on every source.",
}

DLSS5_TOOLTIPS = {
    "builtin_preset": "Built-in application preset that fills the DLSS5 controls. It is separate from named user settings.",
    "scale": "Neural Rendering output scale: 1.0x is native/DLAA-style, 1.5x Quality, approximately 1.724x Balanced, 2.0x Performance, and 3.0x Ultra Performance. Higher scales are substantially slower on RTX 30.",
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
    "scale": "Standalone DLSS Super Resolution would select native/DLAA or an upscale mode, but the approved worker currently exposes no SR-only protocol path.",
    "model_preset": "Standalone SR model selection is not exposed because the approved worker always continues into its DLSS5 Feature-18 pass.",
}


def help_icon(text: str, label: str = "More information") -> str:
    return f'<span class="setting-help" tabindex="0" role="button" aria-label="{escape(label)}">&#9432;<span class="setting-tooltip">{escape(text)}</span></span>'


def help_html(text: str, label: str):
    return help_icon(text, label)
