# Third-Party Software

Project-owned source is licensed under the MIT License in the root `LICENSE`
file. That license does not apply to third-party dependencies or runtime
artifacts.

| Dependency | License or terms | Purpose / current use |
|---|---|---|
| [Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer) at `796ed5927a202ba50b5c929cd08e16b365041162` | MIT for its source; runtime binaries retain separate terms | Retained generic DLSS5 protocol, session, settings, motion, and diagnostics code |
| NVIDIA RTX Video SDK / `nvidia-vfx` | NVIDIA terms | RTX VSR backend; installed as a Python dependency during source setup |
| NVIDIA DLSS SDK / NGX runtime | NVIDIA RTX SDK terms and accompanying notices | Standalone DLSS SR host/runtime and native project build inputs |
| NVIDIA Streamline / DLSS-G provider | NVIDIA/Streamline and included third-party terms | Official DLSS-G provider installed from the pinned public Streamline release |
| [sdli1995/dlssg_for_sm86](https://github.com/sdli1995/dlssg_for_sm86) | GPLv3 source ancestry plus separate NVIDIA/third-party binary terms | Pinned SM86 direct-host runtime downloaded from the recorded public source; newer proxy candidate retained for explicit experimentation |
| Project C55/grid4 DLSS-G workers | Project-owned object code plus applicable NVIDIA SDK notices/terms | C55 default worker and separate hardware-validated grid4 candidate distributed by this project through pinned releases |
| NVIDIA DLSS 5 / Neural Rendering v3 runtime | NVIDIA and bundled third-party terms | Optional experimental Feature-18 backend; exact upstream archive is downloaded only after explicit provisioning and is hash/scan/firewall/self-test gated |
| [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) v10.0 | Merserk Source License 1.0 for project-owned v10 material; NVIDIA and other bundled components retain their respective terms | Source of the pinned v10 experimental runtime archive used by explicit preflight/application execution; archive is not source-tracked or redistributed as ordinary repository content |
| [Merserk/dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) v9.0 | MIT for the v9-tagged source; bundled NVIDIA, mpv, Python, FFmpeg, and other binaries retain their terms | Historical static-audit candidate; not a current application backend |
| PyTorch `2.10.0+cu128` | PyTorch license | CUDA support and DLSS 5 recomposition/diagnostics |
| FFmpeg and FFprobe | Depends on the user-supplied build | Video decode, NVENC encode, muxing, and media inspection |
| Gradio, NumPy, Pillow, PyAV, OpenCV, psutil, SciPy, Matplotlib, pytest, pip-audit, nvidia-ml-py | See package metadata and pinned requirements | Python application, telemetry, media, testing, and audit dependencies |

The NVIDIA, NGX, DLSS, Streamline, community runtime, and other third-party
artifacts are not relicensed under the project's MIT license.

The source repository intentionally does not track the external DLSS-G runtime
DLLs or the DLSS 5 runtime archives. Normal setup/provisioning may retrieve
pinned artifacts from their recorded public sources after explicit user action.
Redistribution status varies by component; consult
`src/runtime_manager/manifest.json`, `THIRD_PARTY_NOTICES.md`, and
`docs/legal/BINARY_DISTRIBUTION_NOTICES.md` before packaging a release.
