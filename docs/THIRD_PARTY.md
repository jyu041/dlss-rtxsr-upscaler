# Third-party software

- Comfy-Org/Nvidia_RTX_Nodes_ComfyUI: Apache-2.0, pinned in the security audit, reference only.
- Merserk/dlss5-visual-enhancer: MIT source, pinned in the security audit, reference only. Its native dependencies are separate and not redistributed.
- NVIDIA RTX Video SDK / nvidia-vfx: NVIDIA terms; official source only; optional and not bundled.
- PyTorch `2.10.0+cu128`: official PyTorch CUDA 12.8 wheel index (`download.pytorch.org`), required for the PyTorch DLPack bridge. The wheel is not indexed by PyPI’s advisory database; `pip-audit` reports it as un-auditable rather than claiming a clean advisory result.
- DLSS/NGX/ReShade/RenoDX components: separate vendor/project terms; none bundled or executed.
- FFmpeg: system PATH build (current machine reports Gyan.dev full build); LGPL/GPL configuration varies by build, inspect `ffmpeg -L`.
- Gradio, NumPy, PyAV, psutil, pytest, pip-audit: licenses and versions are resolved by the dedicated environment lock inputs.
