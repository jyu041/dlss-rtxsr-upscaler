# Phase 5F — SM86 Direct-Output Runtime Assessment

## Primary result

`DIRECT_OUTPUT_EXISTS_BUT_PRIVATE_RUNTIME`

The canonical `sdli1995/dlssg_for_sm86` revision exposes strong static evidence
of a standalone, caller-output-oriented native runtime, but the public
repository contains no native runtime source and the distributed `version.dll`
does not expose a complete external parameter-map ABI. The output mechanism is
therefore private to the binary’s own wrapper/host contract. It was not loaded
or executed.

## A. Repository

- URL: https://github.com/sdli1995/dlssg_for_sm86
- Local path: `C:\Users\<user>\Desktop\dlss-community-research\dlssg_for_sm86`
- HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Submodules: none materially present
- Source classification: `BINARY_ONLY_RUNTIME`
- Public contents: README files, INI/configuration, roadmap, notices, proxy
  DLLs, and alternate proxy entry points; no native C++ implementation source
  or standalone benchmark host source was present.

The README identifies the package as DLSSG Native 0.2.4, Windows x64/D3D12,
with an embedded native C++ wrapper, SM75/SM86 PTX/Cubin, model and inference
graph. It explicitly says it does not load or memory-map the original
frame-generation DLL, and that the caller owns queue submission,
synchronization, and presentation.

## B. Trust and static PE assessment

Analyzed file:

`C:\Users\<user>\Desktop\dlss-community-research\dlssg_for_sm86\version.dll`

- Size: `15,667,520` bytes
- SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Machine: `AMD64 / 0x8664`
- PE magic: PE32+
- PE timestamp: `0x6AA2613A` (`2026-09-10 19:50:18` UTC as decoded by dumpbin)
- Image base: `0x180000000`
- SizeOfImage: `0xF09000`
- Entry RVA: `0x47194`
- Sections: 9
- Authenticode: signature present, but PowerShell reports `UnknownError`
  because the signer chain terminates at an untrusted self-signed root
- Certificate subject/issuer: `CN=DLSSG Native Project (Self-signed)`
- Certificate thumbprint: `A994735E6A7E9AA31FA926B3023B7C487DAB4850`
- Defender: a Microsoft Defender custom scan was run over the canonical repo
  directory and returned without a detection. Defender status inspection was
  restricted by access policy, so this is not cryptographic or vendor-level
  proof of safety.
- TLS callbacks: none found in the TLS callback array
- PDB/debug path: no useful PDB path was exposed by static inspection

Sections:

| Section | RVA | Virtual size | Raw size | Characteristics |
|---|---:|---:|---:|---|
| `.text` | `0x1000` | `0x6F97C` | `0x6FA00` | executable/read |
| `.rdata` | `0x71000` | `0x22704` | `0x22800` | read-only |
| `.data` | `0x94000` | `0x1335C` | `0x1C00` | read/write |
| `.pdata` | `0xA8000` | `0x5274` | `0x5400` | read-only |
| `.detourc` | `0xAE000` | `0x21C0` | `0x2200` | read-only |
| `.detourd` | `0xB1000` | `0x18` | `0x200` | read/write |
| `.fptable` | `0xB2000` | `0x100` | `0x200` | read/write |
| `.rsrc` | `0xB3000` | `0xE53BF8` | `0xE53C00` | read-only |
| `.reloc` | `0xF07000` | `0x1084` | `0x1200` | discardable/read-only |

Imports are limited to `bcrypt.dll`, `dxgi.dll`, and `KERNEL32.dll`. The
KERNEL32 imports include normal proxy/hook primitives (`LoadLibrary*`,
`GetProcAddress`, `VirtualAlloc`, `VirtualProtect`, `VirtualQuery`) and thread
context APIs (`SuspendThread`, `GetThreadContext`, `SetThreadContext`) expected
from a system-DLL proxy/hook integration. No network DLL or network API,
PowerShell/cmd execution, service/task persistence, credential/browser paths,
or obvious process-injection API such as `CreateRemoteThread` or
`WriteProcessMemory` was found in the import table or targeted strings.

The static assessment is therefore `NO_OBVIOUS_MALWARE_INDICATORS`, with the
important limitation that the file is opaque, self-signed, and uses hook-like
behavior. The binary was not executed.

## C. ABI findings

The DLL exports 67 names. The relevant exposed NGX surface includes:

