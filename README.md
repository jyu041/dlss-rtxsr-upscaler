<div align="center">

# NVIDIA Video Enhancer

**A local Windows workbench for NVIDIA-powered video enhancement.**

Preview frames, preview clips, and render complete videos through four primary GPU backend families. Your media stays on your machine.

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![NVIDIA RTX](https://img.shields.io/badge/NVIDIA-RTX-76B900?logo=nvidia&logoColor=white)](https://www.nvidia.com/geforce/graphics-cards/)
[![Local processing](https://img.shields.io/badge/processing-local%20only-2E7D32)](#security-model)
[![License](https://img.shields.io/badge/License-MIT-2563EB.svg)](LICENSE)

**Unofficial community project. Not affiliated with or endorsed by NVIDIA.**

</div>

<div align="center">
  <img src="docs/assets/ui-overview.png" alt="NVIDIA Video Enhancer interface showing RTX VSR, DLSS Super Resolution, and DLSS 5 controls" width="100%">
</div>

## Choose Your Backend

The backends are selected explicitly. If a required runtime is missing, incompatible, or unapproved, that backend reports diagnostics and stops; it never silently switches to another processor.

| Backend | Best for | Starting point | Setup state |
| --- | --- | --- | --- |
| **RTX Video Super Resolution** | Ordinary video, compression artifacts, practical cleanup | 2× · ULTRA | Python/VFX runtime installed by `setup.bat` |
| **DLSS Super Resolution** | Temporal super resolution through a native D3D12 host | Quality · Default model | Host/runtime installed and self-test attempted by `setup.bat` |
| **DLSS Frame Generation** | Temporal interpolation through the DLSS-G worker | 2× / 3× / 4× | Worker + pinned compatibility runtime + NVIDIA provider installed and validated by `setup.bat` |
| **DLSS 5 Neural Rendering** | CGI-like or AI-generated content where reinterpretation is acceptable | 1× native · Natural | Experimental; separate approval/runtime gate remains |

### What each one does

- **RTX VSR** reconstructs and cleans up conventional video through NVIDIA's RTX Video SDK.
- **DLSS SR** runs standalone NVIDIA NGX DLSS Super Resolution with DIS optical-flow guidance. It is not a game integration and does not receive engine motion vectors.
- **DLSS-G** generates intermediate frames from consecutive decoded frames using NVIDIA Optical Flow, the project C55 worker, a pinned SM86 compatibility runtime, and the pinned official NVIDIA provider. It is frame generation, not an upscaler.
- **DLSS 5** uses a separately approved local Feature-18 worker. It is a neural rendering experiment, not a conventional detail-preserving upscaler; faces, materials, and lighting may be reinterpreted.

## Highlights

- Local Gradio UI bound to `127.0.0.1` with no public share link
- Before/after frame preview and short clip preview
- Full-video rendering with progress, GPU/VRAM monitoring, and cancellation
- H.264 or HEVC NVENC output in MP4, MKV, or MOV containers
- Audio preservation through the video render pipeline
- Saved settings and presets for each backend
- Manifest-driven runtime downloads with pinned URLs, hashes, destinations, and validation gates
- Normal RTX VSR, DLSS SR, and DLSS-G use does not require manually downloading backend DLLs or entering executable paths in the UI
- No backend fallback, silent runtime downloads at application startup, or unapproved proprietary binary substitution

## Architecture

```mermaid
flowchart LR
    A[Local Gradio UI] --> B[Video input]
    B --> C[Decode frames]
    C --> D{Explicit backend selection}
    D --> E[RTX VSR<br/>NVIDIA VFX]
    D --> F[DLSS SR<br/>Native D3D12 + NGX]
    D --> G[DLSS-G<br/>Frame Generation worker]
    D --> H[DLSS 5<br/>Feature-18 worker]
    E --> I[GPU processing]
    F --> I
    G --> I
    H --> I
    I --> J[NVENC H.264 / HEVC]
    J --> L[Output video + preserved audio]
    K[setup.bat managed runtimes<br/>pinned + hash verified] -. gates .-> E
    K -. gates .-> F
    K -. gates .-> G
    M[Experimental user approval] -. gates .-> H
```

## Quick Start

### Prerequisites

The source-checkout workflow assumes the following are already installed:

- **Windows 10/11 x64**
- **NVIDIA RTX GPU** with a current compatible NVIDIA Game Ready or Studio driver
- **Git for Windows** — current stable release recommended
- **Miniconda** — recommended; Anaconda is also supported
- **FFmpeg + FFprobe with NVENC** on `PATH` — a current full Gyan FFmpeg build is a known-good choice
- **Microsoft Visual C++ 2015-2022 Redistributable x64**

The project setup owns the Conda environment and managed backend files. Users should not need to collect backend executables/DLLs from other repositories or paste runtime paths into the normal UI.

### Install and run

From a Git-enabled terminal:

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

`setup.bat` performs the provisioning step. It:

1. creates or updates the dedicated `dlss-rtxsr-upscaler` Conda environment;
2. installs the pinned Python dependencies, including NVIDIA VFX and CUDA-enabled PyTorch;
3. verifies FFmpeg/FFprobe and H.264/HEVC NVENC support;
4. downloads and verifies the project-owned C55 DLSS-G worker and validated DLSS SR host/runtime from the public `v0.1.0-beta.2` release;
5. downloads the pinned SM86 0.3.1 DLSS-G compatibility runtime from its public upstream source;
6. downloads the pinned official NVIDIA DLSS-G provider from the public Streamline release;
7. stores those components in canonical project-managed `runtime/` locations;
8. attempts the DLSS SR self-test and bounded DLSS-G 2X/3X/4X compatibility validation; and
9. writes `config/source_env.bat` so `start.bat` uses the managed runtime locations automatically.

All downloaded managed components are checked against source-controlled identity policy before activation. `setup.bat` is an explicit user-initiated network action; ordinary `start.bat` startup does not silently download or replace runtime files.

If a hardware validation fails, setup keeps the verified files installed and reports the backend as unavailable/needs validation rather than asking the user to browse for a DLL. The Runtime Manager remains available for inspection, repair, updates, and experimental components.

Open the printed localhost URL, upload an owned or synthetic test video, choose one backend, preview a frame or clip, and then render. The UI prefers a ready RTX VSR backend for a fresh session instead of defaulting to experimental DLSS 5.

### Existing beta package

The public `v0.1.0-beta.2` release remains available as the validated pre-Phase-5 beta package. It already contains the C55 worker, DLSS SR host, and validated official DLSS SR runtime, but its application source predates the current `main` branch. New users should prefer the current source-checkout workflow above.

The detailed setup is documented in [`docs/INSTALL.md`](docs/INSTALL.md). Development notes are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Requirements By Backend

| Backend | Additional local requirement after `setup.bat` |
| --- | --- |
| RTX VSR | Compatible GPU/driver; the pinned NVIDIA VFX Python package is installed by setup |
| DLSS SR | Compatible GPU/driver; host/runtime are installed automatically and setup attempts the local self-test |
| DLSS-G | Compatible GPU/driver; C55, SM86 compatibility runtime, and official NVIDIA provider are installed automatically and setup attempts the bounded compatibility validation |
| DLSS 5 | Retained protocol client, separately approved execution runtime, exact hashes, signed Feature-18 evidence, and the required Windows Firewall outbound block |

Backend availability depends on the installed GPU, driver, and exact runtime combination. RTX 30/40/50-series hardware may expose different capabilities; DLSS 5 support must not be inferred from community experiments alone. See [`docs/DLSS5_APPROVAL.md`](docs/DLSS5_APPROVAL.md) for the approval contract.

## Managed Runtime Layout

A normal source installation uses canonical project paths such as:

```text
runtime/
├── dlss-sr-host/
│   ├── dlss_sr_host.exe
│   └── nvngx_dlss.dll
├── dlssg/
│   ├── worker/
│   │   └── dlssg_sm86_offline.exe
│   ├── candidate-0.3.1/
│   │   ├── version.dll
│   │   └── dlssg_sm86.ini
│   └── official/
│       └── nvngx_dlssg.dll
└── ...
```

Advanced environment-variable overrides remain supported for development and validation, but they are not part of the normal user workflow.

## Security Model

This project is designed for local, explicit, auditable processing:

- The UI binds to localhost and does not enable Gradio sharing.
- `setup.bat` explicitly retrieves pinned managed components from their recorded public sources and verifies archive/file identities before activation.
- The project does **not** redistribute the externally licensed DLSS-G compatibility/provider files in the Git repository; setup downloads them directly from their recorded upstream sources on the user's explicit request.
- Ordinary application startup does not silently fetch or replace runtime files.
- DLSS 5 requires explicit approval and a firewall outbound block for the worker.
- Missing, invalid, incompatible, or unapproved runtimes fail closed with diagnostics.
- The application does not silently resize, sharpen, switch backends, or fetch replacement runtime files.

Read the full audit in [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md).

## Limitations

- The current pipeline targets SDR RGBA video.
- DLSS SR uses estimated optical flow rather than engine-provided motion vectors and may fail around cuts, occlusion, hair, and transparency.
- DLSS-G compatibility validation is hardware/runtime dependent; verified files alone do not guarantee that a given GPU/driver combination passes the bounded test.
- DLSS 5 is experimental, hardware- and runtime-dependent, and may alter semantic content.
- Performance and output quality vary substantially by source media, codec, resolution, driver, and backend runtime.
- NVIDIA runtimes and community runtime files remain subject to their own licenses and are not covered by this repository's MIT license.

## Tested Hardware

Primary development and hardware validation has been performed on:

- Phase 4C / beta.2 validation: NVIDIA GeForce RTX 3070 Ti 8 GB, Windows 11
  build 26200, NVIDIA driver 610.62
- Other development testing also includes RTX 3070 where separately documented.

This is a development and validation configuration, not a minimum requirement or a claim of official NVIDIA support for every backend. Backend availability depends on the installed GPU, driver, and exact runtime combination; in particular, this does not establish official DLSS 5 support on RTX 30-series hardware. GPU smoke tests count as validation only when the relevant local runtime is actually present.

For the validation classes and commands, see [`docs/TESTING.md`](docs/TESTING.md). A skipped hardware test is not a successful backend validation.

## Project Structure

```text
src/                    Python application and video pipelines
native/dlss_sr_host/    Standalone D3D12 DLSS SR host
tests/                  Deterministic and explicit hardware tests
docs/                   Installation, architecture, security, and approval notes
third_party/            Retained protocol dependency and local SDK staging area
setup.bat               Conda + managed runtime provisioning
start.bat               Local UI launcher
```

## Documentation

- [`docs/INSTALL.md`](docs/INSTALL.md) - installation and backend setup
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - pipeline and host architecture
- [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) - security and runtime policy
- [`docs/DLSS5_APPROVAL.md`](docs/DLSS5_APPROVAL.md) - DLSS 5 provenance and approval
- [`docs/TESTING.md`](docs/TESTING.md) - deterministic and hardware validation
- [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) - dependency and retained-source licensing
- [`CONTRIBUTING.md`](CONTRIBUTING.md) - development and contribution guidelines

## Acknowledgements

This project uses the following software and technologies; acknowledgement does not imply endorsement:

- NVIDIA for RTX Video Super Resolution, NGX DLSS, Streamline, and related developer technologies
- The maintainers of the retained [`ComfyUI-DLSS5-Enhancer`](third_party/ComfyUI-DLSS5-Enhancer) protocol client
- The upstream SM86 DLSS-G compatibility project referenced by the managed runtime manifest
- FFmpeg for media decoding, encoding, and muxing
- Gradio for the local UI
- OpenCV for image and frame processing
- PyTorch for tensor and CUDA operations

Beta packaging may redistribute only the specifically validated DLSS SR application host and official REL runtime under the applicable NVIDIA terms. The source repository does not redistribute the managed external DLSS-G compatibility/provider archives; `setup.bat` retrieves the pinned files directly from their public upstream sources. DLSS5 execution runtimes and model files remain separately gated.

## License

Project-owned source is released under the [MIT License](LICENSE). Third-party components and proprietary runtimes retain their respective licenses. See [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) for the inventory.
