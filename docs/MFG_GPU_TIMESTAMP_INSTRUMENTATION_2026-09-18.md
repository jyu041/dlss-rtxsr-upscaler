# MFG GPU Timestamp Instrumentation — 2026-09-18

This branch adds diagnostic-only D3D12 timestamp queries to the source of the
C55 native DLSS-G worker while preserving protocol v4 and the currently pinned
validated worker binary.

## Safety boundary

The instrumentation is enabled only when the worker is started with
`DLSSG_WORKER_DIAGNOSTIC=1`, which is already the existing diagnostic mode.

It does **not**:

- change `worker_protocol.h`;
- enlarge `ProcessResponse`;
- change the production default profile;
- replace the pinned C55 executable;
- enable concurrency or reorder GPU commands;
- change DLSS-G resources, options, output ordering, or fence behavior.

The currently distributed validated worker therefore remains byte-for-byte
unchanged until a separately built instrumented worker is deliberately used for
measurement.

## Direct-queue timestamp layout

The diagnostic worker creates one D3D12 timestamp query heap and a readback
buffer. For each generated group it records timestamps on the existing direct
command list around:

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

`dlssg_evaluate` and `output_copy` use generated index 1..3. Group/input
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

They do **not** yet measure NVIDIA Optical Flow GPU execution directly.

NVOF is driven through the NVIDIA Optical Flow API and has its own execution
boundary. Existing `nvof_upload_ms`, `nvof_execute_ms`, and
`flow_conversion_ms` remain CPU/API/wait-attributed timings. A separate NVOF
GPU-timestamp design is required before claiming actual NVOF GPU execution
duration.

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
