# MFG GPU Timestamp Instrumentation — 2026-09-18

This branch adds explicitly opt-in D3D12 timestamp queries to the source of the
C55 native DLSS-G worker while preserving protocol v4 and the currently pinned
validated worker binary.

## Safety boundary

Timestamp instrumentation is enabled only when the worker is started with
`DLSSG_GPU_TIMESTAMPS=1`. It is deliberately independent of
`DLSSG_WORKER_DIAGNOSTIC`.

This separation matters for NVOF: verbose diagnostic mode intentionally selects
the older diagnostic motion path, while production GPU-resident NVOF requires
forward-only flow plus `DLSSG_NVOF_GPU_FLOW=1`. The bounded instrumented
validator therefore uses timestamp opt-in with verbose diagnostic mode **off**,
`DLSSG_NVOF_DIRECTION=forward`, and `DLSSG_NVOF_GPU_FLOW=1`.

It does **not**:

- change `worker_protocol.h`;
- enlarge `ProcessResponse`;
- change the production default profile;
- replace the pinned C55 executable;
- enable concurrency or reorder GPU commands;
- change DLSS-G resources, options, output ordering, or fence behavior.

The currently distributed validated worker therefore remains byte-for-byte
unchanged until a separately built instrumented worker is deliberately used for
measurement. Normal production startup does not set `DLSSG_GPU_TIMESTAMPS`.

## Direct-queue timestamp layout

The timestamp-enabled worker creates one D3D12 timestamp query heap and a
readback buffer. For each generated group it records timestamps on the existing
direct command list around:

1. color/motion input upload copies;
2. each DLSS-G Evaluate submission;
3. each generated-output readback copy segment; and
4. the complete direct-queue group.

After the existing group fence completes, resolved timestamps are read and
emitted as stderr records:

```text
GPU_TIMESTAMP frame=<frame> stage=<stage> index=<index> ms=<milliseconds> frequency=<ticks-per-second>
```

Current stages are:

- `input_upload`
- `dlssg_evaluate`
- `output_copy`
- `group_total`
- `nvof_bracket`
- `nvof_conversion`

`dlssg_evaluate` and `output_copy` use generated index 1..3. Group/input/NVOF
records use index 0.

## What these timestamps mean

These are GPU timestamps from the worker's existing **D3D12 direct queue**.
They are materially different from the existing CPU/API fields such as
`evaluate_cpu_ms` and `gpu_wait_ms`.

They can answer questions such as:

- how much direct-queue GPU time the input copies consume;
- the GPU duration of Evaluate index 1 versus later MFG indices;
- how much direct-queue time each output-copy segment occupies;
- how those pieces compare with total direct-queue group duration.

They still do **not** measure pure NVIDIA Optical Flow engine execution
directly.

The NVOF GPU-resident path now adds a cross-engine timestamp bracket:

1. timestamp 0 executes on the D3D12 direct queue after the NVOF input upload;
2. that queue signals the NVOF input fence;
3. Optical Flow waits on that input fence, executes on its own engine, and
   signals its output fence;
4. the direct queue waits on that NVOF output fence;
5. timestamp 1 is the first direct-queue timestamp after that wait;
6. timestamp 2 is recorded after the flow-copy + compute-conversion work.

Therefore:

- `nvof_bracket` = GPU-side elapsed time across queue handoff + Optical Flow
  scheduling/execution + output-fence handoff. It is **not** labeled
  `nvof_execute`.
- `nvof_conversion` = direct-queue GPU time for the existing flow copy and
  S10.5 → R16G16_FLOAT compute conversion.

The query results are resolved on the existing conversion command list and read
only after the worker's existing group fence completes, avoiding a new CPU wait
inside the NVOF path.

Existing `nvof_upload_ms`, `nvof_execute_ms`, and
`flow_conversion_ms` remain CPU/API/wait-attributed timings and are retained
for comparison.

## Reporting

`src/core/dlssg_gpu_timing.py` parses timestamp diagnostics without changing
the worker wire protocol.

Both:

- `tools/dlssg_benchmark.py`
- `tools/validate_dlssg_candidate.py`

now include a `gpu_timestamps` summary when instrumented diagnostics are
present. Older validated workers simply report `available: false`.

This makes the reporting path backward-compatible.

## Native build gate

