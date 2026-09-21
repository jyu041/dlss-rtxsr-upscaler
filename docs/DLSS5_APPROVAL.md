# DLSS5 Runtime Approval

DLSS 5 Neural Rendering remains optional and **experimental**. The application
now exposes one DLSS 5 mode. The isolated Visual Enhancer v10 application path
is the preferred implementation when its explicit preflight is ready; the
validated Feature-18 v3 runtime is retained only as an internal compatibility
fallback while broader v10 coverage is still being established. The earlier v9
candidate remains historical static-audit evidence.

## Normal setup path

`setup.bat` now offers an explicit opt-in to provision the validated v3 runtime.
The user can answer the setup prompt, set `NVE_SETUP_DLSS5=1` before running
setup to make that choice explicitly in advance, or run the provisioner later:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\provision_dlss5_v3.py
```

Set `NVE_SETUP_DLSS5=0` to skip the optional DLSS 5 step without a prompt.

The project Conda environment uses `conda-forge` plus `nodefaults`, so normal
project bootstrap does not need the Anaconda `repo.anaconda.com` default
channels or their local Terms-of-Service cache.

At the beginning of setup, before Conda or any setup-time downloader is invoked,
`setup.bat` checks the process environment for the known local discard-proxy
pattern `127.0.0.1:9`/`localhost:9`/`::1:9`. This configuration is commonly
injected by sandboxed automation shells to intentionally deny child-process
network access. Setup does not bypass that security boundary; it exits
immediately with an actionable message instead of spending minutes in Conda or
urllib retries. Run setup again from a normal network-enabled terminal.

For the normal DLSS 5 path, the exact verified upstream v3.0 ZIP is persisted at:

```text
runtime/cache/dlss5-v3/DLSS.5.Visual.Enhancer.v3.0.zip
```

A later provisioning, UAC, or Feature-18 self-test retry reuses that cache only
if the archive still matches the pinned size and SHA-256. A corrupt cache entry
is deleted and reacquired. This avoids repeatedly downloading the ~467 MB
release after a later-stage failure.

If the exact upstream v3.0 ZIP is already available, setup can use it directly:

```bat
set NVE_DLSS5_ARCHIVE=C:\path\to\DLSS.5.Visual.Enhancer.v3.0.zip
setup.bat
```

This bypasses only the DLSS 5 archive download; the normal project bootstrap
still requires whatever network access is needed for Conda and the other
managed runtime components.

The provisioner uses `DLSS.5.Visual.Enhancer.v3.0.zip` from the public Merserk
upstream release. This repository does not redistribute the archive or its
proprietary/third-party runtime files. The pinned archive identity is:

- size: `466919995` bytes
- SHA-256: `6F0590D81677484F4ECDFAA5C44FC2A0E1A3835D33EEFC59D656E6C3BCF35F6A`

Before any runtime file is activated, the provisioner validates the complete ZIP
namespace for traversal, symlink and case-insensitive collision hazards, then
extracts only the five runtime files used by the retained protocol client. Each
file must match the previously validated identity exactly:

| File | SHA-256 |
|---|---|
| `nvngx.dll` | `AE871BF387B84E59154DD666BBB6C0E03F466FAA2BA99687D7144C13E69F3DDF` |
| `renodx-dlss5.addon64` | `D5ADF82EB44B065F4C590AC91FE824BAB07AFEA0EB9F994BDE936710C8593952` |
| `nvngx_dlssnr.dll` | `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` |
| `dxgi.dll` | `0CEE63F9C9F13F3AC909C5B4903F4DBB4B719A7AB3B4F13B0DEAF83C814B94F7` |
| `nvngx_dlss.dll` | `C85F971CE023C9F3492FC7455F0B01A24BA18EA39636407A846902C4360B0B7E` |

The staged five-file payload then receives one Windows Authenticode trust
observation per file. The provisioner first uses PowerShell
`Get-AuthenticodeSignature`; if `Microsoft.PowerShell.Security` is unavailable,
it falls back to the native Windows `WinVerifyTrust` API with cache-only URL
retrieval. An empty or partial result is an error. Authenticode is recorded as
provenance information because not every component is expected to be signed;
it is not used to pretend that unsigned third-party files are signed.

The same payload is scanned with Microsoft Defender using `MpCmdRun.exe`, and a
clean scan result is required for automatic approval. The exact five file hashes
are rechecked after Authenticode inspection and again after the Defender scan so
security tooling or other local changes cannot silently alter the staged files
between verification and activation.

After those checks pass, the provisioner atomically activates the runtime at:

```text
runtime/dlss5-v3/
```

The exact five file hashes are checked again after activation. The provisioner
then requests Windows elevation to create an enabled **Outbound / Block**
firewall rule for the exact installed `nvngx.dll` worker. The application
independently verifies that exact program-path rule before allowing the backend
to become ready, and the provisioner performs another runtime hash check after
the firewall operation.

Only after the file, scan and firewall gates pass does the provisioner create
the gitignored local `runtime/dlss5-v3/approval.json`. The approval records the
upstream source, archive identity, exact five runtime hashes, Authenticode
observations, Defender result, firewall rule and explicit user decision. Any
runtime hash change invalidates that approval in the backend.

Finally, the provisioner runs:

```powershell
python -m src.backends.dlss5_selftest
```

The self-test re-verifies the approval, hashes and firewall rule, exercises a
synthetic five-frame Feature-18 session, requires Feature-18 execution evidence,
and writes the gitignored `runtime/dlss5-v3/selftest.json`. The backend becomes
`EXPERIMENTAL READY` only when the successful self-test hashes still match the
installed runtime.

If provisioning, scanning, elevation or the hardware self-test fails, setup
continues for the other backends and DLSS 5 remains unavailable. It does not
fall back to an unapproved runtime.

## Current hardware scope

The executable v3 self-test remains intentionally constrained to the validated
RTX 3070-family/Ampere path. On the exercised RTX 3070 Ti pairing, DLSS 5 output
scale `1.0x` is the accepted path. Higher DLSS output scales are blocked before
worker launch because the tested v3 pairing reproducibly fell back with NGX
`InvalidParameter (0xBAD00005)`.

This project evidence does not establish official NVIDIA RTX 30 DLSS 5 support
and does not automatically generalize the validated result to other RTX 30,
RTX 40 or RTX 50 GPUs. Broader hardware/runtime combinations require their own
execution evidence before the project should promote them.

## Existing archive / offline import

A user who already has the exact public v3.0 release ZIP can avoid the DLSS 5
archive network download while retaining every other gate:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\provision_dlss5_v3.py --archive C:\path\to\DLSS.5.Visual.Enhancer.v3.0.zip
```

