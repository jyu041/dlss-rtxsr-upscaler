# Security and Provenance Audit

Audit date: 2026-09-02. No third-party repository script, installer, EXE, DLL, or release asset was executed. No proprietary NVIDIA binary was downloaded.

## Comfy-Org RTX reference

- URL: https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI
- Owner: Comfy-Org; Apache-2.0; current reference commit `892515e3eb9a4920a131a502a047e47adca9eb0d` (verified GitHub commit, 2026-03-18).
- Review: public Python repository, small tree, requirements only `nvidia-vfx`; one GitHub Action publishes to the Comfy registry. No submodules, LFS, native binaries, shell scripts, credential/cookie access, persistence, listeners, or download-and-execute behavior observed from metadata/tree and source inspection.
- Native files: none downloaded; SHA256/signature/Defender: not applicable.
- Decision: **APPROVED WITH CAUTION** as a pinned reference only. It is not imported and full ComfyUI is not installed.

## Merserk DLSS5 reference

- URL: https://github.com/Merserk/dlss5-visual-enhancer
- Owner: Merserk; MIT source license; pinned reference commit `c12102a12cff368200755e52586d4f0e1fa57ec2` (verified GitHub commit, 2026-09-01).
- Review: very new repository, six recent upload commits, no GitHub Actions, contains Python source, `start.bat`, and a `bin/` directory. Source inspection found subprocess-based media/runtime orchestration using list commands and no shell=True, download, persistence, credential, cookie, or listener behavior. The repository license does not establish redistribution rights or provenance for DLSS/NGX/ReShade/RenoDX/native files. No native file was downloaded or executed.
- Native files: none used; SHA256/signature/Defender: not applicable.
- Decision: **APPROVED WITH CAUTION** as documentation/architecture reference only. DLSS5 is unavailable until the user supplies an audited, legally obtained runtime.

## NVIDIA RTX Video SDK / nvidia-vfx

- Official source: https://developer.nvidia.com/rtx-video-sdk
- NVIDIA terms apply. The package was not auto-installed because package availability/version compatibility must be confirmed against the installed driver and SDK documentation. No native files were downloaded; no signature or Defender result applies.
- Decision: **NOT EXECUTED** in this environment.

## Other dependencies

Gradio, NumPy, PyAV, psutil, pytest, and pip-audit are pinned in `requirements.txt` and are installed only in the named Conda environment. FFmpeg is requested from conda-forge. Package audit is required after installation. No proprietary files are tracked by `.gitignore`.