The native worker source is compiled by
`native/dlssg_sm86_offline/build.ps1` against the separately staged NVIDIA
DLSS, NVAPI, and Optical Flow SDK inputs. On this research branch the build
script defaults to `bin-instrumented`, not the validated `bin` directory, so
a development timing build cannot silently overwrite the pinned C55 worker.

GitHub ordinary CI intentionally does not possess those SDK inputs, so this
branch can statically test protocol/default invariants and Python parsing but
cannot claim that the changed native source has been compiled.

Before any GPU timing run, a development machine must:

1. build the native worker from this branch;
2. pass its native selftest;
3. retain the existing validated worker separately;
4. run the instrumented worker only as an explicit development override;
5. capture its SHA-256 as experimental evidence;
6. run the existing bounded 256x256 validation before practical-resolution
   timing work.

No production runtime identity should be updated merely because the
instrumented build compiles.


## One-command development workflow

`tools/build_validate_dlssg_instrumented.ps1` now provides the intended
development sequence.

By default it:

1. verifies the exact legacy community-runtime SHA-256;
2. verifies the exact NVIDIA 310.9.1 provider SHA-256;
3. builds into `bin-instrumented`;
4. runs the GPU-free native `--selftest`;
5. records the new worker SHA-256;
6. stops **before GPU validation**.

GPU validation requires the explicit `-Validate256` switch. With that switch,
the script invokes the separate `tools/validate_dlssg_instrumented.py` gate,
which refuses the production C55 hash and accepts only an executable under
`bin-instrumented`. It then runs exactly six bounded cells: 2X/3X/4X ×
external-motion/NVOF at 256x256.

The normal `tools/validate_dlssg_candidate.py` C55 identity gate is unchanged.


The isolated validator is intentionally **not** wired into normal setup or
startup. It is a developer evidence tool only. The standard C55 validator still
requires the exact pinned production worker hash.


## Final static build/synchronization audit

Before requesting a local MSVC build, the instrumented source was re-audited for
queue ordering, query capacity, generated build artifacts, and resource
lifetime.

Findings:

- The DLSS-G timestamp probe uses 16 query slots. 4X requires 12 slots:
  timestamp 0/1 for input upload, three timestamps per generated frame, and the
  final group timestamp. A compile-time assertion now protects this invariant.
- The NVOF bracket resolve is submitted on the same D3D12 direct queue before
  the DLSS-G group command list. The existing group fence is signalled after
  both the NVOF conversion/resolve work and the DLSS-G group work, so
  `ConsumeGpuTimings()` maps the readback only after the query resolve is
  complete.
- An enabled NVOF timing sample may not be overwritten. If a prior sample is
  still pending, the next GPU-flow call fails closed with
  `NVOF_GPU_TIMESTAMP_PENDING_UNCONSUMED`.
- The timestamp query heap and readback resource now have an explicit release
  path/destructor. Normal worker CLOSE still ends with the established
  `ExitProcess(0)` lifecycle; this cleanup primarily makes abnormal/alternate
  teardown internally complete.
- `nvof_d3d12.h` now forward-declares `ID3D12Resource`, removing dependency
  on include order.
- The native build no longer rewrites the tracked
  `native/dlssg_sm86_offline/flow_convert_bytecode.h`. FXC emits the CSO and
  generated C header under the requested build output directory, and that
  directory is placed first on the compiler include path.
- The build now explicitly throws when `cl.exe` returns a non-zero exit code.

No protocol-v4 layout, validated runtime identity, or normal application startup
path changed as part of these hardening edits.

The local compile, GPU-free selftest, and bounded 256x256 six-cell matrix have
now passed. Practical-resolution timing is the next MFG measurement gate.


## First bounded hardware timestamp evidence

The local RTX 3070 Ti development machine completed the isolated six-cell
256x256 matrix after the native source compiled and the GPU-free selftest
passed.

Evidence from the successful run:

- experimental worker SHA-256:
  `CF4471AC5D3543403A4DAB331ADAC9FA537648666B67135E1BC95E502A97F257`;
- legacy community runtime SHA-256 remained
  `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`;
- NVIDIA provider SHA-256 remained
  `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82`;
- 2X, 3X, and 4X all passed with both external motion and GPU-resident NVOF;
- every cell emitted the required direct-queue timestamp stages;
- NVOF cells additionally emitted `nvof_bracket` and `nvof_conversion`;
- no device-removed error was reported.

Representative medians from this bounded run:

