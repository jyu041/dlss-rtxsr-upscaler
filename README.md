# NVIDIA Video Enhancer

A local Windows utility for NVIDIA RTX Video Super Resolution (RTX VSR), standalone NVIDIA NGX DLSS Super Resolution, and DLSS 5 Neural Rendering. It is designed for low-resolution or CGI-like AI-generated video, including WAN2GP output.

RTX VSR is fast video reconstruction and artifact reduction. Use it when the source looks correct but needs resolution. DLSS SR is genuine NVIDIA NGX SuperSampling through the separate local native D3D12 host. DLSS 5 is neural rendering/material and lighting enhancement through the separately approved community worker. These are separate implementations and are selected independently; there is no combined mode.

DLSS SR video uses one persistent native host per job, raw RGBA8 frames, DIS optical-flow motion guidance, zero renderer jitter, constant baseline depth, scene-cut resets, and NVENC output. It is an SDR offline-video baseline: motion vectors are estimated rather than engine-provided, and decoded frames contain no native renderer depth or jitter.

The application never substitutes another upscaler when a backend is unavailable. DLSS5 Runtime v3.0 is approved for local experimental use after manual review, exact hash matching, Microsoft Defender scanning, and VirusTotal review. The closed-source worker remains local-only, and existing Windows Firewall rules block its network access. Proprietary runtime files are not included in Git or downloaded by the application.

## Install and run

1. Install current Miniconda/Anaconda and NVIDIA drivers. A reputable FFmpeg build is supplied by conda-forge in the dedicated environment.
2. Run `setup.bat` from this directory.
3. Run `start.bat`; open the localhost URL shown.

The environment is `dlss-rtxsr-upscaler`, Python 3.11. `PYTHONNOUSERSITE=1` prevents user-site leakage and no ComfyUI environment is modified.

## Suggested workflow

- Low quality, mostly-correct video: RTX VSR, 2x, ULTRA.
- Temporal reconstruction/upscaling: DLSS SR, with Quality as the general-purpose starting mode and Default or K as initial NGX preset hints.
- CGI/3D-animation-like video: DLSS 5, Natural, Photoreal Balanced, native first.
- Preview a representative frame before a full render.

## Limitations

DLSS5 can change faces and details; stronger values increase reinterpretation. DLSS SR optical flow is not game-engine motion vectors and can artifact around cuts, occlusion, hair, and transparency. The DLSS SR and community DLSS5 paths are SDR RGBA8-oriented and do not promise HDR preservation. RTX 30 compatibility may be slower/limited. Enhancement cannot repair fundamentally broken animation.

See `docs/INSTALL.md`, `docs/SECURITY_AUDIT.md`, `docs/DLSS5_APPROVAL.md`, `docs/TESTING.md`, and `docs/TROUBLESHOOTING.md`.

The compact system bar reports cached CPU, RAM, GPU, and VRAM usage. Render jobs expose frame progress, smoothed FPS, elapsed time, and an ETA based on recent processing speed; the ETA is an estimate and can change with workload and model startup. RTX VSR, DLSS5, and DLSS SR settings have keyboard-focusable information icons. Named settings are stored independently in the gitignored `config/user_presets.json`; last-used values are stored in `config/settings.local.json`. These files contain settings only, not runtime binaries or media.