The supplied archive must match the same pinned size and SHA-256. Arbitrary
runtime folders and replacement DLLs are not accepted by the managed path.

## Preferred v10 runtime behind the unified DLSS 5 mode

Visual Enhancer v10 is not executed silently by setup. Runtime Manager retains
the pinned upstream artifact and the Configuration page performs the explicit
archive/staging/Defender preflight. Once that preflight is ready,
`DLSS5UnifiedBackend` selects v10 automatically for the single user-facing
**DLSS 5** mode. If it is not ready, the validated v3 runtime may be used
internally when available.

The v10 boundary preserves the materially different in-process D3D12/NGX bridge
plus caller-shim lifecycle: bridge ABI 6, process-lifetime NGX state, isolated
child execution, exact runtime identity, fresh Microsoft Defender preflight,
temporary exact-interpreter outbound firewall blocking, process-tree checks,
per-frame NGX/CUDA/timestamp/geometry/reset validation, scene-aware resets, and
mandatory clean CLOSE/cleanup.

The preferred path now wraps that native session with the runtime-agnostic
quality/performance layer previously validated on v3: deterministic reduced
working resolution, residual recomposition, optional temporal residual
stabilization, and shared color/tone controls. Native v10 1–4 pass, face/skin,
grain, shimmer, and NVOF controls remain available. A v10-only setting is never
silently ignored by the compatibility backend.

The native-input hardware scope remains SDR RGBA8, 1.0x output and up to
1920x1080-equivalent input. Reduced working resolution changes the internal
neural workload and recomposes onto the native source; it is not evidence of
native >1.0x NGX output scaling or a wider validated input boundary on Ampere.

On 2026-09-19 the exact application renderer passed on the RTX 3070 Ti at both
640x480 for 90 frames and 1920x1080 for 30 frames. Both runs completed the
pinned archive/static gate and clean Defender scan, initialized bridge ABI 6 on
GPU ordinal 0, preserved the application containment contract, returned a clean
host `CLOSED`, and ended with `DLSS5_V10_APP_SMOKE_PASS`. This establishes the
current experimental application boundary on that tested configuration; it is
not a claim of official RTX 30-series DLSS 5 support or perceptual superiority.
See `docs/DLSS5_V10_APP_HARDWARE_2026-09-19.md`.

The earlier v9 candidate remains available as historical static-audit evidence.
