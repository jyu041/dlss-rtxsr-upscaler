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
- NVIDIA terms apply. Official package `nvidia-vfx==0.1.0.1` was installed only in `<MINICONDA_ROOT>\envs\dlss-rtxsr-upscaler` from the NVIDIA index `https://pypi.nvidia.com`, using the Windows cp311 wheel. The quarantined wheel SHA256 was `FF7E3E65B4A6ACD507C3C9DDE0D8D881891B0643AF80C4ACC5B7D886463764BD`.
- The wheel includes the VFX feature/runtime libraries, including `nvngx_vsr.dll`, `nvVFXVideoSuperRes.dll`, `NVVideoEffects.dll`, TensorRT, and NPP libraries. Authenticode verification found all listed DLLs valid and signed by NVIDIA Corporation; the Python extension `_ext.cp311-win_amd64.pyd` was unsigned. Windows Defender custom scan of the installed `nvvfx` directory completed without a reported detection.
- Driver evidence: `NVIDIA GeForce RTX 3070`, driver `595.79`, CUDA capability reported `13.2`, WDDM. The driver exceeds the official Windows minimum `570.65`.
- Decision: **APPROVED WITH CAUTION** for local use. Native wheel files remain outside Git; NVIDIA proprietary terms apply.
- PyTorch native wheel: version `2.10.0+cu128`, source `https://download.pytorch.org/whl/cu128`, installed only in the named environment. `pip-audit` cannot match this local CUDA build to PyPI advisories and reports it as un-auditable; this is a coverage limitation, not a clean-vulnerability claim.

## Other dependencies

Gradio, NumPy, Pillow, psutil, setuptools, pytest, and pip-audit are pinned in `requirements.txt` and are installed only in the named Conda environment. FFmpeg is resolved from the existing system PATH build. Package audit is required after installation. No proprietary files are tracked by `.gitignore`.

## DLSS5 v2.0 release quarantine

- Official release: https://github.com/Merserk/dlss5-visual-enhancer/releases/tag/v2.0
- Release commit: `fb06227ebfe5571a22b966c70798b97ebf0b1e57`, GitHub verified signature.
- Asset URL: https://github.com/Merserk/dlss5-visual-enhancer/releases/download/v2.0/DLSS.5.Visual.Enhancer.v2.0.zip
- GitHub API digest: `d926ffbf921643ccac57f04a37c96cd790a74922defd23e65783a6b9556bd560`.
- The asset may be downloaded to `runtime/audit/dlss5-v2/` for inspection only. It must not be executed or used by the application without a separate evidence review. Native files are not redistributed.
- Because the project-specific `nvngx.dll` has no available source/build provenance and the archive contains closed native components, the runtime remains **SIGNIFICANT UNVERIFIED COMPONENTS — USER DECISION REQUIRED**. No DLSS5 execution is authorized in this sprint.
- Local quarantine result: archive SHA256 matched the GitHub API digest. Inventory contained the embedded Python 3.13 runtime, bundled FFmpeg/PyAV/application files, `dxgi.dll` (ReShade 6.8.0.2155, unsigned), `nvngx.dll` (unsigned project-specific worker), `nvngx_dlss.dll` (NVIDIA product metadata, Authenticode valid), `nvngx_dlssnr.dll` (NVIDIA metadata but unsigned), `renodx-dlss5.addon64` (unsigned), and `ReShade.ini`.
- Native hashes: `dxgi.dll` `0CEE63F9C9F13F3AC909C5B4903F4DBB4B719A7AB3B4F13B0DEAF83C814B94F7`; `nvngx.dll` `4E4688760759C3433961AB93545F9749EC50E5B06BEC2679DB8EB47514E2CE13`; `nvngx_dlss.dll` `C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E`; `nvngx_dlssnr.dll` `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927`; `renodx-dlss5.addon64` `245C06137AD13B1CA03AFAAD5100C1E8F0DCE8C11FE50A9272EA562F33CEA601`.
- Static review found list-based subprocess calls for the worker and FFmpeg, local job/report writes, and no BAT/PS1 payload in the archive. The embedded dependencies contain ordinary documentation references to network services; the production adapter will not use the embedded Python or second UI. Defender scan completed without a reported detection. Malware scan cleanliness does not establish provenance, so the runtime remains gated.

