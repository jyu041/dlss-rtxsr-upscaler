# Phase 5A — Official Streamline Sample

## Primary classification

`PROCESS_CRASHED`

The official Streamline sample built successfully from NVIDIA source and the
stock baseline ran to its bounded frame limit. The single donor-enabled run
crashed before producing a ReShade or donor log, so donor initialization and
DLSS-G activation were not demonstrated. No retry or alternate DLL arrangement
was attempted.

## Source baselines

- Official Streamline: `https://github.com/NVIDIA-RTX/Streamline`
  - HEAD/tag: `2122257e0fce486f91b385aa63b9a09b0a34b363` (`v2.14.1`)
- Official Streamline_Sample: `https://github.com/NVIDIA-RTX/Streamline_Sample`
  - HEAD: `0bb8bf3ee80ce8d6b53688c2e237ac0981ce2f6c`
- Official ReShade: `https://github.com/crosire/reshade`
  - HEAD: `eeb2c76aea8e00200d88b479c9036c5ea4d06d5e`
- Donor: `MFGAmpereUnlock-RenoDx`
  - HEAD: `c88b208e3f8f12e86a261f06aef1da3a77adef27`

The Streamline and sample checkouts have no additional material git submodule
commits. ReShade submodules were initialized at:

```text
d3d12 9e393d6d8a3b30dcc6f2806ef604ec16a27b0d7e
fpng 925796543b9d26b8edfcdcecd94c1dac280f29fc
glad 27bed1181560211b55e39a9b132fef8c5846aae5
imgui 3912b3d9a9c1b3f17431aebafd86d2f40ee6e59c
jxl_simple_lossless 8dc970fc771e35239db55dfbce8f46f83f8e9b73
minhook 8fda4f5481fed5797dc2651cd91e238e9b3928c6
openxr 288d3a7ebc1ad959f62d51da75baa3d27438c499
spirv 7845730cab6ebbdeb621e7349b7dc1a59c3377be
stb 28d546d5eb77d4585506a20480f4de2e706dff4c
utfcpp 819011bb01628fe1aa2f1da9f2c842a48fd5680b
vma 1076b348abd17859a116f4b111c43d58a588a086
```

## Source verification

The sample enables `STREAMLINE_FEATURE_DLSS_FG` in its root `CMakeLists.txt`.
The relevant host implementation is in:

- `src/SLWrapper.cpp`: `slInit`, resource tagging, `slDLSSGSetOptions`,
  `slDLSSGGetState`, and frame constants.
- `src/StreamlineSample.cpp`: startup option parsing, DLSS-G mode and generated
  frame count selection, Reflex callbacks, and per-frame state handling.
- `src/DeviceManagerOverride/DeviceManagerOverride_DX12.cpp`: D3D12 swapchain
  recreation and DLSS-G lifecycle integration.
- `src/NVWrapper.cpp`/`src/NVWrapper.h`: NGX/DLSS-G capability and Reflex
  queries.

The sample tags motion vectors, depth, final color, HUD-less color, scaling
resources, and UI resources. It uses the D3D12 path, Streamline interposer,
DLSS-G plugin, and Reflex/PCL integration.

NVIDIA’s source README explicitly states that `sl.dlss_g.dll` and its
`nvngx_dlssg.dll` runtime are binary-only. They were obtained only from the
official NVIDIA Streamline v2.14.1 release asset; no community prebuilt binary
was used.

## System

- GPU: NVIDIA GeForce RTX 3070 Ti
- Driver: `610.62`
- HAGS: `UNKNOWN` — `HwSchMode` was not present in the checked registry key;
  it was not changed.

Before the donor-enabled run, `nvidia-smi` reported 36 C, P8, 607 MiB / 8192
MiB, and 0% GPU utilization.

## Builds

### Streamline sample

Configured and built externally with:

```text
cmake -S Streamline_Sample -B _build -G "Visual Studio 17 2022" -A x64
  -DUSE_SL=ON
  -DSTREAMLINE_FEATURE_DLSS_FG=ON
  -DDONUT_WITH_VULKAN=OFF
  -DDONUT_WITH_DX11=OFF
```

Built with MSBuild 17.14.51, MSVC 19.44.35228, Windows SDK 10.0.26100. The
Release executable is:

