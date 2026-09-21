# Phase 5R — Offline Public-NGX-ABI 2X Milestone

## A. Starting state

The starting point had two distinct failures:

- Phase 5P reached the community `NVSDK_NGX_D3D12_EvaluateFeature` export, but its bootstrap call returned `0xBAD00005` (`NVSDK_NGX_Result_FAIL_InvalidParameter`).
- Phase 5Q corrected three objective contract defects (`DLSSG.Width`/`Height`, shader-readable input states, and a 4-byte UAV `OutputDisableInterpolation` buffer), but its attempted retest exited with code 39 during the first input upload. It did not reach CreateFeature or Evaluate, so the corrected contract had never been tested.

Baseline integrity remained intact:

- Primary `HEAD` and `origin/main`: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community source baseline: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community DLL SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`

## B. Investigation workstreams

No separate sub-agent execution facility was available in this task. The main agent completed the two independent read-only workstreams before modifying or running GPU code:

1. **Exit-39 regression:** Compared the Phase 5O resource sequence with the current Phase 5Q path. It found that `CreateCommandList` returns an open list, while the first per-texture upload immediately called `allocator->Reset()` and `list->Reset()` without closing that initial list. Recommendation: close the initial command list once, retain the Phase 5Q state transitions, and add stage/HRESULT logging. Adopted.
2. **Evaluate contract diff:** Compared the host with NVIDIA's public DLSS-G definitions/helper and the known-worker contract supplied for this phase. It found incomplete helper-shaped scalar/subrect population and five dangling matrix pointers caused by storing pointers into a local options structure that was destroyed before Evaluate. Recommendation: use caller-owned option storage, set `BackbufferFrameID` through the unsigned-long-long overload, populate the full public helper contract, and verify all non-null resource pointers. Adopted.
3. **Targeted community validator inspection:** Not needed. Run 1 passed both Evaluate calls after the objective contract corrections, so binary validation-path inspection would not have changed the result.

## C. Exit-39 root cause

The failing path was the old `Run2x` input loop calling `Upload`, whose first operation was:

```text
allocator->Reset()
list->Reset(allocator, nullptr)
```

The command list created by `ID3D12Device::CreateCommandList` was still open. Resetting it in that state failed, `Upload` returned false, and `Run2x` mapped that failure to exit code 39.

The correction is at [community_run2x.cpp](C:/Users/mark/Desktop/dlss-rtxsr-upscaler/native/dlssg_sm86_offline/community_run2x.cpp): after creating the D3D12 objects, the host closes the initial command list, logs `INITIAL_COMMAND_LIST_CLOSE_RESULT`, and only then enters the fenced per-resource reset/upload sequence. Each helper now logs its failing HRESULT and resource name. The successful run reported:

```text
INITIAL_COMMAND_LIST_CLOSE_RESULT=0x00000000
UPLOAD_COMPLETE name=COLOR_A finalState=0x40 fence=1
...
UPLOAD_COMPLETE name=MV_B finalState=0x40 fence=6
```

No correct Phase 5Q transition was removed.

## D. Evaluate contract

The final contract matches the public helper/known-worker shape:

- Create-time generic and DLSS-G dimensions: `256 x 256`
- Backbuffer/internal format: `DXGI_FORMAT_R8G8B8A8_UNORM` (`28`)
- Creation/visibility node masks: `1` / `1`
- `ResourceAlwaysProvided_Flags`: `0x0500000F` (Backbuffer, MVecs, Depth, HUDLess, OutputInterpolated, OutputDisableInterpolation)
- `ResourceNeverProvided_Flags`: `0x020000B0` (UI, UIAlpha, BidirectionalDistortionField, OutputReal)
- UI recomposition: disabled
- Input states: `D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE` (`0x40`)
- Output texture and disable buffer: `D3D12_RESOURCE_STATE_UNORDERED_ACCESS` (`0x8`)
- Bootstrap: frame ID `0ULL`, Reset `1`, MultiFrameCount `1`, MultiFrameIndex `1`
- Measured: frame ID `1ULL`, Reset `0`, MultiFrameCount `1`, MultiFrameIndex `1`
- Five identity matrices are stored in caller-owned `NVSDK_NGX_DLSSG_Opt_Eval_Params` objects that remain alive through each Evaluate/fence sequence.
- Jitter and pinhole offset: zero
- Motion-vector scale: `1/256`, `1/256`
- Camera: near `0.1`, far `1000`, FOV `1.04719755`, aspect `1.0`
- HDR/depth-inverted/camera-motion/automode/not-rendering/menu: false
- Orthographic projection and dilated motion vectors: true
- Motion-vector invalid value: `-65500.0`
- Non-null resource subrects: origin `0,0`, size `256 x 256`; null-resource subrects remain zero.

Before each Evaluate, the official NVIDIA parameter object returned every non-null D3D12 pointer identically. The bootstrap manifest logged `KNOWN_WORKER_CONTRACT_MATCH=1`.

`OutputDisableInterpolation` is a 4-byte DEFAULT-heap UAV buffer. Before both Evaluate calls, the command list records `UAV -> COPY_DEST`, copies four zero bytes from an upload buffer, then records `COPY_DEST -> UAV`. Output sentinel prefill uses the analogous legal texture transitions immediately before measured Evaluate.

## E. Build and tests

- Compiler: Microsoft C/C++ 19.44.35228 for x64
- Settings: `/std:c++17 /O2 /EHsc /W4 /Zi /MD`, linker `/DEBUG`
- Build: PASS
- Executable SHA-256: `1F775B4AE6E4C8C35A2F3CAD2BF990ADA58CF93778D4C677A640E59C121E21FE`
- Warnings: only pre-existing unused legacy helpers, one `sprintf` deprecation, one unused parameter, and pre-existing unreachable-code warnings; no new material warning blocked execution.

GPU-free selftest:

```text
PROCESS_ENTRY
ARGS_PARSED
SELFTEST_COMPLETE
SELFTEST_EXIT=0
```

Resource-only regression (does not call community Evaluate): PASS. All seven exact upload/readback comparisons passed for COLOR_A, COLOR_B, DEPTH_A, DEPTH_B, MV_A, MV_B, and OUTPUT_INTERPOLATED. The sentinel GPU SHA remained `1253466474BEA2C01580B221BDAF63E7428C17C5E6F96274A2403FB914B6E37C`.

## F. Live Evaluate runs

### Run 1

- Reason: first retest after fixing the concrete exit-39 list-state defect, completing the known contract, fixing matrix lifetime, and implementing measured output persistence.
- Command:

```text
C:\Users\<user>\Desktop\dlss-rtxsr-upscaler\native\dlssg_sm86_offline\bin\dlssg_sm86_offline.exe --run-2x C:\Users\<user>\Desktop\dlss-community-research\dlssg_for_sm86\version.dll C:\Users\<user>\Desktop\dlss-community-research\Streamline_Sample_MFGAmpere\_bin
```

- Official NGX Init: `0x00000001`
- Community Init: `0x00000001`
- Community CreateFeature: `0x00000001`, non-null handle
- Bootstrap Evaluate: `0x00000001`
- Bootstrap fence: complete; device-removed reason `0x00000000`
- Measured Evaluate: `0x00000001`
- Measured fence: complete; device-removed reason `0x00000000`
- Readback fence: complete; device-removed reason `0x00000000`
- Process exit code: `0`

Runs 2 and 3 were not used. Evaluate-run budget consumed: `1 / 3`. There were no retries.

## G. Final success path

The successful path was:

1. Select NVIDIA GeForce RTX 3070 Ti and match the DXGI and NVAPI full LUID.
2. Verify native architecture `0x170`.
3. Create one D3D12 direct queue, allocator/list, and fence.
4. Initialize official NGX and allocate the official `NVSDK_NGX_Parameter` object.
5. Load the exact community runtime and call its Init export.
6. Create and upload six input textures; transition all inputs to `NON_PIXEL_SHADER_RESOURCE`.
7. Call community CreateFeature and receive a non-null community feature handle.
8. Call community bootstrap Evaluate and fence successfully.
9. Zero the disable buffer, prefill the caller-owned output with the known sentinel, and call community measured Evaluate.
10. Fence, copy the output/disable resources to readback memory, repack rows, validate the bytes, and persist the result.

The actual Evaluate implementation and feature handle came from the community SM86 runtime; the parameter object came from official NVIDIA NGX. No swapchain and no Present were used.

## H. Generated output

- Raw: [generated_2x.raw](C:/Users/mark/Desktop/dlss-rtxsr-upscaler/native/dlssg_sm86_offline/runtime/output/generated_2x.raw)
- Metadata: [generated_2x.json](C:/Users/mark/Desktop/dlss-rtxsr-upscaler/native/dlssg_sm86_offline/runtime/output/generated_2x.json)
- Dimensions: `256 x 256`
- Format: `DXGI_FORMAT_R8G8B8A8_UNORM`
- Readback RowPitch: `1024`
- Packed bytes: `262144`
- Generated SHA-256: `86F2066E3998FBCFFEBADBF1B93B3A3AFDEF9ED28E90D66C833EA73EE963CB4D`
- Sentinel SHA-256: `1253466474BEA2C01580B221BDAF63E7428C17C5E6F96274A2403FB914B6E37C`
- Input A SHA-256: `D7316B9D0A65A0681173134838566FA8B3DF1F589C5F88EC5F88458D5752CB80`
- Input B SHA-256: `7372F8E5FC8F559FC16922BCC2AD91EB78090E27C8D77394321514E97AC1298B`
- OutputDisableInterpolation: `0`
- Identical to sentinel/A/B: `NO / NO / NO`
- All zero: `NO`
- Constant: `NO`
- Byte minimum / maximum / mean: `16 / 255 / 88.807343`
- MAD generated-to-A: `0.876045`
- MAD generated-to-B: `0.894417`
- MAD A-to-B: `1.765625`

The raw file's SHA-256 was independently recomputed after process exit and matched the in-process hash.

## I. GPU health

Before Run 1:

```text
NVIDIA GeForce RTX 3070 Ti, driver 610.62, 8192 MiB total, 721 MiB used, 40 C, 19%
```

After Run 1:

```text
NVIDIA GeForce RTX 3070 Ti, driver 610.62, 8192 MiB total, 732 MiB used, 40 C, 36%
```

The narrow run interval contained no matching `nvlddmkm`, Display, WHEA, Application Error, or Windows Error Reporting events. New nvlddmkm Event 153: **NO**.

## J. Primary result

`OFFLINE_PUBLIC_NGX_ABI_2X_WORKING`

All required success predicates passed: RTX 3070 Ti/full LUID/native `0x170`, community Init/Create, bootstrap and measured Evaluate/fences, disable flag zero, modified nonzero/nonconstant caller-owned output, persisted readback, no swapchain/Present, and healthy GPU.

## K. Remaining blockers

There is no blocker to the offline 2X milestone. Productization still needs a persistent process protocol, reusable allocations, real decoded frame ingestion, and a production motion-vector source. The known official NGX shutdown hang remains intentionally out of scope; the successful process logged `NGX_SHUTDOWN_SKIPPED_KNOWN_HANG=1` after persisting output.

## L. Distance to productization

The next worker should use this lifecycle:

- `INIT`: launch one persistent x64 process; select/match the RTX GPU; create one D3D12 device/queue/fence; initialize official NGX once; allocate one official parameter object; load and initialize the community runtime once.
- `CREATE`: declare fixed dimensions/formats and resource masks; create one community feature handle; allocate reusable input, output, disable, upload, and readback resources.
- `PROCESS_FRAME_PAIR`: receive adjacent real frames plus depth and motion, upload into reusable slots, use Reset only when history is invalid, increment `BackbufferFrameID` monotonically, Evaluate, fence, read back one generated frame, and return bytes plus SHA/status metadata.
- `RESET_HISTORY`: mark the next bootstrap input with Reset `1`, clear/zero outputs, and reset the worker's adjacent-frame bookkeeping without reinitializing NGX.
- `SHUTDOWN_PROCESS`: release only resources/features already proven safe, skip the known-hanging NGX shutdown exports, and terminate the process to reclaim runtime state.

A minimal binary protocol should use a fixed little-endian header containing magic, protocol version, opcode, request ID, width, height, format, and payload lengths. `PROCESS_FRAME_PAIR` should carry tightly packed Frame A/Frame B RGBA8 payloads and separately sized depth/motion payloads; the response should carry result code, disable flag, output dimensions/format/length, and packed output bytes. Transport framing must permit exact reads/writes and reject oversized or inconsistent lengths before touching GPU resources.

Adjacent real video frames can come from a decoder converted to the worker's declared color format. Depth and current-to-previous motion vectors are not derivable from ordinary compressed video metadata in general; productization therefore needs either engine-native depth/MVs, an optical-flow/motion-estimation stage plus an explicit depth strategy, or a validated neural/geometry estimator. Motion-vector convention, units, dilation, invalid-value handling, and frame IDs must remain identical to this milestone contract.

## M. Next step

`IMPLEMENT_PERSISTENT_OFFLINE_2X_WORKER`

This next step was designed only; it was not executed.

## N. Git

- No commit.
- No push.