## DLSS5 v3.0 release quarantine

- Official release: https://github.com/Merserk/dlss5-visual-enhancer/releases/tag/3.0
- Asset URL: https://github.com/Merserk/dlss5-visual-enhancer/releases/download/3.0/DLSS.5.Visual.Enhancer.v3.0.zip
- GitHub API/archive SHA256: `6F0590D81677484F4ECDFAA5C44FC2A0E1A3835D33EEFC59D656E6C3BCF35F6A`; local archive matched before extraction.
- The archive was extracted only after path-safety validation into gitignored `runtime/audit/dlss5-v3/extracted/`. It contains 7,842 entries; no archive binary or script was executed.
- Native inventory, hashes, Authenticode status, and version metadata are in `runtime/audit/dlss5-v3/reports/binary_hashes.json` and `.txt`. Static source review is in `static_script_review.md`. Defender custom scan completed without a reported detection.
- Key v3 hashes: `dxgi.dll` `0CEE63F9C9F13F3AC909C5B4903F4DBB4B719A7AB3B4F13B0DEAF83C814B94F7`; `nvngx.dll` `AE871BF387B84E59154DD666BBB6C0E03F466FAA2BA99687D7144C13E69F3DDF`; `nvngx_dlss.dll` `C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E`; `nvngx_dlssnr.dll` `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927`; `renodx-dlss5.addon64` `D5ADF82EB44B065F4C590AC91FE824BAB07AFEA0EB9F994BDE936710C8593952`.
- The user manually reviewed VirusTotal results: `nvngx.dll` 1/71 (Microsoft `Trojan:Win32/Wacatac.B!ml`, accepted as residual heuristic risk); `renodx-dlss5.addon64` 2/71 (Cynet and MaxSecure generic detections, accepted residual risk); `nvngx_dlssnr.dll`, `dxgi.dll`, and `nvngx_dlss.dll` 0/71.
- Existing Windows Firewall inspection found enabled Block rules for both directions, including outbound rules, whose application filters exactly match the staged `nvngx.dll` path. No rules were created or modified.
- The pinned standalone protocol reference is `Blueforcer/ComfyUI-DLSS5-Enhancer` at commit `796ed5927a202ba50b5c929cd08e16b365041162`, under `third_party/ComfyUI-DLSS5-Enhancer`. Only its generic `dlss5.*` protocol/session/settings/motion/diagnostic code is used; ComfyUI is not installed or imported.
- Controlled local execution passed: protocol v4, 5 synthetic RGBA8 frames at 128x128, RTX 3070, clean exit, and signed Feature-18 evidence. DLSS5 status is now **EXPERIMENTAL READY** only after this result and exact hash revalidation.
- Decision: **APPROVED FOR LOCAL EXPERIMENTAL USE** after manual review. This is not a claim that the files are completely safe; the closed-source worker and residual detections remain risks. The tracked approval record is `docs/DLSS5_APPROVAL.md`.

## Standalone DLSS Super Resolution investigation

- The approved worker client speaks protocol v4 with a header field for DLSS/DLAA performance-quality selection, but no field or command-line option to disable the RenoDX DLSS5 addon or its NGX Feature-18 evaluation.
- The pinned client documents and logs the chain as DLSS/DLAA input followed by DLSS5 Neural Rendering. Its only self-test criterion is signed Feature-18 evidence. Therefore its 1x/1.5x/1.724x/2x/3x modes cannot establish standalone DLSS SR.
- `src/backends/dlss_sr.py` reports this capability boundary as `FAILED SELFTEST` and refuses processing. `src/backends/dlss_sr_selftest.py` deliberately exits without launching the worker. No resize, RTX VSR, or DLSS5 fallback is exposed as SR.
- A future SR-capable worker must be separately sourced, hash-approved, and tested before this backend can become available. No new runtime was downloaded or modified in this investigation.
