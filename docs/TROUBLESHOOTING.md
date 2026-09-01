# Troubleshooting

Run `python -m src.core.diagnostics` inside the named Conda environment first. If FFmpeg is unavailable, rerun `setup.bat`. If RTX VSR says unavailable, install the exact official NVIDIA VFX package for the compatible driver and verify `import nvvfx`; no similarly named package is accepted. If DLSS5 says unavailable, this is expected until a legally obtained and separately audited runtime is configured. HDR warnings are intentional: the DLSS5 path must not be described as HDR-preserving.
