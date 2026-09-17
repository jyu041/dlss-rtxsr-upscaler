# Installation

## Current source checkout (recommended)

Use Windows 10 or 11 x64 with a compatible NVIDIA driver, Miniconda or
Anaconda, FFmpeg/FFprobe with NVENC available on `PATH`, and the Microsoft
Visual C++ 2015-2022 Redistributable x64.

Clone the public repository and run:

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

`setup.bat` creates/updates the dedicated `dlss-rtxsr-upscaler` Conda
environment, installs Python 3.11, Gradio, PyTorch CUDA 12.8, the official
`nvidia-vfx` package and the other pinned Python dependencies, then verifies
FFmpeg/FFprobe and requires both `h264_nvenc` and `hevc_nvenc`.

The setup step also explicitly bootstraps the validated project resources that
used to live only in the private resources repository:

- C55 DLSS-G worker, SHA-256
  `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`
- DLSS SR host, SHA-256
  `E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB`
- validated official DLSS SR REL runtime, SHA-256
  `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`

They are downloaded from this project's public `v0.1.0-beta.2` release through
the manifest-driven Runtime Manager. The release ZIP is pinned to SHA-256
`F32F8D9586D3A3006D5E26549D9BAB74DD33E10326157D5AEE4620C9DD0006C8`,
and extracted files are re-verified before activation. An outside user does
not need access to `dlss-rtxsr-upscaler-resources`.

The setup operation is an explicit network action initiated by the user. Normal
`start.bat` startup does not silently download project or optional runtimes.

If FFmpeg is not already available, install a reputable full build such as:

```powershell
winget install --id Gyan.FFmpeg --source winget
```

Restart the shell and rerun `setup.bat`.

For isolated developer or validation runs only, set `NVE_CONDA_ENV` to a
temporary Conda environment name before running `setup.bat` and `start.bat`.
The default remains `dlss-rtxsr-upscaler`; the override is not required for
normal users and accepts only letters, numbers, underscore, period, and hyphen.
If a host cannot resolve a custom named environment with `conda run -n`, set
`NVE_CONDA_PREFIX` to the exact existing environment prefix.

## Existing Beta.2 package

The public `v0.1.0-beta.2` ZIP remains available and already contains the
validated C55 worker, DLSS SR host, and official DLSS SR REL runtime. Its
application source predates the current `main` branch, so new users should
prefer the source-checkout workflow above.

## Backend requirements

RTX VSR needs the compatible official NVIDIA VFX package and an NVIDIA GPU.
The source setup installs the pinned Python package; the backend remains
hardware/driver dependent.

DLSS SR uses the publicly bootstrapped validated native D3D12 host and official
REL `nvngx_dlss.dll`. Developers need the NVIDIA SDK headers/libraries only to
rebuild the host; normal users do not. A first-use local self-test is still
required:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\check_dlss_sr_readiness.py --selftest
```

DLSS Frame Generation receives the validated C55 worker from the public project
release during setup. The external community and/or official DLSS-G runtime is
still a separately licensed component and is not silently installed. Inspect
available managed components with:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\manage_runtime.py inventory
```

The pinned official Streamline provider can be explicitly installed through
the Runtime Manager. The current SM86 0.3.1 runtime remains a compatibility
candidate and requires its compatibility attestation. The older validated
legacy community runtime remains user supplied.

DLSS 5 is experimental and optional. It needs the retained generic protocol
client, a separately obtained local runtime, a user-approved
`runtime/dlss5-v3/approval.json`, exact hash matches, and the required Windows
Firewall outbound block. The runtime and model files are not bundled by this
project.

If an optional backend is unavailable, the UI reports the reason and refuses
that operation. It does not silently resize, switch backends, or download
replacement files.

## Developer native builds

Developers may rebuild the native project workers from source. Native builds
require separately staged NVIDIA SDK headers/libraries and the appropriate
Visual Studio C++ toolchain. These SDK inputs are not needed by a normal user
after the validated public project binaries have been bootstrapped.

For the DLSS SR host, place the compatible NVIDIA SDK under
`third_party/local/nvidia-dlss-sdk-full`, then run:

```powershell
native\dlss_sr_host\build.bat
```

The application is local-only and binds its UI to localhost. For security and
provenance requirements, see `docs/SECURITY_AUDIT.md`, `docs/THIRD_PARTY.md`,
and `docs/DLSS5_APPROVAL.md`.