| Cell | group_total | NVOF bracket | NVOF conversion | output copy |
| --- | ---: | ---: | ---: | ---: |
| 2X external | 0.436 ms | n/a | n/a | 0.009 ms |
| 2X NVOF | 1.046 ms | 4.485 ms | 0.009 ms | 0.010 ms |
| 3X external | 1.325 ms | n/a | n/a | 0.010 ms |
| 3X NVOF | 1.318 ms | 4.742 ms | 0.009 ms | 0.010 ms |
| 4X external | 2.209 ms | n/a | n/a | 0.009 ms |
| 4X NVOF | 2.215 ms | 4.546 ms | 0.009 ms | 0.009 ms |

The 2X NVOF first measured bracket was 19.427 ms, while the subsequent two
samples were 4.485 and 4.464 ms. It is therefore treated as warm-up evidence,
not as the steady-state Optical Flow bracket.

The bounded result changes the optimization priority. At 256x256, output-copy
and flow-conversion GPU time are negligible compared with DLSS-G Evaluate and
the cross-engine NVOF bracket. No production architecture change is justified
from this small-resolution run alone; the next measurement gate is practical
resolution.

## Practical-resolution research gate

The instrumented validator now has a separate `practical` matrix. It is not
reachable through normal C55 validation. The matrix is intentionally limited to:

- 1280x720: 2X external, 2X NVOF, 4X external, 4X NVOF;
- 1920x1080: 2X external, 2X NVOF, 4X external, 4X NVOF.

The practical path retains the exact legacy runtime/provider identity gates,
instrumented-worker isolation, selftest, timestamp-stage requirements, and a
per-cell timeout. Its purpose is to determine whether the approximately
4.5-ms NVOF cross-engine bracket is primarily fixed overhead or scales with
resolution, and how DLSS-G Evaluate scales relative to that bracket.

The one-command entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_validate_dlssg_instrumented.ps1 -ValidatePractical
```

The expected evidence file is
`runtime/audit/mfg-instrumented-practical-validation.json`.


## Practical-resolution 1x1 NVOF hardware evidence

The RTX 3070 Ti practical matrix completed successfully on research head
`017499a600d988172f643aec68718431aca2c91f`.

Experimental worker SHA-256:

`79DA7749897462884F17B9ED549C7714380AA680017671BF5CBC2D7599C43E34`

The legacy community runtime and NVIDIA provider identities remained unchanged.
All eight cells passed:

- 1280x720: 2X external, 2X NVOF, 4X external, 4X NVOF;
- 1920x1080: 2X external, 2X NVOF, 4X external, 4X NVOF.

No device-removal failure was observed.

Representative steady-state medians:

| Geometry / path | group_total | NVOF bracket | NVOF conversion | input upload | output copy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 720p 2X external | 1.708 ms | n/a | n/a | 0.286 ms | 0.139 ms |
| 720p 2X NVOF | 1.580 ms | 6.915 ms | 0.035 ms | 0.144 ms | 0.138 ms |
| 720p 4X external | 3.617 ms | n/a | n/a | 0.283 ms | 0.138 ms |
| 720p 4X NVOF | 3.501 ms | 7.136 ms | 0.035 ms | 0.146 ms | 0.138 ms |
| 1080p 2X external | 2.651 ms | n/a | n/a | 0.634 ms | 0.313 ms |
| 1080p 2X NVOF | 2.345 ms | 13.712 ms | 0.063 ms | 0.319 ms | 0.313 ms |
| 1080p 4X external | 4.894 ms | n/a | n/a | 0.635 ms | 0.313 ms |
| 1080p 4X NVOF | 4.574 ms | 13.784 ms | 0.065 ms | 0.319 ms | 0.313 ms |

The first measured sample in some cells carries a clear warm-up cost and is not
used to infer steady-state scaling.

### Interpretation

The NVOF cross-engine bracket is resolution-dependent, not predominantly fixed
handoff overhead. Moving from 1280x720 to 1920x1080 increases the steady-state
bracket from about 7.0 ms to about 13.7-13.8 ms, roughly 1.9x while pixel count
increases 2.25x.

The direct-queue flow conversion is not a material bottleneck. It remains around
0.035 ms at 720p and 0.064 ms at 1080p. Output-copy cost is also much smaller
than the NVOF bracket.

Therefore the next optimization experiment targets NVOFA work density rather
than conversion-shader micro-optimization or output-copy elimination.

## Opt-in 4x4 NVOF output-grid experiment

NVIDIA documents Ampere support for 4x4, 2x2, and 1x1 NVOFA output grids and
describes coarser blockwise flow as suitable for software upsampling to a dense
flow map.

The research worker now supports an explicitly opt-in environment setting:

`DLSSG_NVOF_OUTPUT_GRID=4`

Default remains 1x1.

For the 4x4 experiment:

- NVOFA still receives full-resolution input frames;
- the NVOFA output resource is allocated at
  `ceil(width/4) x ceil(height/4)`;
- the existing GPU conversion stage expands each block vector to the
  corresponding full-resolution 4x4 pixel region;
- vector magnitude is not multiplied by four because NVOFA flow values remain
  input-pixel displacement values;
- the full-resolution DLSS-G motion resource and protocol contract are
  unchanged;
- CPU/readback flow paths remain restricted to the existing 1x1 mode.

The explicit comparison command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_validate_dlssg_instrumented.ps1 -ValidatePracticalGrid4
```

