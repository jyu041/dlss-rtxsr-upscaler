# Installation

## Beta package user

Download the official project beta ZIP, optionally verify its published
SHA-256, extract it to a normal directory, and run `setup.bat` from the
extracted directory. Then run `start.bat`. The archive includes the validated
project worker but never includes community or official NVIDIA runtime DLLs.

Use Windows 10 or 11 x64 with a compatible NVIDIA driver, Miniconda or
Anaconda, and FFmpeg/FFprobe available on `PATH` (the full Gyan build is
recommended for NVENC). The scripts use only the dedicated
`dlss-rtxsr-upscaler` Conda environment and do not modify system Python,
ComfyUI, or another application environment.

For isolated developer or validation runs only, set `NVE_CONDA_ENV` to a
temporary Conda environment name before running `setup.bat` and `start.bat`.
The default remains `dlss-rtxsr-upscaler`; the override is not required for
normal users and accepts only letters, numbers, underscore, period, and hyphen.
If a host cannot resolve a custom named environment with `conda run -n`, set
`NVE_CONDA_PREFIX` to the exact existing environment prefix; this selects the
same environment without changing the default behavior.

The packaged C55 worker uses the Microsoft Visual C++ runtime (`/MD`). Install
the Microsoft Visual C++ 2015-2022 Redistributable x64 separately if it is not
already present. It is not bundled by this project. The readiness check reports
missing runtime DLLs explicitly.

## Developer checkout

Developers may clone the repository and run the same scripts from the
repository root. Native builds require separately staged NVIDIA SDK headers
and libraries; those are not needed by a beta user after package extraction.

The environment installs Python 3.11, Gradio, PyTorch CUDA 12.8, the official
`nvidia-vfx` package, and the other pinned Python dependencies. NVIDIA and
PyTorch package indexes are declared in `environment.yml`. FFmpeg is a system
dependency because the Conda-forge build tested on the validation PC could not
load its Windows DLLs. `setup.bat` verifies
both tools and requires `h264_nvenc` and `hevc_nvenc`. If the Conda build cannot
load on your Windows host, install the reputable full build with
`winget install --id Gyan.FFmpeg --source winget`, restart the shell, and rerun
`setup.bat`.

## Backends

RTX VSR needs the compatible official NVIDIA VFX package and an NVIDIA GPU.
DLSS SR beta.2 is designed to ship the validated native D3D12 host and the
official SDK REL `nvngx_dlss.dll` beside it, subject to NVIDIA notices and
terms. Developers still need the SDK headers/libraries only to rebuild the
host; normal users do not. The recommended starting mode is DLSS Quality with
the Default model preset.

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

DLSS Frame Generation runtime selections are saved locally after a field
changes and before Preview Clip or Render Video. They are stored in the
ignored `config/settings.local.json`; environment variables are optional
bootstrap fallbacks, not required user configuration. Missing files do not
clear saved paths.

## DLSS-G readiness

Run this non-mutating check before the first render:

```powershell
python tools\check_dlssg_readiness.py
```

It reports separate SYSTEM, PROJECT, COMMUNITY, and OFFICIAL checks and exits
zero when all statically checkable prerequisites pass. The result is
`DLSS-G STATICALLY READY` when the external runtime directory is configured,
but that directory remains `CONFIGURED / UNVALIDATED` until native
initialization succeeds; a production render is the full validation gate. The project worker must be the
validated Phase 4A identity; the community `version.dll` must match the
documented hash; the official NVIDIA NGX directory and the driver-provided
`C:\Windows\System32\nvofapi64.dll` must be supplied by the user. The command
never downloads, copies, loads, or substitutes runtimes. Use `--json` for
automation and `--verbose` only when local paths and observed hashes are
appropriate to disclose.
