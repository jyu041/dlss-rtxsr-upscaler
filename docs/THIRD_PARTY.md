# Third-Party Software

Project-owned source is licensed under the MIT License in the root `LICENSE`
file. That license does not apply to any dependency listed below.

| Dependency | License or terms | Purpose |
|---|---|---|
| [Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer) at `796ed5927a202ba50b5c929cd08e16b365041162` | MIT for its source; runtime binaries retain separate terms | Retained generic DLSS5 protocol, session, settings, motion, and diagnostics code |
| NVIDIA RTX Video SDK / `nvidia-vfx` | NVIDIA terms | RTX VSR backend; installed separately from the official NVIDIA index |
| NVIDIA DLSS SDK / NGX runtime | NVIDIA terms | Standalone DLSS SR native host; supplied locally and never redistributed |
| NVIDIA DLSS5/Neural Rendering runtime | NVIDIA terms | Optional experimental backend; supplied, approved, and hash-gated locally |
| PyTorch `2.10.0+cu128` | PyTorch license | CUDA/DLPack support for RTX VSR |
| FFmpeg and FFprobe | Depends on the user-supplied build | Video decode, encode, and media inspection |
| Gradio, NumPy, Pillow, PyAV, OpenCV, psutil, SciPy, Matplotlib, pytest, pip-audit, nvidia-ml-py | See package metadata and pinned requirements | Python application and test dependencies |

The NVIDIA, NGX, DLSS, ReShade, RenoDX, and community worker binaries are not
covered by the project's source-code terms and are not included here. Review
the applicable vendor terms before obtaining or using them.
