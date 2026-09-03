# Installation

Use Windows 10 or 11 x64 with a compatible NVIDIA driver, Miniconda or
Anaconda, and FFmpeg/FFprobe available on `PATH`. Run `setup.bat` from the
repository root, then run `start.bat`. The scripts use only the dedicated
`dlss-rtxsr-upscaler` Conda environment and do not modify system Python,
ComfyUI, or another application environment.

The environment installs Python 3.11, Gradio, PyTorch CUDA 12.8, the official
`nvidia-vfx` package, and the other pinned Python dependencies. NVIDIA and
PyTorch package indexes are declared in `environment.yml`. FFmpeg is not
bundled by this repository.

## Backends

RTX VSR needs the compatible official NVIDIA VFX package and an NVIDIA GPU.
DLSS SR needs a locally staged NVIDIA DLSS SDK to build the native D3D12 host,
an approved `nvngx_dlss.dll` beside that host, and a passing self-test. The
recommended starting mode is DLSS Quality with the Default model preset.

DLSS 5 is experimental and optional. It needs the retained generic protocol
client at `third_party/ComfyUI-DLSS5-Enhancer`, a separately obtained local
runtime, a user-approved `runtime/dlss5-v3/approval.json`, exact hash matches,
and the required Windows Firewall outbound block. The runtime and model files
are never downloaded or bundled by this project.

If an optional backend is unavailable, the UI reports the reason and refuses
that operation. It does not silently resize, switch backends, or download
replacement files.

## Build the DLSS SR host

Place the compatible NVIDIA SDK under
`third_party/local/nvidia-dlss-sdk-full`, then run:

```powershell
native\dlss_sr_host\build.bat
```

The host binary and self-test results belong in ignored
`runtime/dlss-sr-host`. The build script does not copy or redistribute an
NVIDIA runtime; supply and approve that file separately.

The application is local-only and binds its UI to localhost. For security
requirements and provenance rules, see `docs/SECURITY_AUDIT.md` and
`docs/DLSS5_APPROVAL.md`.
