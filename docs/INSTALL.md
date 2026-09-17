# Installation

## Current source checkout (recommended)

Use Windows 10 or 11 x64 with a compatible NVIDIA driver, Miniconda or
Anaconda, Git, FFmpeg/FFprobe with NVENC available on `PATH`, and the Microsoft
Visual C++ 2015-2022 Redistributable x64.

Clone the public repository and run:

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

`setup.bat` is the normal installation path. It creates/updates the dedicated
`dlss-rtxsr-upscaler` Conda environment, installs Python 3.11, Gradio, PyTorch
CUDA 12.8, the official `nvidia-vfx` package and the other pinned Python
dependencies, verifies FFmpeg/FFprobe, and requires both `h264_nvenc` and
`hevc_nvenc`.

It then automatically installs every supported runtime component for which the
project has a stable public download path:

- the project-owned C55 DLSS-G worker from the public `v0.1.0-beta.2` release;
- the validated DLSS SR host and official REL `nvngx_dlss.dll` from that same
  public project release;
- the validated legacy SM86 DLSS-G `version.dll` and INI directly from the
  pinned upstream `sdli1995/dlssg_for_sm86` GitHub commit;
- the pinned NVIDIA DLSS-G 310.9.1 provider directly from NVIDIA's Streamline
  v2.14.1 GitHub release;
- the DLSS 5 Visual Enhancer v3.0 runtime directly from its upstream GitHub
  release.

The private `dlss-rtxsr-upscaler-resources` repository is not required by
outside users. Third-party runtime archives are downloaded from their own
upstream projects rather than being re-hosted here.

Stable identities and release digests are checked automatically during setup.
Those checks are internal integrity checks: users do not create approval files,
copy hashes, or approve each runtime manually.

`setup.bat` also runs the DLSS SR self-test automatically and attempts the DLSS
5 Feature-18 self-test automatically. A backend-specific download or hardware
self-test failure produces a warning and leaves only that backend unavailable;
it does not prevent RTX VSR or the other working backends from being used.

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

## Backend requirements after setup

### RTX Video Super Resolution

RTX VSR needs a compatible NVIDIA GPU/driver and the NVIDIA VFX package. The
source environment installs the pinned Python package automatically. Backend
availability remains hardware/driver dependent.

### DLSS Super Resolution

The validated native D3D12 host and official REL runtime are installed
automatically. The local self-test is also attempted by `setup.bat`. If it did
not pass, it can be rerun manually for troubleshooting:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\check_dlss_sr_readiness.py --selftest
```

Normal users do not need NVIDIA SDK headers/libraries; those are only required
to rebuild the native host from source.

### DLSS Frame Generation

The standard validated DLSS-G path is automated. Setup installs:

- the frozen C55 worker;
- the validated legacy SM86 community runtime directly from its upstream
  commit;
- the pinned NVIDIA Streamline provider.

The saved source environment points the application at those managed files and
uses the validated `legacy` runtime profile by default. No manual DLL copying is
required for that path.

The newer SM86 0.3.1 runtime remains available as a separate candidate through
the Runtime Manager and retains its own compatibility-test requirement. It is
not selected automatically because the older legacy profile is the production
path already validated with C55.

Runtime inventory and repair commands remain available for troubleshooting:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\manage_runtime.py inventory
```

### DLSS 5 Neural Rendering

DLSS 5 remains experimental, but normal installation no longer requires a
manual approval manifest, manually copied hashes, or a mandatory Windows
Firewall rule.

`setup.bat` downloads the compatible Visual Enhancer v3.0 runtime directly from
its upstream GitHub release into `runtime\dlss5-v3`, then attempts the local
Feature-18 self-test. If the installed GPU/driver/runtime combination passes,
the backend becomes `EXPERIMENTAL READY` automatically.

The application still verifies that a render really executed Feature 18 rather
than silently accepting a fallback. That is a functional correctness check,
not a user approval step.

An outbound Windows Firewall block for the third-party DLSS 5 worker is
optional. Users who want one can create it themselves; the application may
report its presence diagnostically but does not require it for readiness.

If the automatic DLSS 5 download is unavailable, a user who already has a
compatible Visual Enhancer installation can copy/register its `bin\runtime`
contents with:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\bootstrap_dlss5_runtime.py --runtime-dir "D:\path\to\DLSS 5 Visual Enhancer\bin\runtime"
conda run -n dlss-rtxsr-upscaler python -m src.backends.dlss5_selftest
```

This is a fallback path, not part of normal setup.

## What still cannot be automated

The project should automate installation whenever a stable public upstream URL
exists. If a future NVIDIA or third-party component requires an account,
click-through SDK agreement, vendor portal, or other acquisition flow that
cannot be scripted reliably, the README and this document will identify that
specific file and source. Users should not be asked to perform manual runtime
work merely for provenance bookkeeping.

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

The application is local-only and binds its UI to localhost. For runtime
provenance and licensing details, see `docs/SECURITY_AUDIT.md` and
`docs/THIRD_PARTY.md`.
