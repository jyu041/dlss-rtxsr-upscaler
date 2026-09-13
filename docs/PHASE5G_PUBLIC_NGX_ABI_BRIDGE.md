# Phase 5G — Public NGX ABI Compatibility

## Primary result

`PUBLIC_NGX_ABI_WITH_THIN_ADAPTER`

The pinned SM86 runtime has exported D3D12 Create/Evaluate/Release entry points
whose x64 argument handling matches the public NVIDIA NGX signatures. Static
disassembly also shows the runtime consuming a caller-supplied parameter object
through the standard C++ virtual interface. However, the runtime does not
export parameter allocation/access functions, and the required official
parameter-object interoperability probe was not completed. No community DLL
was loaded or executed and no GPU Evaluate was attempted.

## A. Baselines and artifacts

- Primary repository HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community repository: `C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Runtime: `version.dll`
- Runtime SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- Runtime execution: **NO**
- Community GPU attempt: **NO**

## B. NVIDIA public ABI

Local NVIDIA DLSS SDK header snapshot:

- Header tree: `C:\Users\mark\AppData\Local\Temp\dlssg-phase3-research\DLSS`
- Header commit: `374959484e79a640feaba44c93ac8cfb0a03f5b5`

`NVSDK_NGX_Parameter` is a C++ abstract interface with virtual overloads for
unsigned long long, float, double, unsigned int, int, D3D11 resource, D3D12
resource, and void-pointer Set methods; matching Get overloads; and Reset.
Therefore a consumer does not need the DLL to export setter/getter wrapper
functions when it receives a valid object from official NGX.

The public D3D12 signatures in `nvsdk_ngx.h` are:

```text
CreateFeature(ID3D12GraphicsCommandList*, NVSDK_NGX_Feature,
              const NVSDK_NGX_Parameter*, NVSDK_NGX_Handle**)
EvaluateFeature(ID3D12GraphicsCommandList*, const NVSDK_NGX_Handle*,
                const NVSDK_NGX_Parameter*, PFN_NVSDK_NGX_ProgressCallback)
ReleaseFeature(const NVSDK_NGX_Handle*)
```

The official DLSS-G helper sets
`NVSDK_NGX_DLSSG_Parameter_OutputInterpolated` (the string
`DLSSG.OutputInterpolated`) to the caller-owned `ID3D12Resource*`, together
with Backbuffer, MotionVectors, Depth, MultiFrameCount, MultiFrameIndex, and
the documented camera/reset fields.

## C. Community export map

`dumpbin /exports` on the pinned runtime reported:

| Export | RVA | Public-name match |
|---|---:|---|
| `NVSDK_NGX_D3D12_CreateFeature` | `0x205D0` | exact |
| `NVSDK_NGX_D3D12_EvaluateFeature` | `0x20630` | exact |
| `NVSDK_NGX_D3D12_GetFeatureRequirements` | `0x20690` | exact |
| `NVSDK_NGX_D3D12_GetScratchBufferSize` | `0x206F0` | exact |
| `NVSDK_NGX_D3D12_Init` | `0x20710` | exact |
| `NVSDK_NGX_D3D12_Init_Ext` | `0x20710` | exact alias |
| `NVSDK_NGX_D3D12_PopulateDeviceParameters_Impl` | `0x20740` | implementation helper |
| `NVSDK_NGX_D3D12_PopulateParameters_Impl` | `0x20780` | implementation helper |
| `NVSDK_NGX_D3D12_ReleaseFeature` | `0x207B0` | exact |
| `NVSDK_NGX_D3D12_Shutdown` | `0x207F0` | exact |
| `NVSDK_NGX_D3D12_Shutdown1` | `0x20820` | exact |

The runtime does **not** export `D3D12_GetParameters`,
`D3D12_GetCapabilityParameters`, `D3D12_AllocateParameters`, or
`D3D12_DestroyParameters`. Those must come from official NGX if the runtime
accepts the public object model.

## D. Static ABI evidence

At `version.dll` RVA `0x205D0`, CreateFeature preserves the first four x64
argument registers as command list, feature, parameter object, and output
handle, checks the parameter and output pointers, and dispatches internally.
At RVA `0x20630`, EvaluateFeature preserves command list, handle, and parameter
object in the corresponding positions and dispatches internally.

The runtime’s internal call sites dereference the supplied parameter object and
invoke vtable slots consistent with the public interface. For example, calls
through `[vtable+0x18]` occur with a parameter name and a 32-bit value, matching
the public `Set(const char*, unsigned int)` slot; other call sites use the
resource and pointer slots. This is strong evidence for a thin adapter rather
than a completely private parameter representation, but it is not a runtime
proof of every required key, ownership rule, or lifetime rule.

The x64 ABI uses the Microsoft register calling convention; no separate x86
calling-convention issue was found. Exact runtime behavior for feature ID 11
(Frame Generation), handle ownership, and GPU-side resource validation remains
untested.

## E. Parameter-object provenance and probe status

The official headers and existing project source provide the correct route:

```text
official NVSDK_NGX_D3D12_Init
 -> official NVSDK_NGX_D3D12_GetCapabilityParameters
 -> official NVSDK_NGX_Parameter*
 -> public Set/Get/Reset virtual interface