This is a research-only performance experiment. It is not a production default
and must be followed by withheld-frame/perceptual quality comparison before any
promotion could be considered.


## Practical 4x4 NVOF output-grid result

The first practical 4x4 hardware run completed successfully on the RTX 3070 Ti.

Experimental worker SHA-256:

`C570011DBAC20C7DC41C2D0A04283D696EBD513F93AAA1D4CFE4F8D280B364FB`

The pinned legacy community runtime and NVIDIA provider hashes remained unchanged.
All eight 720p/1080p 2X/4X external/NVOF cells passed, with no reported device
removal.

Observed 4x4 NVOF bracket samples:

| Geometry | Multiplier | Bracket samples | Reported median |
| --- | ---: | --- | ---: |
| 1280x720 | 2X | 24.039, 1.647, 2.434 ms | 2.434 ms |
| 1280x720 | 4X | 20.285, 4.287, 2.259 ms | 4.287 ms |
| 1920x1080 | 2X | 22.728, 2.697, 2.706 ms | 2.706 ms |
| 1920x1080 | 4X | 4.551, 5.422, 3.912 ms | 4.551 ms |

The first sample is a clear warm-up outlier in three of the four NVOF cells.
Therefore this run is evidence that coarse-grid NVOF can materially reduce the
cross-engine bracket, but the three-sample median is not precise enough for a
promotion decision.

The same run also showed materially different external-path DLSS-G timings from
the prior practical run, especially at 1080p. Cross-run percentages therefore
remain confounded by GPU clock/load state.

The next gate is a same-invocation A/B matrix:
`practical-grid-ab`.

It runs only NVOF cells, compares grids 1 and 4 at each geometry/multiplier, and
uses eight measured frames per child. The purpose is to reduce warm-up
sensitivity and compare both NVOF grid modes under much closer machine
conditions. It remains research-only; production/default grid selection is
still 1x1.

