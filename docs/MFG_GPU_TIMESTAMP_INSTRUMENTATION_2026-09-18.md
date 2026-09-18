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

At this point the next MFG gate is a **local compile + GPU-free selftest** using
`tools/build_validate_dlssg_instrumented.ps1` without `-Validate256`. The
256x256 six-cell GPU matrix should only follow if that build/selftest succeeds.
