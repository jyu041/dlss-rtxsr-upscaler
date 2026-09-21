# Phase 4C readiness audit

Status: locally validated closure candidate; no publication approval requested.

## RTX VSR

The public application uses NVIDIA's `nvidia-vfx==0.1.0.1` package. The
installed binding reported SDK version `1.2.0`, exposes `VideoSuperRes`, and
exposes the tested `LOW`, `MEDIUM`, `HIGH`, `ULTRA`, `HIGHBITRATE_*`,
`DEBLUR_*`, and `DENOISE_*` quality values. The package includes proprietary
native NVIDIA VFX/NGX DLLs and NVIDIA license/third-party files; package
availability is not treated as redistribution permission.

Import and enum inspection is deliberately reported as `STATICALLY READY`,
not as a successful hardware validation. `src/core/rtx_vsr_readiness.py`
provides the explicit GPU check in a child process. It emits line-buffered
`HEARTBEAT` events and has a hard timeout so a native import, load, or run
cannot hang the WebUI or an orchestration process.

The earlier direct probe produced a valid finite `3x128x128` result but left
the Python process alive; the subsequent multi-mode probe stopped after its
first heartbeat. The process-isolated check and render lifecycle now pass,
subject to the explicit helper termination policy below.

### Phase 4C2 lifecycle evidence

The diagnostic-only matrix used a fresh child process and a 10-second hard
timeout per case. All cases reached import, construction, dimensions, load,
and CUDA input setup. Cases B, C, D, and E also completed their requested
native runs and immediate DLPack clones; case D completed 100 tiny runs.

| Case | Last marker before timeout | Output | Residual child |
| --- | --- | --- | --- |
| A: load/destroy | `M13 before close` | No | No |
| B: one run/clone/destroy | `M13 before close` | Yes | No |
| C: 10 persistent runs/destroy | `M13 before close` | Yes | No |
| D: 100 persistent runs/destroy | `M13 before close` | Yes | No |
| E: retain until exit | `M15 before interpreter shutdown` | Yes | No |
| F: explicit delete/GC | `M13 before explicit delete` | Yes | No |

The installed wrapper documents the same context-manager lifecycle used by
the project, implements `close()` through the native `destroy()` call, and
requires copying the DLPack result before the next call or close. The evidence
therefore classifies the blocker as **NVIDIA VFX / driver native teardown or
interpreter-shutdown lifecycle defect**, not a per-frame recreation, run, or
DLPack-lifetime defect. Persistent reuse improves bounded processing but does
not make teardown reliable. A production fix requires a dedicated helper
process with fail-closed frame transport and supervised termination; it must
not hide teardown in the WebUI process.

The Phase 4C3/4C4 helper completed ten independent 64x64-to-128x128 jobs with
finite output and `EXITED_AFTER_DONE`; per-job VRAM returned to approximately
854–859 MiB after 1058–1066 MiB peaks. The UI preview, H.264 and HEVC paths,
cancellation, recovery, and repeated-job checks passed. H.264 completed 120
frames at 3840x2160 with AAC preserved; HEVC completed 29 frames at the same
dimensions. No matching driver events were found in the four-hour audit.

## Standalone DLSS SR

The public tree contains a real persistent-host stream pipeline in
`src/video/dlss_sr.py`, including temporal guide/reset handling, bounded
packet parsing, encoding, audio muxing, and cancellation. The adapter's old
messages claiming that video processing was not implemented were stale and
now point to those pipeline entry points.

The public source still contains no committed `dlss_sr_host.exe` or
`nvngx_dlss.dll`; the private resource repository remains unchanged. An
ignored local Release host and runtime staging area now exist for validation.

The host, official runtime, self-test, and short pipeline checks now pass.

### Recovered provenance

The historical SDK tree exists at
`C:\Users\<user>\AppData\Local\Temp\dlssg-phase3-research\DLSS`, with Git
HEAD `374959484e79a640feaba44c93ac8cfb0a03f5b5` and the recorded
`LICENSE.txt` SHA-256
`3027F23CA5A46DD9CB8183FBD522983A86F64D7DAAC5982912BF9F214671F294`.
It includes the Windows x64 NGX import libraries and official development and
release `nvngx_dlss.dll` files. Their hashes are respectively
`378262F4BA429E6199CE25D6F9275734F354C3B017F3F096D8CEA1AF468312FF` and
`3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`.
Both are NVIDIA-signed version `310.9.1.0`; neither matched the then-staged
historical `C85F` identity, which has since been retired. The current validated
official REL runtime identity is
`3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`.
Hash equality alone is not accepted as production provenance.

The host was built successfully with Visual Studio Build Tools 17.14.40/MSVC
19.44.35228, CMake 4.4.3, and Ninja 1.13.0. Its SHA-256 is
`E23F3CD5BEB5E70001E9950C890027D46F84CEB4439A09CEA67E343AB34A34BB`.
Both official SDK `dev` and `rel` runtimes passed bounded native Quality
self-test. The `rel` candidate passed 2-second H.264 and HEVC pipelines, each
120 frames at 2880x1620 with AAC preserved and ffprobe-valid output. Standalone
DLSS SR no longer imports DLSS 5 code for its temporal guide.

### Engineering distribution classification

Using the exact recovered NVIDIA RTX SDKs License v. March 14, 2024:

| Component | Classification | Evidence/condition |
| --- | --- | --- |
| `dlss_sr_host.exe` | **A — REDISTRIBUTION SUPPORTED IN APPLICATION PACKAGE** | Project application output incorporating the SDK; the license grants distribution of SDK software/material in object-code application form. |
| NVIDIA SDK library material statically incorporated into the host | **A — REDISTRIBUTION SUPPORTED IN APPLICATION PACKAGE** | Same object-code application grant; host provides material additional functionality. |
| Official SDK `lib/Windows_x86_64/rel/nvngx_dlss.dll` | **A — REDISTRIBUTION SUPPORTED IN APPLICATION PACKAGE** | It is an SDK runtime material in the exact matched snapshot, not a stand-alone SDK distribution; include NVIDIA notices/terms and preserve NVIDIA rights. |
| Additional NVIDIA runtime DLLs | **A — NONE REQUIRED BY THIS HOST BEYOND `nvngx_dlss.dll`** | PE imports are Windows D3D12/DXGI/system libraries; native self-test succeeded with only the selected NGX DLL staged beside the host. |

This classification is conditional on packaging the host as part of the
application, including required notices/attribution, not relicensing NVIDIA
material as MIT, preserving downstream protections, and complying with the
commercial-release notification and NVIDIA mark requirements in the license.
The old `C85F...` hash is historical and retired; it is not accepted for this package.

## Current gate

The local evidence supports `RTX VSR TURNKEY BETA READY` and `DLSS SR
TURNKEY BETA READY` for the exercised RTX 3070 Ti / Windows 10 / driver 610.62
environment. Overall: `READY FOR BETA.2 PACKAGING`. This is a local closure
candidate only; no source push, tag, release, or package publication is part
of this milestone.
