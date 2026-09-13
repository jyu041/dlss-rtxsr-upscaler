# DLSS-G MFG capability investigation

## Result classification

* `DLSSG_CAPABILITY_POPULATION_FIXED`
* `DLSSG_COMMUNITY_INI_LOADED`
* `DLSSG_3X_MFG_NOT_WORKING`
* `DLSSG_4X_MFG_NOT_TESTED`
* `DIRECT_HOST_SKIPPED_COMMUNITY_MFG_CAPABILITY_POPULATION` does **not** apply:
  the corrected worker now calls both community population exports.

The capability-advertisement defect is fixed, but the RTX 3070 Ti direct host
still receives a disabled MFG output for 3X.  This task therefore does not
claim `DLSSG_3X_MFG_WORKING` and does not attempt 4X.

## A. Original failure

The original v4 worker hardcoded `maximumGeneratedFrames=3` in `CreateResponse`
and never populated the official parameter object from the community provider.
The first 3X attempt reached a successful Evaluate (`0x00000001`) but read
`OUTPUT_DISABLE_INTERPOLATION=1`, returned as native status `-9`, with no device
removal or driver reset.

## B. Parameter provenance and ABI

`NVSDK_NGX_D3D12_GetCapabilityParameters` allocates the object used by the
worker.  It is therefore an official NVIDIA NGX parameter object.  The
community DLL is loaded afterward and supplies the feature Init/Create/Evaluate
entry points.

The pinned community DLL exports the two internal population entry points.  Its
x64 export stubs establish these call shapes:

```text
NVSDK_NGX_Result PopulateDeviceParameters(ID3D12Device*, NVSDK_NGX_Parameter*)
NVSDK_NGX_Result PopulateParameters(NVSDK_NGX_Parameter*)
```

The worker now resolves and invokes those exact D3D12 exports after community
Init, with typed function pointers.  It logs the result and every capability
stage.  The public SDK header confirms that MFG count is `1=2X`, `2=3X`, and
`3=4X`, with a 1-based `MultiFrameIndex`.

## C. Capability by stage

Observed on NVIDIA GeForce RTX 3070 Ti, driver 610.62:

| Stage | FrameGeneration.Available | MultiFrameCountMax | FeatureInitResult |
| --- | ---: | ---: | ---: |
| Official GetCapabilityParameters | 0 | missing, result `0xBAD00010` | `0xBAD0000B` |
| After community DLL load, before Init | 0 | missing, result `0xBAD00010` | `0xBAD0000B` |
| After community Init | 0 | missing, result `0xBAD00010` | `0xBAD0000B` |
| After community PopulateDeviceParameters | 0 | **3**, result `0x1` | `0xBAD0000B` |
| After community PopulateParameters | 0 | **3**, result `0x1` | `0xBAD0000B` |
| After evidence-based direct availability enable | **1**, result `0x1` | **3**, result `0x1` | `0xBAD0000B` |

The worker now advertises the discovered maximum, falling back to 1 if the
community capability query is missing/invalid.  It rejects a CREATE request
above that actual ceiling instead of accepting a host hardcoded value.

The separate availability enable is based on the local MFG provider’s own
capability policy: it preserves an explicit `FeatureInitResult=0xBAD0000B`
(`FeatureNotSupported`) while promoting `FrameGeneration.Available` only after
both community population calls succeed and a valid generated-frame maximum is
present.  This is not a blind `MultiFrameCountMax` override.

## D. Community configuration and proof of load

The exact runtime path was:

```text
C:\Users\mark\Desktop\dlss-community-research\dlssg_for_sm86\version.dll
```

The adjacent `dlssg_sm86.ini` was restored to its original `Logging.Level=1`
after temporary diagnostics and contains:

```ini
Router=SM86
KernelImage=PTX
MaxGeneratedFrames=3
```

The verbose runtime record was written to
`dlssg_sm86\logs\native_35556.jsonl` and reported:

```text
router=86
kernel_image=ptx
max_generated=3
runtime=native_pipeline
feature_created actual_sm=86
```

It also recorded `presentation=caller_owned` for the reset Evaluate.  The
runtime did not emit a separate disable-reason field for the subsequent host
readback.

## E. Correction

The native worker now:

1. queries and logs official capability state;
2. resolves both community population exports;
3. invokes device then parameter population on the official parameter object;
4. enables the community-backed availability state only after successful
   population and verifies it;
5. derives `CreateResponse.maximumGeneratedFrames` from the observed ceiling;
6. logs requested count/index, raw disable value, capability maximum, Evaluate
   result, and device-removed reason on disabled output;
7. commits history only after a valid generated group, while reset frames still
   commit bootstrap state.

The request trace for 3X is now explicit: `count=2`, `index=1`, result `0x1`.
The host never reached a valid `index=2` output because index 1 was disabled.

## F. 3X result

After the capability correction, the bounded 256x256 deterministic synthetic
test was run with both internal NVOF and external deterministic motion.  The
external-motion isolation was important: it reproduced the same result and
removed NVOF as the cause.

Observed corrected 3X state:

```text
capabilityMax=3
FrameGeneration.Available=1
MultiFrameCount=2
MultiFrameIndex=1
Evaluate=0x00000001
OUTPUT_DISABLE_INTERPOLATION=1
deviceRemoved=0x00000000
```

The 2X comparison on the same host remains valid and produces non-stale
outputs.  The 3X failure is therefore no longer explained by the missing
community capability population.  The remaining failure lies in the
runtime’s direct caller-owned MFG evaluation contract; the installed runtime
does not expose a more specific disable reason in its JSONL output.  In
particular, it cannot currently be attributed to NVOF, missing INI support, a
missing maximum, or a failed Evaluate call.

## G. 4X result

Not tested.  The required gate was not satisfied because corrected 3X did not
produce a valid generated frame.  No 4X claim is made.

## H. GPU health

Before and after the corrected tests:

```text
GPU: NVIDIA GeForce RTX 3070 Ti
Driver: 610.62
```

The checked narrow Windows event intervals contained no new `nvlddmkm`,
Display, WHEA, Event 153, Application Error, or WER entry.  There were no
HAGS, TDR, driver, overclock, or GPU-reset changes.

## I. Tests

* Native x64 Release `/O2 /W4`: PASS; existing warnings remain.
* Native protocol self-test: PASS.
* NVOF direction test: PASS, object median approximately `(-8.125, -0.094)`.
* Zero-create capability probe: PASS; community max changed from missing to 3.
* 2X persistent regression: PASS.
* Corrected 3X: capability state PASS, generated output FAIL (`disable=1`).
* Full Python suite before this investigation: 82 passed, 2 skipped.

## J. Git

The investigation started from public `7526b3883046aca9dd776942e247641472758060`
and private resource `4eeeb0a1a1a492b56448780e9447008a9b971bd3`.  The final
capability-fix commits are public `d4d10ca` and private resource `5b81c90`.
The external community DLL and NVIDIA runtime remain untracked and are not
added to either repository.
