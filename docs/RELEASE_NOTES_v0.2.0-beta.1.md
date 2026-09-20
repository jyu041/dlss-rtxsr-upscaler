# NVIDIA Video Enhancer v0.2.0-beta.1

This is the first beta built around the project's **validated source-install
workflow** rather than the older prebuilt beta package.

## Recommended installation

Prerequisites remain Windows 10/11 x64, a compatible NVIDIA RTX GPU/driver,
Git, Miniconda/Anaconda, FFmpeg/FFprobe with H.264 + HEVC NVENC, and the
Microsoft Visual C++ 2015-2022 Redistributable x64.

From PowerShell:

```powershell
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
git checkout v0.2.0-beta.1
.\setup.bat
.\start.bat
```

The release intentionally does **not** include a no-Conda portable application
bundle. GitHub's generated source archives are provided for archival/reference
use, but the recursive Git clone above remains the recommended installation
method because the project has a pinned Git submodule.

## Major changes since v0.1.0-beta.2

### Managed installation and runtime handling

- `setup.bat` now creates/updates the Conda environment and provisions the
  normal managed runtime set into canonical project paths.
- The exact Conda executable used by setup is remembered for later
  `start.bat` launches, so normal startup does not depend on reopening the
  same Conda-enabled shell.
- Runtime Manager provides explicit install/update/verify/repair/remove/import
  actions without requiring users to type runtime paths into the main UI.
- Fresh recursive clone → `setup.bat` → `start.bat` is covered by a clean
  Windows GitHub Actions acceptance workflow.

### DLSS Frame Generation

- The validated C55/grid1 path remains the normal/default DLSS-G profile.
- The hardware-tested grid4 / GPU-resident NVOF profile is now available as an
  explicit experimental application option.
- The exact managed grid4 worker is pinned by archive and executable identity,
  installed automatically by setup, and validated through its own Runtime
  Manager/bootstrap gate.
- The project records RTX 3070 Ti real-video evidence for the managed grid4
  candidate while keeping C55/grid1 as the fallback/default.

### DLSS 5

- DLSS 5 v3 provisioning is now an explicit setup-time opt-in with pinned
  identity, Defender, firewall, approval, and Feature-18 self-test gates.
- **DLSS 5 v10 Experimental** is integrated as a real application mode rather
  than a research-only harness.
- The v10 application path uses pinned static identity, explicit preflight,
  isolated child-process execution, temporary outbound firewall containment,
  process-tree checks, per-frame NGX/CUDA/result validation, scene-aware resets,
  and mandatory clean close.
- The current v10 app boundary is SDR RGBA8, 1.0×, up to
  1920×1080-equivalent input.
- RTX 3070 Ti application evidence includes both a 640×480 multi-cut smoke run
  and the advertised 1920×1080 / 1.0× ceiling run.

### DLSS Super Resolution

- The project-owned standalone D3D12/NGX DLSS SR host/runtime path is managed by
  setup and Runtime Manager.
- Readiness/self-test state is exposed in Configuration rather than cluttering
  the main enhancement workflow.

### Frontend

- The WebUI was reorganized into **Enhance**, **Configuration**, and
  **Diagnostics** workspaces.
- Runtime administration, backend validation, presets, and telemetry were moved
  out of the primary video-processing workflow.
- Empty hidden Gradio placeholder shells were removed.
- Preview/output presentation, status display, spacing, and responsive behavior
  were overhauled.

### Repository and CI

- The repository root and README were cleaned for normal users.
- Generated runtime/log/temp/output/input directories are no longer tracked.
- Maintainer-only requirements and developer tooling are grouped under
  `tools/`.
- GitHub Actions use current Node 24-based official action majors.
- Dedicated CI covers ordinary tests, fresh source installation, managed grid4
  bootstrap, and grid4 worker build/self-test/package validation.

## Validation scope

Primary hardware evidence remains centered on Windows 11 with an NVIDIA
GeForce RTX 3070 Ti 8 GB. That evidence supports the exercised DLSS-G,
managed-grid4, DLSS 5 v3, and DLSS 5 v10 paths described in the repository.

This beta is **not** a claim of universal RTX 30/40/50 compatibility, official
NVIDIA support for experimental RTX 30-series DLSS 5 combinations, or
perceptual superiority of an experimental backend.

The release commit is required to pass the repository's ordinary test workflow
before the GitHub prerelease is created. Hardware-specific claims remain tied
to the recorded evidence documents rather than hosted CI runners without RTX
hardware.

## Known limitations

- The main video pipeline is SDR-focused.
- DLSS SR receives estimated optical-flow guidance rather than renderer motion
  vectors, depth, or jitter.
- Grid4/GPU-resident NVOF remains experimental even though its managed worker
  passed the recorded hardware gate.
- DLSS 5 v3 and v10 are experimental and may materially reinterpret image
  content.
- The validated Ampere DLSS 5 v3 path remains restricted to 1.0×.
- The current DLSS 5 v10 app path remains restricted to 1.0× and a maximum
  1920×1080-equivalent input.
- A no-Conda portable distribution is deliberately deferred.

## Documentation

- [Installation](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/INSTALL.md)
- [Project status](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/PROJECT_STATUS.md)
- [Testing](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/TESTING.md)
- [Security audit](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/SECURITY_AUDIT.md)
- [DLSS 5 approval](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/DLSS5_APPROVAL.md)
- [DLSS 5 v10 application hardware evidence](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/DLSS5_V10_APP_HARDWARE_2026-09-19.md)
- [Managed grid4 hardware evidence](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.1/docs/MFG_GRID4_MANAGED_WORKER_HARDWARE_2026-09-19.md)

Project-owned source remains MIT licensed. Third-party components and
proprietary NVIDIA runtimes retain their own terms. No NVIDIA endorsement is
implied.
