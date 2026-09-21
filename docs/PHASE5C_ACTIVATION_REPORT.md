# Phase 5C — Embedded Streamline DLSS-G 2X Activation

## Result

`KNOWN_GOOD_AMPERE_2X_WORKING`

One donor-enabled run was performed. It exited normally with code `0`; no
retry or alternate runtime was used.

## Exact command

```text
C:\Users\<user>\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin\StreamlineSample.exe -d3d12 -maxFrames 200 -sllog -logToFile -width 256 -height 256 -adapter 0 -mfg-ampere -DLSSG_on -DLSSG_numFrameToGenerate 1
```

The source parser at `src/StreamlineSample.h` confirms that `-DLSSG_on` is a
flag with no value and that `-DLSSG_numFrameToGenerate` consumes the following
integer. The requested mode was ON with one generated frame, i.e. 2X.

## Source and binaries

- Streamline: `2122257e0fce486f91b385aa63b9a09b0a34b363` (v2.14.1)
- Streamline_Sample base: `0bb8bf3ee80ce8d6b53688c2e237ac0981ce2f6c`
- Embedded donor: `c88b208e3f8f12e86a261f06aef1da3a77adef27`
- Executable: `StreamlineSample.exe`, SHA-256
  `440F7A14166C61EBED19A30F96A354BE2726D7CB6E70B013183B9FF5B2AC6B0F`
- ReShade: not used

Matched Streamline runtime hashes:

| File | Version | SHA-256 |
|---|---:|---|
| `sl.interposer.dll` | 2.14.1.0 | `8C87C9499461DA561EDD529AA9BF7831D67D7B94EBB1C1A5ED54EF4934E1EA4C` |
| `sl.common.dll` | 2.14.1.0 | `82924A8954DD671E09351C5DE0EB87AD0EB25B944CC9F9AB955CA1D9950DE15D` |
| `sl.dlss_g.dll` | 2.14.1.0 | `F4A6B2B14DCC0B1485989E430D3B4E3A44AC1800B92BA1AD74F476E64FB2B09C` |
| `sl.reflex.dll` | 2.14.1.0 | `0CE9725E3E03EA9E7F81D008B57F33EE365973D2E349131C8B1C3E3378FE2DB0` |
| `sl.pcl.dll` | 2.14.1.0 | `F13D51CFA05F4CD514DF2026049E2DB8ADF359221713170AD386FD499915B582` |
| `nvngx_dlssg.dll` | 310.9.1 | `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82` |

## Donor evidence

The embedded donor logged to immediate stderr:

```text
MFG_EMBED_INIT
installed 3 hook(s) in kernel32.dll
installed 1 hook(s) in sl.interposer.dll
installed 1 hook(s) in sl.interposer.dll
installed 9 hook(s) in NGX
provider prepared: sm_89 -> sm_86, 70 fatbins, 31 cubins hidden
NGX frame-generation requirements adjusted
NVSDK_NGX_D3D12_GetCapabilityParameters: 1
slDLSSGGetState hook installed.
slDLSSGSetOptions hook installed.
DLSS-G feature created
DLSS-G active
MFG_EMBED_SHUTDOWN
EXIT_CODE=0
```

Thus the observed donor profile was Ampere, native architecture `0x170`,
exposed architecture `0x190`, target SM `86`; provider preparation qualified
one matched provider, with 70 PTX/fatbin retargets and 31 incompatible cubins
hidden. Requirements were relaxed and the capability bridge was active.

## Streamline state and execution

The Streamline log reported:

```text
DLSS-G is supported on this system
Reflex is supported on this system
Multi-frame not supported, max generated frames 1 (SL Plugin supports 5, NGX feature supports 1)
DLSS-G interpolation state changed from disabled to enabled (mode=sl::DLSSGMode::eOn, numFramesToGenerate=1, SyncInterval=0)
slFreeResources Releasing DLSS-G instance
```

Reflex availability was YES. The sample’s existing scripted path handled the
Reflex prerequisite; no Reflex implementation was changed.

`slDLSSGGetState` and `slDLSSGSetOptions` were observed by the donor hooks and
Streamline emitted no failure result, but this sample build does not print the
raw numeric return values. The effective state was enabled with a maximum of
one generated frame. Donor instrumentation observed feature creation and
active Evaluate/generation activity. The exact application-rendered versus
presented-frame counters and a generated-frame readback are not instrumented by
the sample, so no fabricated 2N counter is reported.

## Run and GPU health

- Requested bound: 200 frames
- Process exit code: 0
- Attempts: 1
- Retries: 0
- GPU: NVIDIA GeForce RTX 3070 Ti
- Driver: 610.62
- VRAM: 8192 MiB total; 654 MiB used before, 693 MiB after
- Temperature: 37 C before, 45 C after
- Utilization: 23% before, 5% after
- HAGS: UNKNOWN; not changed
- New `nvlddmkm` Event 153: NO
- Narrow post-run checks found no new `nvlddmkm`, Display, WHEA, Application
  Error, or Windows Error Reporting events.

## Classification

`KNOWN_GOOD_AMPERE_2X_WORKING`

The evidence exceeds capability-only support: the command explicitly requested
one generated frame, Streamline transitioned interpolation to enabled, the
donor observed feature creation and active generation activity, and the
application exited cleanly. Exact presentation counters and output readback
remain unavailable in this sample instrumentation.

Next step: `CAPTURE_WORKING_CONTRACT_FOR_STANDALONE` (not executed).

## Git

No commit. No push.
