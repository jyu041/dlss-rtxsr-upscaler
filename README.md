# NVIDIA Video Enhancer

NVIDIA Video Enhancer is a local, Windows-only utility for three separate
enhancement backends:

- **RTX Video Super Resolution (RTX VSR)** reconstructs and reduces artifacts
  in ordinary video through NVIDIA's RTX Video SDK.
- **Standalone DLSS Super Resolution (DLSS SR)** uses a native D3D12 host and
  NVIDIA NGX. It uses the recommended Quality + Default starting configuration,
  DIS optical-flow guidance, and strict runtime hash validation.
- **Experimental DLSS 5 Neural Rendering** uses a separately supplied local
  worker and approved runtime. It is intended for CGI-like or AI-generated
  content and may reinterpret faces, materials, and lighting.

The backends are selected independently. The application never silently
substitutes one backend for another.

## Install

Requirements:

- Windows 10 or 11 x64
- An NVIDIA GPU and a compatible NVIDIA driver
- Miniconda or Anaconda
- FFmpeg and FFprobe on `PATH`
- A compatible official NVIDIA VFX package for RTX VSR
- A separately obtained NVIDIA DLSS SDK/runtime for DLSS SR
- A separately obtained and manually approved DLSS 5 runtime for DLSS 5

Run `setup.bat`, then `start.bat`. The application listens only on localhost.
It does not download proprietary runtimes, model weights, media, or external
worker packages.

## Runtime policy

NVIDIA, NGX, DLSS, RTX Video, ReShade, RenoDX, and community worker binaries
are not distributed in this repository. They remain subject to their own
licenses and must be supplied by the user from a legitimate source.

DLSS SR requires the native host, an approved `nvngx_dlss.dll`, and a passing
self-test. DLSS 5 additionally requires a user-approved manifest, exact hash
matches, signed Feature-18 evidence, and an enabled Windows Firewall outbound
block for the worker. Missing or unapproved runtimes produce diagnostics; they
do not trigger fallback processing.

## Development

The Python tests can be run with:

```powershell
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pytest
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
```

Build the standalone host after placing a compatible local NVIDIA SDK under
`third_party/local/nvidia-dlss-sdk-full`:

```powershell
native\dlss_sr_host\build.bat
```

Build output and local SDK files are ignored. See `docs/INSTALL.md`,
`docs/SECURITY_AUDIT.md`, `docs/DLSS5_APPROVAL.md`, and
`docs/PUBLIC_RELEASE_CHECKLIST.md` for setup and release details.

## Limitations

This utility processes SDR RGBA video. DLSS SR motion is estimated optical
flow rather than engine-provided motion vectors and can fail around cuts,
occlusion, hair, and transparency. DLSS 5 is experimental, hardware and
runtime dependent, and is not an NVIDIA product or endorsement. Current public
NVIDIA DLSS 5 material describes 3D-Guided Neural Rendering as targeting RTX
50 Series; no RTX 30 support should be inferred from community experiments.

The project currently has no root `LICENSE` file. A project-license decision
is still required before public release.
