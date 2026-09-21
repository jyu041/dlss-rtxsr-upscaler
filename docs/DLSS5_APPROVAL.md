# DLSS5 Runtime Approval

DLSS 5 Neural Rendering remains optional and **experimental**. The application
now exposes one DLSS 5 mode. The isolated Visual Enhancer v10 application path
is the preferred implementation when its explicit preflight is ready; the
validated Feature-18 v3 runtime is retained only as an internal compatibility
fallback while broader v10 coverage is still being established. The earlier v9
candidate remains historical static-audit evidence.

## Normal setup path

Normal onboarding now provisions the preferred v10 application runtime directly.
There is no separate v3 setup decision.

`setup.bat` asks one explicit question:

```text
Enable DLSS 5 now? [Y/N]
```

Choosing Yes runs:

```powershell
conda run -n dlss-rtxsr-upscaler python tools\provision_dlss5_v10.py
```

The provisioner uses the Runtime Manager manifest entry
`dlss5-neuroframe-v10-static-candidate`. It accepts only the exact pinned
Visual Enhancer v10.0 archive:

- size: `690203043` bytes
- SHA-256:
  `394BED6FBB3CCA1A994AE02A0A1152213D43030D6761437F86ABAA863C33D515`

The archive is downloaded from the recorded HTTPS upstream release only when a
verified local cache is absent. A user-supplied `NVE_DLSS5_ARCHIVE` must match
that same identity. The verified archive is retained at:

```text
runtime/downloads/Visual.Enhancer.v10.0.zip
```

Before the preferred runtime is staged, the project extracts only the manifest
allowlist into an isolated temporary directory, verifies the pinned runtime
identities and static ABI evidence, requires a clean Microsoft Defender custom
scan, verifies the identities again after the scan, and then atomically
activates the staged payload. The application-facing backend must report ready
before the provisioner reports success.

The local Defender preflight remains time-bounded. When it expires, the unified
DLSS 5 facade can refresh the scan from the already verified cached archive
without downloading the runtime again. **Configuration → DLSS 5 runtime →
Install / Repair DLSS 5** invokes the same managed provisioner for explicit
repair.

`NVE_SETUP_DLSS5=1` opts in without the interactive prompt and
`NVE_SETUP_DLSS5=0` skips DLSS 5. Setup failures remain fail-closed for DLSS 5
and do not prevent the other independently validated backends from being used.

The older v3 approval/firewall/self-test implementation is retained only for
existing/manual legacy installations and historical compatibility work. It is
not downloaded, prompted for, or required by normal setup.

## Legacy v3 compatibility scope

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

Visual Enhancer v10 is the normal implementation behind the single
user-facing **DLSS 5** mode. Setup provisions it only after the explicit DLSS 5
opt-in, using the same pinned archive/staging/Defender-preflight path exposed by
the Configuration repair action. Once ready, `DLSS5UnifiedBackend` selects v10
automatically. If its local preflight later expires, the cached verified archive
can be re-scanned locally; an already-provisioned v3 runtime may still serve as
an internal compatibility fallback when available.

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
