# Third-Party Software

Project-owned source is licensed under the MIT License in the root `LICENSE`
file. That license does not apply to any dependency listed below.

| Dependency | License or terms | Purpose |
|---|---|---|
| [Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer) at `796ed5927a202ba50b5c929cd08e16b365041162` | MIT for its source; runtime binaries retain separate terms | Retained generic DLSS5 protocol, session, settings, motion, and diagnostics code |
| NVIDIA RTX Video SDK / `nvidia-vfx` | NVIDIA terms | RTX VSR backend; installed separately from the official NVIDIA index |
| NVIDIA DLSS SDK / NGX runtime | NVIDIA RTX SDKs License v. March 14, 2024 and accompanying terms | Standalone DLSS SR host and validated official REL runtime; beta.2 packaging must preserve NVIDIA notices, attribution, marks, and downstream protections |
| NVIDIA DLSS5/Neural Rendering runtime | NVIDIA terms | Optional experimental backend; supplied, approved, and hash-gated locally |
| [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) v9.0 | MIT for the v9-tagged source; included NVIDIA, mpv GPL/LGPL, Python, FFmpeg, and other binaries retain their respective terms | Historical external DLSS5 Neuroframe candidate inspected for Phase 5; no source or binary is incorporated |
| [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) v10.0 | Merserk Source License 1.0 for project-owned v10 material; NVIDIA and other bundled components retain their respective terms | Newest external DLSS5 Neuroframe static candidate; direct upstream download only, no redistribution by this project |
| [sdli1995/dlssg_for_sm86](https://github.com/sdli1995/dlssg_for_sm86) at `117faf5c70333b34160f5d21d01c222261cc5af1` | GPLv3 source ancestry plus separate NVIDIA/third-party binary terms | External pinned MFG candidate; downloaded only by explicit user action and never redistributed by this project |
| PyTorch `2.10.0+cu128` | PyTorch license | CUDA/DLPack support for RTX VSR |
| FFmpeg and FFprobe | Depends on the user-supplied build | Video decode, encode, and media inspection |
| Gradio, NumPy, Pillow, PyAV, OpenCV, psutil, SciPy, Matplotlib, pytest, pip-audit, nvidia-ml-py | See package metadata and pinned requirements | Python application and test dependencies |

The NVIDIA, NGX, DLSS, ReShade, RenoDX, and community worker binaries are not
covered by the project's source-code terms. Only the specifically validated
DLSS SR host/runtime package may be distributed, and only under its applicable
vendor terms; DLSS-G/community and experimental runtimes remain user-supplied.
