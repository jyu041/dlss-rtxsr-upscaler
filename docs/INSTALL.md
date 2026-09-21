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

Clone the public repository and run from PowerShell:

```powershell
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
.\setup.bat
.\start.bat
```

In Command Prompt, use `setup.bat` and `start.bat` without the leading
`.\`. Setup first looks for `conda` in the current shell and then checks
the common per-user, LocalAppData, and ProgramData Miniconda/Anaconda install
locations. The resolved Conda executable is written to
`config/source_env.bat`, so normal later startup does not require reopening
the same Conda-enabled terminal.

`setup.bat` is the provisioning boundary for a normal user. It creates/updates
the dedicated `dlss-rtxsr-upscaler` Conda environment, installs Python 3.11,
Gradio, PyTorch CUDA 12.8, the official `nvidia-vfx` package and the other
pinned Python dependencies, then verifies FFmpeg/FFprobe and requires both
`h264_nvenc` and `hevc_nvenc`.

After the machine prerequisites are present, normal users should not need to
visit another repository to collect backend DLLs/executables, copy files into
project folders, or enter absolute runtime paths in the UI. The retained
DLSS 5 v3 compatibility runtime remains experimental, so setup asks for an
explicit opt-in before provisioning that fallback.

## Managed runtime provisioning

The setup step explicitly downloads and verifies the managed backend components
from source-controlled public locations.

### Project bootstrap resources

The project-owned/validated Beta.2 resources are retrieved from this project's
public `v0.1.0-beta.2` release:

- C55 DLSS-G worker, SHA-256
  `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916`
- experimental managed grid4 DLSS-G worker, from the separate
  `dlssg-grid4-worker-v1` project release, SHA-256
  `E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881`;
  its exact 209,002-byte release ZIP is pinned to SHA-256
  `5A6644CC78EFEFB3705C80E7859D53C0E75081AAAE33C676D0DC451BE74B80C9`
- DLSS SR host, SHA-256
  `E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB`
- validated official DLSS SR REL runtime, SHA-256
  `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`

The release ZIP is pinned to SHA-256
`F32F8D9586D3A3006D5E26549D9BAB74DD33E10326157D5AEE4620C9DD0006C8`,
and extracted files are re-verified before activation. An outside user does
not need access to `dlss-rtxsr-upscaler-resources`.

### DLSS Frame Generation

Setup provisions the normal DLSS-G runtime set through the manifest-driven
Runtime Manager:

- the project C55 worker under `runtime/dlssg/worker/`;
- the separately pinned project grid4/GPU-resident NVOF worker under
  `runtime/dlssg/grid4-worker/`; the archive also installs its build
  provenance, NVIDIA RTX SDK license, and third-party notices;
- the validated SM86 direct-host `version.dll` and `dlssg_sm86.ini` from pinned
  upstream commit `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40` under
  `runtime/dlssg/legacy/`;
- the pinned official NVIDIA 310.9.1 DLSS-G provider from the public Streamline
  release under `runtime/dlssg/official/`.

The `legacy` profile name is retained for identity compatibility; it is the
normal validated C55 profile. The exact `version.dll` has SHA-256
`C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
and size 15,667,520 bytes. The exact INI has SHA-256
`FD7F0722194E6E8D8C085327D9826EFFB411925A69A5E7549D70EFF26A9F18B5`
and size 581 bytes. This runtime combination has retained RTX 3070 Ti evidence
for 2X Frame Generation plus 3X/4X Multi Frame Generation.

The optional `grid4-gpu-candidate` application profile uses the exact managed
worker SHA-256
`E097BC87558D6E12ECE1963E67CD7330570BCFBF6C6ED336B10F1EF6DF2A5881`.
That exact packaged worker passed the managed 640x480 / 2X real-video gate on
the RTX 3070 Ti: 442 input frames produced exactly 884 output frames, duration
and audio were preserved, interpolation-disable and device-removal failure
lists were empty, and the worker/decoder/encoder exited cleanly. This is a
hardware-tested experimental profile, not the default; C55/grid1 remains the
normal path. See `docs/MFG_GRID4_MANAGED_WORKER_HARDWARE_2026-09-19.md`.

The external community/provider files are not redistributed by this source
repository. `setup.bat` is an explicit user-initiated network action that
downloads them directly from the public upstream URLs recorded in
`src/runtime_manager/manifest.json` and checks the recorded hashes/sizes before
activation.

