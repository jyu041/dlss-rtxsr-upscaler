# Installation

## Normal source checkout

The normal workflow assumes these machine prerequisites are already installed:

- Windows 10 or 11 x64
- a compatible NVIDIA RTX GPU and current compatible NVIDIA Game Ready or Studio driver
- Git for Windows
- Miniconda (recommended) or Anaconda
- FFmpeg/FFprobe with `h264_nvenc` and `hevc_nvenc` available on `PATH`
- Microsoft Visual C++ 2015-2022 Redistributable x64

A current full Gyan FFmpeg build is a known-good Windows choice. If FFmpeg is
not already available, one installation option is:

```powershell
winget install --id Gyan.FFmpeg --source winget
```

Restart the shell after changing `PATH`.

Clone the public repository and run:

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

`setup.bat` is the provisioning boundary for a normal user. It creates/updates
the dedicated `dlss-rtxsr-upscaler` Conda environment, installs Python 3.11,
Gradio, PyTorch CUDA 12.8, the official `nvidia-vfx` package and the other
pinned Python dependencies, then verifies FFmpeg/FFprobe and requires both
`h264_nvenc` and `hevc_nvenc`.

After the machine prerequisites are present, normal users should not need to
visit another repository to collect backend DLLs/executables, copy files into
project folders, or enter absolute runtime paths in the UI.

## Managed runtime provisioning

The setup step explicitly downloads and verifies the managed backend components
from source-controlled public locations.

### Project bootstrap resources

The project-owned/validated Beta.2 resources are retrieved from this project's
public `v0.1.0-beta.2` release:

- C55 DLSS-G worker, SHA-256
  `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`
- DLSS SR host, SHA-256
  `E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB`
- validated official DLSS SR REL runtime, SHA-256
  `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`

The release ZIP is pinned to SHA-256
`F32F8D9586D3A3006D5E26549D9BAB74DD33E10326157D5AEE4620C9DD0006C8`,
and extracted files are re-verified before activation. An outside user does
not need access to `dlss-rtxsr-upscaler-resources`.

### DLSS Frame Generation

Setup also provisions the normal DLSS-G runtime set through the manifest-driven
Runtime Manager:

- the project C55 worker under `runtime/dlssg/worker/`;
- the pinned SM86 0.3.1 compatibility runtime under
  `runtime/dlssg/candidate-0.3.1/`;
- the pinned official NVIDIA provider from the public Streamline release under
  `runtime/dlssg/official/`.

The external files are not redistributed by the source repository. `setup.bat`
is an explicit user-initiated network action that downloads them directly from
the public upstream URLs recorded in `src/runtime_manager/manifest.json` and
checks the recorded identities before use.

Setup then runs the bounded `tools/validate_dlssg_candidate.py` compatibility
validation. On a compatible machine it records the current 2X/3X/4X attestation.
If the validation does not pass, the verified files remain installed and the
backend stays unavailable/needs validation. The user is not asked to browse for
`version.dll` or `nvngx_dlssg.dll`.

The generated `config/source_env.bat` records the canonical managed locations:

```text
runtime/dlssg/worker/dlssg_sm86_offline.exe
runtime/dlssg/candidate-0.3.1/version.dll
runtime/dlssg/official/
```

Advanced environment-variable overrides remain supported for development, but
are not part of the normal user workflow.

### DLSS Super Resolution

DLSS SR uses the publicly bootstrapped validated native D3D12 host and official
REL `nvngx_dlss.dll`. Developers need NVIDIA SDK headers/libraries only to
rebuild the host; normal users do not.

`setup.bat` automatically attempts the local self-test:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\check_dlss_sr_readiness.py --selftest
```

If the machine cannot pass the self-test, the verified host/runtime remain
installed and the UI reports the readiness reason rather than falling back to a
substitute processor.

### RTX Video Super Resolution

RTX VSR needs the compatible official NVIDIA VFX package and an NVIDIA GPU. The
source setup installs the pinned Python package; final availability remains
hardware/driver dependent.

### DLSS 5

DLSS 5 remains an experimental exception to the zero-manual-runtime contract.
The current execution backend still requires a separately approved Feature-18
runtime, exact hash matches, the local approval contract, a verified self-test,
and the required Windows Firewall outbound block. The repository has pinned
static Neuroframe research components, but they are not yet promoted to the
validated execution runtime used by the main DLSS 5 backend.

Until that provenance/execution boundary is resolved, setup does not pretend the
DLSS 5 backend is turnkey and does not silently substitute a different runtime.
See `docs/DLSS5_APPROVAL.md`.

## Startup behavior

`start.bat` first uses a complete portable runtime when one is present. For a
normal source checkout it loads `config/source_env.bat` and starts the project
through the Conda environment created by `setup.bat`.

Ordinary startup does not download backend files. Runtime downloads and repairs
occur only through the explicit setup/Runtime Manager actions.

For isolated developer or validation runs only, set `NVE_CONDA_ENV` to a
temporary Conda environment name before running `setup.bat` and `start.bat`.
The default remains `dlss-rtxsr-upscaler`; the override accepts only letters,
numbers, underscore, period, and hyphen. If a host cannot resolve a custom
named environment with `conda run -n`, set `NVE_CONDA_PREFIX` to the exact
existing environment prefix.

## Existing Beta.2 package

The public `v0.1.0-beta.2` ZIP remains available and already contains the
validated C55 worker, DLSS SR host, and official DLSS SR REL runtime. Its
application source predates the current `main` branch, so new users should
prefer the source-checkout workflow above.

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
