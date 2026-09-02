# NVIDIA Video Enhancer

A local Windows utility for two technologies only: NVIDIA RTX Video Super Resolution (RTX VSR) and DLSS 5 Neural Rendering. It is designed for low-resolution or CGI-like AI-generated video, including WAN2GP output.

RTX VSR is fast reconstruction and artifact reduction. Use it when the source looks correct but needs resolution. DLSS 5 is neural rendering/material and lighting enhancement. Use it for synthetic-looking renders that would benefit from a more photographic response. The combined order is DLSS 5, then RTX VSR.

The application never substitutes another upscaler when a backend is unavailable. DLSS5 Runtime v3.0 is approved for local experimental use after manual review, exact hash matching, Microsoft Defender scanning, and VirusTotal review. The closed-source worker remains local-only, and existing Windows Firewall rules block its network access. Proprietary runtime files are not included in Git or downloaded by the application.

## Install and run

1. Install current Miniconda/Anaconda and NVIDIA drivers. A reputable FFmpeg build is supplied by conda-forge in the dedicated environment.
2. Run `setup.bat` from this directory.
3. Run `start.bat`; open the localhost URL shown.

The environment is `dlss-rtxsr-upscaler`, Python 3.11. `PYTHONNOUSERSITE=1` prevents user-site leakage and no ComfyUI environment is modified.

## Suggested workflow

- Low quality, mostly-correct video: RTX VSR, 2x, ULTRA.
- CGI/3D-animation-like video: DLSS 5, Natural, Photoreal Balanced, native first. The current full-video combined workflow remains deferred until a lossless bridge is available.
- Preview a representative frame before a full render.

## Limitations

DLSS5 can change faces and details; stronger values increase reinterpretation. Optical flow is not game-engine motion vectors and can artifact around cuts, occlusion, hair, and transparency. The community path is SDR RGBA8-oriented and does not promise HDR preservation. RTX 30 DLSS5 compatibility may be slower/limited. Enhancement cannot repair fundamentally broken animation.

See `docs/INSTALL.md`, `docs/SECURITY_AUDIT.md`, `docs/DLSS5_APPROVAL.md`, `docs/TESTING.md`, and `docs/TROUBLESHOOTING.md`.