```

The existing capability probe source uses this official route and destroys the
returned object with official NGX. It currently hard-codes an exact
`NVIDIA GeForce RTX 3070` match, while this machine’s required target is the
RTX 3070 Ti. It was therefore not used as evidence for this phase’s required
3070 Ti parameter probe, and no new probe executable was created.

Results:

- official parameter allocation on the target RTX 3070 Ti: **NOT RUN**
- scalar Set/Get round-trip: **NOT RUN**
- resource-pointer Set/Get round-trip: **NOT RUN**
- Reset: **NOT RUN**
- parameter pointer/vtable provenance: statically established from official
  headers, runtime pointer unavailable without the probe

Because that gate did not pass, the community runtime was not loaded.

## F. Output contract

The official helper defines `DLSSG.OutputInterpolated` as a caller-supplied
D3D12 resource pointer. The community binary contains the same output key plus
`OutputReal`, `OutputDisableInterpolation`, `MultiFrameCount`, and
`MultiFrameIndex`. This supports the direct-output hypothesis and is
compatible in shape with the public helper contract.

Still unverified for this binary:

- required output format and flags;
- exact resource state at Evaluate;
- fence/queue ownership;
- whether the community implementation writes the caller resource;
- handle and parameter lifetime behavior.

## G. Runtime and D3D12 results

- community runtime LoadLibrary: **NO**
- community initialization: **NOT RUN**
- CreateFeature: **NOT RUN**
- reset Evaluate: **NOT RUN**
- measured Evaluate: **NOT RUN**
- caller-owned output resource: **NOT CREATED**
- swapchain: **NO**
- Present: **NO**
- readback: **NO**

No standalone host was created because the official parameter-object gate was
not completed. No source or runtime files were changed in the community
workspace.

## H. Safety and GPU health

The Phase 5F runtime SHA is unchanged. No community binary was loaded, no
provider was modified, and no GPU work occurred in Phase 5G. Consequently no
new `nvidia-smi` or Windows GPU event window was generated for this phase, and
Event 153 is **not applicable**.

## I. Decision and next step

The static result is `PUBLIC_NGX_ABI_WITH_THIN_ADAPTER`, not
`EXACT_PUBLIC_NGX_ABI`: the exported Create/Evaluate surface and standard
parameter-object consumption are plausible, but allocation must be supplied by
official NGX and target-adapter Set/Get/Reset interoperability remains to be
demonstrated.

Next step: `COMPLETE_OFFLINE_2X_PROOF`.

## J. Git

- No commit.
- No push.
