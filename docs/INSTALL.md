# Installation

Use Windows Miniconda/Anaconda and an NVIDIA driver supporting the desired SDK. From the project directory run `setup.bat`, then `start.bat`. Both scripts use only `dlss-rtxsr-upscaler`; they do not activate or modify base, WAN2GP, ComfyUI, or system Python. FFmpeg is resolved from PATH; the current machine has the Gyan.dev full build installed. The app does not download or bundle FFmpeg.

Python 3.11 was selected as the conservative intersection for current Gradio and NVIDIA VFX integration. The official `nvidia-vfx==0.1.0.1` wheel is installed from `https://pypi.nvidia.com`; it includes the VSR feature library. PyTorch `2.10.0+cu128` is installed from the official PyTorch CUDA 12.8 index for the DLPack bridge. Install both only in this environment.

DLSS5 Runtime v3.0 is approved for local experimental use on the reviewed RTX 3070 machine only. The exact local approval manifest is `runtime/dlss5-v3/approval.json`; it is gitignored and requires every approved hash to match. The staged runtime is under `runtime/audit/dlss5-v3/extracted/bin/runtime`, and its worker path must remain covered by the existing Windows Firewall outbound block rule. Do not copy proprietary binaries into Git or use changed binaries without a new manual approval.

Run the first controlled synthetic check with `conda run -n dlss-rtxsr-upscaler python -m src.backends.dlss5_selftest`. It uses protocol v4, five 128x128 synthetic frames, DLAA/native 1x, and requires signed Feature-18 evidence before the backend reports `EXPERIMENTAL READY`. No personal media is used by the self-test.

The pinned generic protocol reference is `third_party/ComfyUI-DLSS5-Enhancer` at commit `796ed5927a202ba50b5c929cd08e16b365041162`. ComfyUI is not installed or imported.

The UI includes cached live CPU/RAM/GPU/VRAM metrics, persistent job progress and ETA, accessible setting help icons, and independent saved RTX VSR/DLSS5 settings. User presets are stored in gitignored `config/user_presets.json`; last-used settings are stored in gitignored `config/settings.local.json`. Neither file contains native binaries, runtime hashes, input paths, or video content.

DLSS Super Resolution is shown as a separate capability, but is intentionally unavailable with the approved runtime. Its v4 protocol has no request that disables the DLSS5 Feature-18 addon, so the application never substitutes a resize, RTX VSR, or DLSS5 result.

Manual checks: `conda run -n dlss-rtxsr-upscaler python -m pip check`, `conda run -n dlss-rtxsr-upscaler python -m pip_audit`, and `conda run -n dlss-rtxsr-upscaler python -m src.core.diagnostics`.