The explicit command is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_validate_dlssg_instrumented.ps1 -ValidatePracticalGridAB
```

The corrected evidence filename is:

`runtime/audit/mfg-instrumented-practical-grid-ab-validation.json`

## Controlled same-run 1x1 versus 4x4 NVOF result

The same-invocation eight-frame-per-cell A/B matrix completed successfully on
the RTX 3070 Ti. The experiment used the same instrumented worker build for
both grid modes and preserved the pinned legacy runtime/provider identities.

Experimental worker SHA-256:

`534937A896E511F3CA6FD23AEB8CA3BFB147F2C31AE7D2861902DE2141F22663`

NVOF bracket medians:

| Geometry | Multiplier | Grid 1 | Grid 4 | Reduction |
| --- | ---: | ---: | ---: | ---: |
| 1280x720 | 2X | 7.074 ms | 1.832 ms | 74.1% |
| 1280x720 | 4X | 7.062 ms | 1.976 ms | 72.0% |
| 1920x1080 | 2X | 13.551 ms | 2.771 ms | 79.6% |
| 1920x1080 | 4X | 13.653 ms | 3.284 ms | 75.9% |

The paired DLSS-G `group_total` medians stayed effectively unchanged between
grid modes:

- 720p 2X: 1.577 ms (grid 1) versus 1.573 ms (grid 4);
- 720p 4X: 3.486 ms versus 3.509 ms;
- 1080p 2X: 2.353 ms versus 2.344 ms;
- 1080p 4X: 4.576 ms versus 4.640 ms.

The flow-conversion stage also became cheaper because the coarse source texture
contains 1/16 as many vectors before dense expansion:

- 720p: ~0.0358 ms (grid 1) versus ~0.0174 ms (grid 4);
- 1080p: ~0.066 ms versus ~0.0266 ms.

This same-run result removes the earlier cross-run GPU-state confounder and
establishes 4x4 as the current MFG NVOF performance candidate.

It did **not**, by itself, establish acceptable image quality. That missing gate
was subsequently run with withheld real-frame A/B evidence as described below.

## Real-video grid-1 versus grid-4 quality evidence

The first real-video quality campaign completed on the RTX 3070 Ti using the
same grid-1/grid-4 implementation and a 640x480, approximately 29.999-fps
source. The 2X harness sampled five non-overlapping windows beginning at source
frames 0, 30, 90, 150, and 210. Each window contained eight withheld midpoint
comparisons, for 40 generated-frame pairs total.

Every window completed both grid captures and returned `QUALITY_AB_PASS`.
Across all 40 paired samples, the weighted aggregate differences
(grid 4 minus grid 1) were:

| Metric | Grid 1 | Grid 4 | Difference |
| --- | ---: | ---: | ---: |
| MAE | 6.333788 | 6.333345 | -0.000443 (-0.0070%) |
| RMSE | 10.480888 | 10.480496 | -0.000392 (-0.0037%) |
| PSNR | 32.546326 dB | 32.546652 dB | +0.000326 dB |
| SSIM RGB | 0.950260 | 0.950263 | +0.0000037 |
| edge MAE | 19.850778 | 19.851953 | +0.001174 (+0.0059%) |

Per-frame win counts were likewise mixed rather than systematically regressing:
grid 4 won 22/40 MAE comparisons, 22/39 non-tied RMSE comparisons, 22/39
non-tied PSNR comparisons, 23/40 SSIM comparisons, and 20/38 non-tied edge-MAE
comparisons. One segment favored grid 1 on most metrics while another favored
grid 4; the absolute deltas remained very small.

This closes the **first** withheld-frame quality gate for the 4x4 candidate:
the tested material shows no meaningful systematic 2X quality loss while the
controlled practical-resolution timing A/B showed a 72-80% reduction in the
NVOF cross-engine bracket.

The evidence is deliberately not generalized beyond its scope. The source was
640x480 at about 30 fps, so 2X withheld-frame sampling yields about 15-fps
anchors. It is a coarse-temporal stress test, not a substitute for a diverse
60-fps, 720p/1080p corpus with text/UI, faces, thin detail, occlusion and
disocclusion.

## Application-level grid4 candidate profile

The normal pinned C55 worker/profile remains unchanged. To carry the validated
research settings into the real renderer without relying on ambient environment
variables, the Python worker client now exposes an explicit research profile:

`grid4-gpu-candidate`

That profile fixes the exact tested controls:

- `DLSSG_NVOF_DIRECTION=forward`;
- `DLSSG_NVOF_GPU_FLOW=1`;
- `DLSSG_NVOF_OUTPUT_GRID=4`.

The default profile is still `validated`, which preserves the existing C55
behavior and does not inject GPU-flow or output-grid settings. The candidate is
also rejected when verbose diagnostic mode is enabled, because the diagnostic
motion path is intentionally different from the production GPU-resident path.

The developer CLI exposes the candidate with:

```powershell
python tools\dlssg_video.py ... --nvof-profile grid4-gpu-candidate
```

A render manifest records the selected NVOF profile. This is a promotion
**candidate**, not a production-default change: a newly built candidate worker
still needs the existing native selftest/hardware gates before the distributed
pinned C55 binary or normal UI default can change.

The application-level candidate gate is:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_dlssg_grid4_candidate.ps1 `
    -Input "C:\path\to\clip.mp4"
```

It rebuilds and GPU-free self-tests the isolated instrumented worker, refuses
the pinned production C55 SHA-256, renders the supplied source at 2X through
the real video path with `grid4-gpu-candidate`, and then fails closed unless:

- the render manifest reports `PASS` and the exact candidate profile;
- no interpolation-disabled frame is recorded;
- no device-removal result is recorded;
- the native worker log confirms `NVOF_OUTPUT_GRID_SELECTED=4`.

Passing that command is the next candidate-integration hardware gate. It still
does not alter the normal UI/default worker automatically.
