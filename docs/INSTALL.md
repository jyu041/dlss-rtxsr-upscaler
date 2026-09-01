# Installation

Use Windows Miniconda/Anaconda and an NVIDIA driver supporting the desired SDK. From the project directory run `setup.bat`, then `start.bat`. Both scripts use only `dlss-rtxsr-upscaler`; they do not activate or modify base, WAN2GP, ComfyUI, or system Python. FFmpeg is resolved from PATH; the current machine has the Gyan.dev full build installed. The app does not download or bundle FFmpeg.

Python 3.11 was selected as the conservative intersection for current Gradio and NVIDIA VFX integration. The official `nvidia-vfx==0.1.0.1` wheel is installed from `https://pypi.nvidia.com`; it includes the VSR feature library. PyTorch `2.10.0+cu128` is installed from the official PyTorch CUDA 12.8 index for the DLPack bridge. Install both only in this environment.

For DLSS5, set `DLSS5_RUNTIME_DIR` to a directory containing legitimately obtained runtime files. Do not copy proprietary DLLs into Git or download them from mirrors. The adapter remains unavailable unless an explicit audited integration is implemented.

Manual checks: `conda run -n dlss-rtxsr-upscaler python -m pip check`, `conda run -n dlss-rtxsr-upscaler python -m pip_audit`, and `conda run -n dlss-rtxsr-upscaler python -m src.core.diagnostics`.