Setup then runs a bounded local 2X/3X/4X validation through
`tools/validate_dlssg_candidate.py --profile legacy`. It exercises both the
external deterministic motion-vector path and NVIDIA Optical Flow. A validation
failure is reported explicitly; setup does not silently swap to the newer proxy
runtime or another backend.

The newer SM86 `candidate-0.3.1` proxy generation remains available in Runtime
Manager for explicit experimentation. It is not the normal C55 runtime because
the tested candidate did not satisfy the same direct-host startup contract.

The generated `config/source_env.bat` records the canonical normal locations:

```text
runtime/dlssg/worker/dlssg_sm86_offline.exe
runtime/dlssg/grid4-worker/dlssg_sm86_offline.exe
runtime/dlssg/legacy/version.dll
runtime/dlssg/legacy/dlssg_sm86.ini
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

The application exposes one DLSS 5 mode and uses the pinned Visual Enhancer v10
runtime as its preferred implementation.

During `setup.bat`, the user gets one question:

```text
Enable DLSS 5 now? [Y/N]
```

Choosing Yes runs the single managed provisioner:

```powershell
python tools\provision_dlss5_v10.py
```

That command:

1. reuses the exact verified v10 archive if it is already cached;
2. otherwise downloads `Visual.Enhancer.v10.0.zip` from the pinned upstream
   release;
3. verifies the complete 690,203,043-byte archive against SHA-256
   `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`;
4. extracts only the manifest allowlist into an isolated staging directory;
5. verifies the pinned runtime identities/static ABI evidence;
6. requires a clean Microsoft Defender custom scan;
7. verifies the runtime identities again after the scan;
8. atomically stages the runtime under
   `runtime/dlss5/neuroframe-v10-candidate/`; and
9. verifies that the application-facing DLSS 5 backend reports ready.

The verified ZIP remains at
`runtime/downloads/Visual.Enhancer.v10.0.zip`. If the Defender preflight later
expires, the application can refresh the local scan from that cached archive
without another network download.

The setup prompt can be controlled in advance:

```bat
set NVE_SETUP_DLSS5=1
setup.bat
```

Use `NVE_SETUP_DLSS5=0` to skip DLSS 5. If the exact pinned v10 archive is
already available locally:

```bat
set NVE_DLSS5_ARCHIVE=C:\path\to\Visual.Enhancer.v10.0.zip
setup.bat
```

The supplied archive is still checked against the same pinned size and SHA-256
and copied into the managed cache before staging.

If setup was skipped or a later repair is needed, use **Configuration → DLSS 5
runtime → Install / Repair DLSS 5**. That button calls the same provisioner; it
is not a separate installation path.

The tested native-input boundary remains SDR RGBA8, 1.0x output, and up to
1920x1080-equivalent input. Reduced neural working resolution is an
application-level workload control and does not widen that boundary.

The older v3 Feature-18 implementation remains in the repository only as an
internal compatibility path for existing/manual legacy installations. It is no
longer downloaded or requested during normal setup, and availability of the old
upstream v3 archive is not required for a fresh installation.

See `docs/DLSS5_APPROVAL.md`,
`docs/DLSS5_V10_APP_HARDWARE_2026-09-19.md`, and
`docs/DLSS5_UNIFIED_V10_HARDWARE_2026-09-21.md`.

## Startup behavior

`start.bat` first uses a complete portable runtime when one is present. For a
normal source checkout it loads `config/source_env.bat` and starts the project
through the Conda environment created by `setup.bat`.

Ordinary startup does not download backend files. Runtime downloads and repairs
occur only through the explicit setup/Runtime Manager/DLSS5 provisioner actions.

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
Visual Studio C++ toolchain. These SDK inputs are not needed by a normal user after the validated public
project binaries have been bootstrapped. In particular, selecting the managed
grid4 profile does not require the user to install the DLSS, NVAPI, or Optical
Flow SDKs or rebuild the instrumented worker locally.

For the DLSS SR host, place the compatible NVIDIA SDK under
`third_party/local/nvidia-dlss-sdk-full`, then run:

```powershell
native\dlss_sr_host\build.bat
```

The application is local-only and binds its UI to localhost. For security and
provenance requirements, see `docs/SECURITY_AUDIT.md`, `docs/THIRD_PARTY.md`,
and `docs/DLSS5_APPROVAL.md`.
