# Phase 5B — Embedded donor in NVIDIA Streamline Sample

## Result

`DLSSG_ACTIVATION_FAILED`

The official Streamline sample was built in the isolated external working copy
`C:\Users\mark\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere`.
ReShade was not used. The one donor-enabled run completed normally, but the
sample kept its DLSS-G mode off because the sample's separate `-DLSSG_on`
scripting switch was not supplied. No generated-frame success is claimed and no
retry was made.

## Source baselines

- Streamline: `2122257e0fce486f91b385aa63b9a09b0a34b363` (`v2.14.1`)
- Streamline_Sample: `0bb8bf3ee80ce8d6b53688c2e237ac0981ce2f6c`
- donor: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- ReShade: not used

The requested nested path `Streamline\_Sample` did not exist; the verified
official checkout was the sibling `Streamline_Sample` directory. The original
checkout was not edited; all sample changes were made in the separate copy.

## Embedded donor

Copied/adapted donor core files into `src/mfg_ampere/`:

- `architecture.hpp`
- `capability_policy.hpp`
- `fatbin.hpp`
- `ptx_retarget.hpp`
- `provider.hpp`
- `ngx_hook.hpp`
- `ngx_bridge.hpp`
- `loadhook.hpp`
- `framecount.hpp`

Added `mfg_ampere.cpp/.hpp` and a flushed stderr logging adapter. ReShade
registration, UI, ImGui, and addon entrypoint code were excluded. The donor MIT
license and commit attribution are retained in the embedded source header.

Initialization occurs before the sample's `SLWrapper::Initialize_preDevice`,
installing donor loader/interposer/NGX hooks before Streamline loads the matched
plugins. Donor Detours source (`detours.cpp`, `disasm.cpp`, `modules.cpp`) is
compiled into the sample.

## Build and regression

Toolchain: VS Build Tools 17.14.40, MSVC 19.44.35228, MSBuild 17.14.51, Windows
SDK 10.0.26100.0, CMake 3.31.6. Build: x64 Release, D3D12, Streamline/DLSS-G
enabled, single-threaded MSBuild. Build passed and produced
`StreamlineSample.exe` in the isolated `_bin` directory.

The donor-disabled regression started, created D3D12, loaded Streamline,
rendered, and exited 0. Native DLSS-G remained unsupported on the RTX 3070 Ti.

## Matched runtime

- `sl.interposer.dll` 2.14.1.0 — `8C87C9499461DA561EDD529AA9BF7831D67D7B94EBB1C1A5ED54EF4934E1EA4C`
- `sl.common.dll` 2.14.1.0 — `82924A8954DD671E09351C5DE0EB87AD0EB25B944CC9F9AB955CA1D9950DE15D`
- `sl.dlss_g.dll` 2.14.1.0 — `F4A6B2B14DCC0B1485989E430D3B4E3A44AC1800B92BA1AD74F476E64FB2B09C`
- `sl.reflex.dll` 2.14.1.0 — `0CE9725E3E03EA9E7F81D008B57F33EE365973D2E349131C8B1C3E3378FE2DB0`
- `sl.pcl.dll` 2.14.1.0 — `F13D51CFA05F4CD514DF2026049E2DB8ADF359221713170AD386FD499915B582`
- `nvngx_dlssg.dll` 310.9.1.0 — `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82`

## Donor-enabled run

Command executed once, directly:

```text
StreamlineSample.exe -d3d12 -maxFrames 100 -sllog -logToFile -width 256 -height 256 -adapter 0 -mfg-ampere
```

Observed donor trace:

```text
MFG_EMBED_INIT
installed 3 hook(s) in kernel32.dll
installed 1 hook(s) in sl.interposer.dll
installed 1 hook(s) in sl.interposer.dll
installed 9 hook(s) in NGX
provider prepared: sm_89 -> sm_86, 70 fatbins, 31 cubins hidden
NGX frame-generation requirements adjusted
NVSDK_NGX_D3D12_GetCapabilityParameters: 1
slDLSSGGetState hook installed
slDLSSGSetOptions hook installed
MFG_EMBED_SHUTDOWN
EXIT_CODE=0
```

Streamline then loaded `sl.dlss_g` 2.14.1 and reported:

```text
Host SDK version: 2.14.1, platform: D3D12
Multi-frame not supported, max generated frames 1 (SL Plugin supports 5, NGX feature supports 1)
DLSS-G is supported on this system
```

The sample log also records the plugin as disabled and has no donor
Create/Evaluate success observation. This is the first failing layer:
sample-side DLSS-G activation/presentation, not provider preparation or donor
loading. No retry was performed.

## System health

Before: RTX 3070 Ti, driver 610.62, 8192 MiB VRAM, 669 MiB used, 36 C, 0%.

After: RTX 3070 Ti, driver 610.62, 8192 MiB VRAM, 674 MiB used, 44 C, 0%.

No relevant new `nvlddmkm`, Display, WHEA, Application Error, or WER event was
observed. Event 153: NO. HAGS registry value was absent; interpreted as
UNKNOWN. No registry, driver, provider, HAGS, TDR, or hardware settings were
changed.

## Next step

`FIX_EMBEDDED_HOST_AT_EXACT_FAILURE`: use the sample's documented
`-DLSSG_on`/generated-frame scripting path in a future run, with a new explicit
one-attempt authorization. Do not execute that next step in this phase.

## Git

No commit. No push. Primary repository Phase 3/4 work was preserved.