`C:\Users\<user>\Desktop\dlss-community-research\Streamline_Sample\_bin\StreamlineSample.exe`

The build passed. CMake emitted only upstream deprecation and custom-command
policy warnings.

### ReShade host

The official CMake route initially lacked generated resources. ReShade’s own
`tools/update_version.ps1` was run, then its official `ReShade.sln` target was
built as `Release|64-bit`. Output:

`C:\Users\<user>\Desktop\dlss-community-research\ReShade\bin\x64\Release\ReShade64.dll`

The build passed with upstream shader/compiler warnings, including HLSL `pow`
warnings and C4530 exception-unwind warnings.

### Donor

The already source-built donor artifact was used:

`C:\Users\<user>\Desktop\dlss-community-research\renodx\build.vs\Release\renodx-mfgunlock.addon64`

SHA-256: `0FE9798C0F48AD7ADBC0E22546743221EB6397BDEAE804E438297EA133611F81`

It was not rebuilt or modified in the primary repository.

## Matched runtime stack

The official `streamline-sdk-v2.14.1.zip` was copied into the external sample
SDK directory. Relevant runtime identities in the sample output directory:

```text
sl.interposer.dll  2.14.1.0  8C87C9499461DA561EDD529AA9BF7831D67D7B94EBB1C1A5ED54EF4934E1EA4C
sl.common.dll      2.14.1.0  82924A8954DD671E09351C5DE0EB87AD0EB25B944CC9F9AB955CA1D9950DE15D
sl.dlss_g.dll      2.14.1.0  F4A6B2B14DCC0B1485989E430D3B4E3A44AC1800B92BA1AD74F476E64FB2B09C
sl.reflex.dll      2.14.1.0  0CE9725E3E03EA9E7F81D008B57F33EE365973D2E349131C8B1C3E3378FE2DB0
sl.pcl.dll         2.14.1.0  F13D51CFA05F4CD514DF2026049E2DB8ADF359221713170AD386FD499915B582
nvngx_dlssg.dll    310.9.1.0 FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82
```

The sample’s configured stack used the official release provider, not the
earlier DriverStore `310.2.1.0` provider. No attempt was made to replace it.

## Stock sample baseline

Command:

```text
StreamlineSample.exe -d3d12 -maxFrames 100 -sllog -logToFile -width 256 -height 256
```

The baseline created D3D12, loaded Streamline and the official DLSS-G plugin,
rendered the bounded sample workload, and exited normally. The Streamline log
reported native architecture `0x170` and `FeatureSupported == AdapterUnsupported`;
DLSS-G was disabled as expected on stock Ampere. Reflex and PCL were supported.

## Donor-enabled attempt

An isolated external directory was used:

`C:\Users\<user>\Desktop\dlss-community-research\phase5a_streamline_run`

It contained the source-built ReShade runtime as `dxgi.dll`, the source-built
`renodx-mfgunlock.addon64`, the built sample, and the official matched runtime.
The single command was:

```text
StreamlineSample.exe -d3d12 -maxFrames 100 -sllog -logToFile -width 256 -height 256 -DLSSG_on -DLSSG_numFrameToGenerate 1 -Reflex_mode 1
```

The process produced empty `ReShade.log` and `log.txt` files, emitted no donor
diagnostics, left no running process, and generated a Windows Application Error:

```text
Faulting application: StreamlineSample.exe
Exception: 0xc0000005
Fault offset: 0x000000000005bd45
```

Because the donor did not initialize, there is no valid architecture/provider,
`slDLSSGGetState`, `slDLSSGSetOptions`, generation-count, or presentation
evidence. The failure layer is classified as `PROCESS_CRASHED` at the
sample/ReShade loading boundary, before donor observability.

After the run, `nvidia-smi` remained responsive and reported 36 C, P8, 607 MiB /
8192 MiB, and 0% GPU utilization. No new `nvlddmkm`, Display, WHEA, or Event
153 was observed in the checked window. New `nvlddmkm` Event 153: **NO**.

## Next step

`FIX_KNOWN_GOOD_HOST_FIRST` — diagnose the source-built ReShade loading
boundary offline before another sample run. Do not change provider versions or
attempt 3X/4X.

## Git

- Primary repository: no commit
- Primary repository: no push