- `NVSDK_NGX_D3D12_Init` and `NVSDK_NGX_D3D12_Init_Ext`
- `NVSDK_NGX_D3D12_GetFeatureRequirements`
- `NVSDK_NGX_D3D12_CreateFeature`
- `NVSDK_NGX_D3D12_EvaluateFeature`
- `NVSDK_NGX_D3D12_ReleaseFeature`
- `NVSDK_NGX_D3D12_Shutdown` and `Shutdown1`
- `NVSDK_NGX_D3D12_PopulateDeviceParameters_Impl`
- `NVSDK_NGX_D3D12_PopulateParameters_Impl`
- standard NGX architecture/version helpers

The export table does not expose the parameter-map functions needed by a normal
external NGX host, including the D3D12 `AllocateParameters`,
`GetParameters`, `GetCapabilityParameters`, and `DestroyParameters` family.
The `NVSDK_NGX_*` export addresses also show several forwarding/stub aliases,
consistent with a proxy whose complete wrapper behavior is internal.

Static strings embedded in the binary do reveal the private contract vocabulary:

- `DLSSG.OutputInterpolated`
- `DLSSG.OutputReal`
- `DLSSG.OutputDisableInterpolation`
- `DLSSG.MultiFrameCount`
- `DLSSG.MultiFrameIndex`
- `DLSSG.Backbuffer`
- `DLSSG.Depth`
- `DLSSG.MVecs`
- `DLSSG.HUDLess`
- `DLSSG.Reset`
- `DLSSG.MvecScaleX` / `MvecScaleY`
- `DLSSG.ClipToPrevClip` / `PrevClipToClip`
- `DLSSG.CmdQueue`
- `DLSSG.MultiFrameCountMax`

These strings establish that the runtime has explicit output resources and
per-frame multi-frame indexing internally. They do not establish a callable
external ABI for constructing the parameter object or selecting the runtime’s
native wrapper path.

## D. Output ownership

Static classification: `DIRECT_OUTPUT_EXISTS_BUT_PRIVATE_RUNTIME`.

The README says the caller owns queue submission, synchronization, and
presentation, while the binary contains `OutputInterpolated` and
`OutputReal` parameter names. The most likely internal model is an explicit
caller-provided `ID3D12Resource*` for the interpolated output, with
`MultiFrameIndex` selecting the generated frame in a 2X/3X/4X group. However,
the public repository does not provide the native parameter construction code,
the exact resource flags/state contract, or a host that can invoke the private
wrapper without reverse-engineering it.

Expected output conceptually:

- resource type: D3D12 texture resource
- generated output key: `DLSSG.OutputInterpolated`
- real output key: `DLSSG.OutputReal`
- 2X generated count: 1
- generated index: `MultiFrameIndex=1`
- likely UAV-capable output, based on the existing public NGX helper contract

Format, exact state transitions, output-valid signaling, and ownership fences
remain private/unverified for this binary.

## E. Presentation requirement

The package documentation states that the caller owns presentation and that its
offline benchmark excludes rendering, Present, uploads, and readbacks. This is
strong evidence that the native inference path itself does not require a
Streamline presentation path or swapchain to produce its output.

- swapchain required for the inference ABI: likely NO
- Present required for inference: likely NO
- caller-owned output: strongly indicated, but not externally callable from
  the available public surface
- application-owned readback: architecturally indicated, not proven locally

This is distinct from the official Streamline path, where DLSS-G is tied to
Present and its generated image is pacer-owned.

## F. Host/build/probe

No new host was created and no build was performed. The gate for creating
`native\dlssg_sm86_offline\` was not satisfied because the runtime’s parameter
ABI is not externally reconstructible from public source/documentation and
exports alone.

- `--selftest`: not created/run
- `--probe-runtime`: not created/run
- runtime LoadLibrary: NO
- live `--run-2x`: NO
- attempts: 0
- retries: 0

This avoids executing an opaque proxy DLL whose signature is not trusted and
whose initialization/loader behavior is designed for installation beside a
game executable.

## G. GPU health

No GPU work occurred in Phase 5F. No `nvidia-smi` live experiment was run, no
provider was loaded, and no Windows GPU event window was needed.

- GPU: previously established RTX 3070 Ti
- driver: previously established 610.62
- Event 153: not applicable; no live attempt
- driver/system changes: none

## H. Decision

The shortest safe next choice is to decide whether an external dependency on
this vetted-but-opaque native runtime is acceptable. A large decompilation
effort is not justified by this phase. The two practical options are:

1. Treat the runtime as an explicitly pinned optional external backend and
   obtain a supported invocation contract from its author.
2. Request or locate a canonical standalone host/API source release that
   exposes the parameter construction and output-resource contract.

Next step: `DECIDE_EXTERNAL_RUNTIME_DEPENDENCY` (not executed).

## I. Git

- Primary repository HEAD: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Primary repository `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- No commit.
- No push.
