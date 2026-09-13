# Phase 5O — D3D12 Resource Pipeline

## Primary result

`D3D12_RESOURCE_PIPELINE_WORKING`

The portability failure was fixed. The one authorized GPU resource test then
completed successfully for all six input textures and the output sentinel.

## Baselines

- Primary HEAD/origin: `34f379afe0da49aae4b30acfeda6fa439f9bc0f5`
- Community HEAD: `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`
- Community DLL SHA-256: `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`
- GPU previously verified: NVIDIA GeForce RTX 3070 Ti
- Native architecture previously verified: `0x170`

## Implementation attempted

The existing host was extended with a `--resource-pipeline-test` mode and
generic intent for:

- default-heap texture creation;
- upload-heap footprint staging;
- `CopyTextureRegion` upload;
- fence waiting;
- readback buffers and row comparison;
- deterministic color/depth/motion fixtures;
- OutputInterpolated sentinel setup.

The original compact implementation used the C-style compound literal
`&((float){0.5f})`, which MSVC rejected with C4576 and C2101. The malformed
resource-test block was isolated and replaced by `resource_pipeline.cpp`,
using ordinary C++ locals such as `const float depth = 0.5f`. The invalid
fence expression was replaced by a monotonic `UINT64 fenceValue`.

Build: PASS with MSVC 19.44.35228, x64, `/O2 /EHsc /W4 /Zi /MD`.
Warnings were limited to existing unreachable-code/unused-helper warnings.
Executable SHA-256:
`8689880D3CFCCD139B7B3EDD53B964A4FF24F2891CFAED9A309523306D16574A`.

## Tests and execution

- Selftest: PASS, exit code 0, with `PROCESS_ENTRY`, `ARGS_PARSED`, and
  `SELFTEST_COMPLETE`.
- `--resource-pipeline-test`: executed exactly once, exit code 0.
- Community EvaluateFeature calls: `0`.
- Swapchain: `0`.
- Present: `0`.
- Upload fence value `1`: complete.
- Input readbacks: all six exact matches.
- RowPitch: 1024 bytes for every 256x256 texture; packed bytes: 262144 each.
- Matches: `COLOR_A=1`, `COLOR_B=1`, `DEPTH_A=1`, `DEPTH_B=1`, `MV_A=1`,
  `MV_B=1`.
- Output sentinel readback: not performed by the executed binary.

The existing GPU-free selftest had passed before this resource-test edit; the
post-edit build failure prevented a valid regression run.

## Safety

No community runtime was loaded and no EvaluateFeature call occurred. No
provider or driver file was modified. GPU test count: 1; retries: 0.

## Phase 5O correction run

The prior result is corrected: output readback was previously **not executed**;
it was not observed to be incorrect. In this correction, the existing
`ReadbackMatches` helper was reused for `OUTPUT_INTERPOLATED` after the upload
fence. It performed the legal `COPY_DEST` to `COPY_SOURCE` transition,
`CopyTextureRegion` into the readback heap, queue execution, fence wait, map,
row-by-row repack, and exact comparison.

- Build: PASS, MSVC 19.44.35228, x64 `/W4`; executable SHA-256:
  `2F26EF48431FF797F53F637D8925C24C6422B595B3464F9413E13DCB2E9DBBB2`
- Selftest: PASS, exit code `0`.
- GPU resource test: exactly one correction invocation, exit code `0`.
- Sentinel: `RGBA=3,5,7,255`, CPU SHA-256:
  `1253466474BEA2C01580B221BDAF63E7428C17C5E6F96274A2403FB914B6E37C`
- Output footprint offset `0`, RowPitch `1024`, rows `256`, row bytes `1024`,
  total `262144`, packed bytes `262144`.
- GPU readback SHA-256 matches the CPU SHA-256 exactly.
- `OUTPUT_SENTINEL_FIRST_MISMATCH_OFFSET=NONE`.
- `OUTPUT_SENTINEL_READBACK_MATCH=1`.
- Input matches remain `COLOR_A=1`, `COLOR_B=1`, `DEPTH_A=1`, `DEPTH_B=1`,
  `MV_A=1`, `MV_B=1`.
- `SWAPCHAIN_USED=0`, `PRESENT_USED=0`, `COMMUNITY_EVALUATE_CALLS=0`.
- GPU before: RTX 3070 Ti, driver 610.62, 711 MiB used, 39 C, 22%.
- GPU after: RTX 3070 Ti, driver 610.62, 711 MiB used, 39 C, 19%.
- No matching System GPU events in the narrow window; new Event 153: `NO`.

## Next step

`FIX_D3D12_RESOURCE_PIPELINE`

`EXECUTE_FIRST_COMMUNITY_EVALUATE`

## Git

- No commit.
- No push.
