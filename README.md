<div align="center">

# NVIDIA Video Enhancer

**Local Windows video enhancement for NVIDIA RTX GPUs.**

Use RTX Video Super Resolution, DLSS Super Resolution, DLSS Frame Generation,
and experimental DLSS 5 processing from one localhost UI. Video processing is
local; network access is used only for explicit setup/runtime-management
actions.

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![NVIDIA RTX](https://img.shields.io/badge/NVIDIA-RTX-76B900?logo=nvidia&logoColor=white)](https://www.nvidia.com/geforce/graphics-cards/)
[![Local processing](https://img.shields.io/badge/video%20processing-local-2E7D32)](#security-model)
[![License](https://img.shields.io/badge/License-MIT-2563EB.svg)](LICENSE)

**Unofficial community project. Not affiliated with or endorsed by NVIDIA.**

</div>

## Backends

The application exposes four selectable modes across four backend families.
Backends are explicit and fail closed. DLSS 5 is presented as one user-facing
mode: the isolated v10 runtime is preferred when its preflight is ready, while
the validated v3 path is retained only as an internal compatibility fallback.

| Mode | Purpose | Default / normal path | Provisioning |
| --- | --- | --- | --- |
| **RTX VSR** | Conventional enhancement, denoise/deblur, super resolution | Super Resolution · 2× · ULTRA | Python/VFX dependencies installed by `setup.bat` |
| **DLSS SR** | Temporal super resolution through a standalone D3D12/NGX host | Quality · Default model | Host/runtime installed by `setup.bat`; local self-test attempted |
| **DLSS Frame Generation** | 2×/3×/4× temporal interpolation | Validated C55/grid1 profile | Worker, SM86 direct-host runtime, and NVIDIA provider installed by `setup.bat`; hardware validation attempted |
| **DLSS 5** | Experimental Neural Rendering | Preferred v10 runtime; 1.0× output with Auto/100/87.5/75/67/50% neural working resolution | `setup.bat` can download, verify, stage, and Defender-scan the pinned v10 runtime in one opt-in step |

### What the modes do

- **RTX VSR** uses NVIDIA RTX Video SDK processing for conventional video enhancement.
- **DLSS SR** runs standalone NVIDIA NGX DLSS Super Resolution with estimated optical-flow motion guidance. It is not a game integration and does not receive engine motion vectors.
- **DLSS-G** generates intermediate frames from adjacent decoded frames. The normal application path uses the pinned C55/grid1 worker profile; the tested grid4/GPU-resident NVOF profile is available as an explicit experimental option.
- **DLSS 5** automatically uses the isolated v10 application path when its pinned runtime/preflight is ready. That path now supports reduced neural working resolution, residual recomposition, optional temporal residual stabilization, 1–4 neural passes, color/tone controls, face/skin and grain preservation, native shimmer control, and optional NVOF preference. If the preferred runtime is not ready, the validated v3 path can be used internally as a compatibility fallback without exposing a second DLSS 5 mode.

DLSS 5 is an experimental Neural Rendering path, not a conventional
detail-preserving upscaler. It may reinterpret faces, materials, lighting,
and other semantic content.

## Features

- Local Gradio UI bound to `127.0.0.1`; no public share link.
- Before/after frame previews and short clip previews.
- Full-video rendering with progress, cancellation, CPU/RAM/GPU/VRAM telemetry, and last-render loading.
- H.264 or HEVC NVENC output with MP4, MKV, and MOV container support.
- Audio preservation through the render pipeline.
- Backend-specific settings and reusable local presets.
- Separate **Enhance**, **Configuration**, and **Diagnostics** workspaces so runtime maintenance and telemetry stay out of the normal processing flow.
- Manifest-driven runtime management with pinned URLs, hashes, destinations, and validation policy.
- No manual runtime path entry for normal RTX VSR, DLSS SR, or validated DLSS-G use.
- No silent cross-backend substitution. When DLSS 5 uses its retained compatibility runtime, the UI reports that fallback explicitly.

## Quick Start

### Prerequisites

The source-install workflow assumes these are already installed:

- Windows 10/11 x64.
- NVIDIA RTX GPU with a compatible current NVIDIA driver.
- Git for Windows.
- Miniconda or Anaconda.
- FFmpeg and FFprobe with `h264_nvenc` and `hevc_nvenc` available.
- Microsoft Visual C++ 2015-2022 Redistributable x64.

### Install

From PowerShell:

```powershell
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
.\setup.bat
.\start.bat
```

From Command Prompt, use `setup.bat` and `start.bat` without the leading
`.\`.

That exact **clone → setup → start** path is covered by the repository's clean
Windows acceptance workflow. `setup.bat` also records the exact Conda
executable it used, so later `start.bat` launches do not depend on reopening
the same Conda-enabled shell.

### What setup does

`setup.bat`:

1. creates or updates the dedicated `dlss-rtxsr-upscaler` Conda environment;
2. installs the pinned Python dependencies;
3. verifies FFmpeg/FFprobe and NVENC encoder availability;
4. installs and verifies the normal managed DLSS-G C55 worker, the separate pinned grid4 candidate worker, the DLSS SR host/runtime, the validated SM86 direct-host runtime, and the official NVIDIA DLSS-G provider;
5. optionally provisions the preferred DLSS 5 v10 runtime after one explicit opt-in, including pinned archive verification, allowlisted staging, and a Microsoft Defender preflight;
6. attempts local DLSS SR and DLSS-G hardware validation;
7. runs diagnostics; and
8. writes `config/source_env.bat` for later launches.

A backend-specific hardware validation failure does not corrupt the installation
or cause another backend to be substituted. The affected backend remains
unavailable or marked as needing validation while other verified modes remain
usable.

For unattended/repeat setup, `NVE_SETUP_DLSS5=1` enables DLSS 5 provisioning
and `NVE_SETUP_DLSS5=0` skips its prompt. The same pinned v10 archive is kept in
the local runtime cache so later Defender-preflight refreshes do not require
another download. If repair is ever needed, use **Configuration → DLSS 5 runtime
→ Install / Repair DLSS 5**.

Detailed installation and repair notes are in
[`docs/INSTALL.md`](docs/INSTALL.md) and
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Application Layout

**Enhance** contains the normal workflow: upload video, choose a backend,
configure the selected mode, preview, and render.

**Configuration** contains backend validation, Runtime Manager, and reusable
presets. Runtime inventory and experimental preflight actions live here instead
of occupying the primary video workspace.

**Diagnostics** contains live local hardware telemetry and implementation notes.

## Runtime Model

Generated runtime, cache, log, preview, and output directories are intentionally
not tracked in Git. Setup and the application create them when required.

A normal source installation uses managed paths below `runtime/`, including:

```text
runtime/
├── dlss-sr-host/
├── dlssg/
│   ├── worker/
│   ├── grid4-worker/
│   ├── legacy/
│   └── official/
├── dlss5/\n│   └── neuroframe-v10-candidate/     # preferred DLSS 5 runtime after setup opt-in\n└── downloads/\n    └── Visual.Enhancer.v10.0.zip     # verified local cache for repair/preflight refresh
```

Advanced runtime/environment overrides remain available for development and
validation, but they are not part of the normal user workflow.

## Security Model

The project is designed around explicit, auditable local execution:

- Video processing runs locally and the UI binds to localhost.
- Setup/Runtime Manager network actions are user initiated.
- Managed components are checked against source-controlled identity policy before activation.
- The normal application does not silently download replacement runtimes at startup.
- Missing or modified runtimes fail closed with diagnostics.
- The preferred v10 runtime is installed only after explicit setup/user action, is pinned by exact archive identity, and requires a clean Defender preflight before use.
- During rendering, v10 runs through an isolated child process with temporary outbound firewall containment, process-tree checks, NGX/CUDA validation, and mandatory cleanup.
- The older v3 implementation remains code-level compatibility fallback only for existing/manual legacy installations; it is no longer part of normal onboarding.
- Experimental upstream runtime files retain their own licensing/signing properties; the project does not treat a pinned hash as a claim that third-party code is inherently safe.

See [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) and
[`docs/DLSS5_APPROVAL.md`](docs/DLSS5_APPROVAL.md) for the full policy.

## Current Limitations

- The main video pipeline targets SDR RGBA processing.
- DLSS SR uses estimated optical flow rather than renderer motion vectors, depth, or jitter.
- DLSS-G behavior is hardware/runtime dependent. C55/grid1 remains the validated default; grid4/GPU-resident NVOF is explicitly experimental.
- DLSS 5 remains experimental and may materially change image content. Higher neural-pass counts intentionally produce a stronger processed look rather than representing a simple quality ranking.
- The preferred v10 path remains restricted to 1.0× output and the existing 1920×1080-equivalent native-input validation boundary; reduced working resolution changes the neural workload, not final output dimensions.
- The retained RTX 3070-family v3 compatibility path is restricted to 1.0× output.
- Performance and visual quality vary by source content, resolution, codec, driver, GPU, and backend runtime.
- Hardware evidence in this repository is not a claim of official NVIDIA support for experimental RTX 30-series combinations.

## Validation Status

Primary hardware validation has been performed on an RTX 3070 Ti 8 GB under
Windows 11. The repository records successful evidence for the validated
DLSS-G 2×/3×/4× direct-host path, the managed grid4 candidate, validated
DLSS 5 v3 compatibility execution, and the isolated preferred v10 application path.

The current v10 application renderer has passed both a 640×480 90-frame smoke
render and the advertised 1920×1080 / 1.0× ceiling test on that hardware.
These results establish execution/containment behavior for the tested
configuration; they do **not** establish perceptual superiority or official
RTX 30-series DLSS 5 support.

Key evidence:

- [DLSS 5 v10 application hardware validation](docs/DLSS5_V10_APP_HARDWARE_2026-09-19.md)
- [Managed grid4 worker hardware validation](docs/MFG_GRID4_MANAGED_WORKER_HARDWARE_2026-09-19.md)
- [Testing classes and commands](docs/TESTING.md)
- [DLSS 5 research notes](docs/DLSS5_RESEARCH.md)

## Project Structure

```text
src/                         Application, backend adapters, UI, and video pipelines
native/                      Project native host/worker source
tests/                       Unit, integration, and explicit hardware tests
docs/                        Installation, architecture, security, and validation evidence
third_party/                 Retained third-party source/submodule material
tools/                       Runtime management, validation, packaging, and developer tooling
config/                      Source-controlled defaults; local generated config is ignored
app.py                       Application entry point
setup.bat                    Source environment + managed runtime provisioning
start.bat                    Normal local UI launcher
repair.bat                   Portable-runtime repair helper
environment.yml              Conda environment definition
requirements.txt             Primary Python dependency definition
```

Generated `runtime/`, `temp/`, `logs/`, `outputs/`, and `inputs/`
directories are local working data and are intentionally absent from a clean
Git checkout.

## Documentation

| Document | Purpose |
| --- | --- |
| [Documentation index](docs/README.md) | Current operational docs vs historical engineering evidence |
| [Changelog](CHANGELOG.md) | Concise release index |
| [Project status](docs/PROJECT_STATUS.md) | Completed scope, deferred work, hardware-dependent expansion |
| [Installation](docs/INSTALL.md) | Prerequisites, setup, runtime provisioning |
| [Architecture](docs/ARCHITECTURE.md) | Application and backend architecture |
| [Security audit](docs/SECURITY_AUDIT.md) | Runtime trust and execution policy |
| [DLSS 5 approval](docs/DLSS5_APPROVAL.md) | Experimental runtime approval contract |
| [Testing](docs/TESTING.md) | Test classes and hardware-validation rules |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common installation/runtime problems |
| [Third-party inventory](docs/THIRD_PARTY.md) | Dependency and licensing inventory |
| [Binary distribution boundary](docs/legal/BINARY_DISTRIBUTION_NOTICES.md) | Packaging/distribution constraints |
| [Development](docs/DEVELOPMENT.md) | Contributor workflow |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |

## Current Beta Release

[`v0.2.0-beta.1`](https://github.com/jyu041/dlss-rtxsr-upscaler/releases/tag/v0.2.0-beta.1)
is the current source-install beta. It is intentionally not a no-Conda portable
bundle; use the recursive clone → `setup.bat` → `start.bat` workflow
documented above.

The older `v0.1.0-beta.2` ZIP remains available as a historical prebuilt beta,
but it predates managed grid4, the DLSS 5 v10 application path, the current
frontend, hardened source onboarding, and the repository cleanup.

See [the v0.2.0-beta.1 release notes](docs/RELEASE_NOTES_v0.2.0-beta.1.md) for
the current release scope and limitations.

## Acknowledgements

This project uses NVIDIA RTX Video/NGX/Streamline technologies, FFmpeg, Gradio,
OpenCV, PyTorch, and the retained
[`ComfyUI-DLSS5-Enhancer`](third_party/ComfyUI-DLSS5-Enhancer) protocol
client. Acknowledgement does not imply endorsement.

The source repository does not bundle the external DLSS-G direct-host/provider
files or the upstream DLSS 5 runtime archives as ordinary Git content.
`setup.bat`, Runtime Manager, and the explicit v10 preflight retrieve pinned
artifacts from their recorded public sources when the user requests those
actions.

## License

Project-owned source is released under the [MIT License](LICENSE). Third-party
components and proprietary runtimes retain their respective licenses. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md),
[`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md), and
[`docs/legal/BINARY_DISTRIBUTION_NOTICES.md`](docs/legal/BINARY_DISTRIBUTION_NOTICES.md).
