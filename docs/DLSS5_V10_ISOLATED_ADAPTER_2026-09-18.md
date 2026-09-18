# DLSS5 v10 Isolated Adapter Contract — 2026-09-18

This milestone defines the process boundary for a future Visual Enhancer v10
Feature-18 adapter. It does **not** load or execute the v10 runtime.

## Why a separate host

The validated v3 backend and Visual Enhancer v10 have materially different
runtime contracts:

- v3 uses the existing approved RenoDX/ReShade-style worker/runtime bundle;
- v10 exposes a dedicated ABI-6 Neural Rendering bridge;
- v10 treats D3D12/NGX state as process-lifetime state and deliberately avoids
  normal NGX shutdown/module unload after successful Feature-18 evaluation.

The v10 path therefore must not be implemented as a small extension of
`src/backends/dlss5.py`.

## Static parent-side gate

`src/backends/dlss5_v10_adapter.py` resolves the managed candidate directory
and calls the fail-closed v10 static inspector.

A host plan is produced only when:

- the three exact pinned DLL identities match;
- the binaries are x86-64;
- the complete project-required ABI-6 export surface is present;
- no configured static-review condition blocks the candidate.

The resulting `V10HostPlan` records:

- bridge DLL;
- caller shim;
- NVIDIA Neural Rendering runtime;
- exact expected hashes;
- isolated Python module;
- protocol version.

`execution_allowed` is hard-coded false.

The public `launch_host()` entry point raises `V10ExecutionDisabled`.

## Host process scaffold

`src/backends/dlss5_v10_host.py` is intentionally non-executing.

Current supported operation:

```powershell
python -m src.backends.dlss5_v10_host --contract-selftest
```

It validates the static Python ABI/protocol definitions and reports:

- `native_loaded=false`;
- `execution_allowed=false`;
- protocol identity;
- ABI version;
- struct sizes;
- required exports;
- expected file hashes.

`--serve` currently exits with a blocked status and contains no
`ctypes.CDLL`, `WinDLL`, or `LoadLibrary` implementation.

## Protocol

`src/backends/dlss5_v10_protocol.py` defines protocol version 1.

Header:

```text
<4sHHII
magic        = "NR10"
version      = 1
command      = uint16
request_id   = uint32
payload_size = uint32
```

Payloads are bounded to 128 MiB. This is large enough for the upstream
7680×4320 RGBA8 boundary (126.6 MiB plus protocol metadata) while remaining a
hard transport cap.

Reserved commands:

- HELLO
- CREATE
- FRAME
- OUTPUT
- CLOSE
- ERROR

The protocol is transport scaffolding only. It does not yet define a native
frame-memory implementation.

## Protocol v1 payload contract

The first protocol generation is intentionally narrow: **host-memory RGBA8
only**. CUDA/NV12/P010 transport remains outside this milestone even though the
upstream bridge ABI can represent those formats.

CREATE is a canonical JSON object containing:

- input width and height;
- one exact upstream processing scale:
  `0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0`;
- style `0/1/2` = Default/Natural/Cinematic;
- ABI-6 Neural Rendering controls:
  intensity, NR passes, tone, structure, skin, color strength, tone
  preservation, face/skin protection, grain preservation, shimmer suppression;
- automatic-mask and NVOF-preference flags;
- literal transport declarations `memory_type=host` and
  `pixel_format=rgba8`.

The control limits are copied from the pinned upstream v10 validation logic:

- intensity/tone/structure: 0..2;
- skin structure: -1..2;
- color/tone-preservation/face-protection/grain/shimmer: 0..1;
- NR passes: integer 1..4.

Output geometry uses upstream's nearest-even rule after Lanczos pre-resize and
must remain at least 64×64 and within the 7680×4320 long/short-edge boundary.

FRAME payload is binary:

```text
int64 timestamp
uint8 reset
7 bytes reserved
width * height * 4 bytes tightly-packed RGBA8
```

OUTPUT payload begins with:

```text
uint32 width
uint32 height
int64  timestamp
int32  ngx_create_result
int32  ngx_evaluate_result
int32  cuda_result
int32  scene_reset
float  scene_score
uint64 upload_bytes
uint64 download_bytes
```

and is followed by exactly `width * height * 4` RGBA8 bytes.

This retains the Feature-18 result codes needed to distinguish successful
Neural Rendering from fallback/error behavior.

## Request ordering and poison semantics

The child HELLO message reserves request ID 0. Parent requests begin at 1:

1. exactly one CREATE;
2. zero or more consecutive FRAME requests;
3. one CLOSE.

Request IDs must be strictly consecutive. CREATE after CREATE, FRAME before
CREATE, repeated CLOSE, skipped IDs, truncated messages, invalid reset flags,
unknown commands, and payloads above the 64 MiB protocol limit are rejected.

Any future native timeout or native/ABI error poisons the process session.
After poison, no additional CREATE/FRAME request may be accepted. CLOSE remains
available as a terminal parent-side protocol action, after which the parent owns
process termination if the child fails to exit within the bounded grace period.

Current constants are deliberately conservative:

- host start timeout: 15 s;
- frame timeout: 30 s;
- close grace: 1 s.

These are contract values only at this milestone; the host still cannot execute
a v10 DLL.

## Non-native subprocess integration test

`src/backends/dlss5_v10_client.py` now exercises the real parent/child pipe
transport against an explicit `--protocol-selftest-server` mode in the host.

That simulator:

- reports `native_loaded=false` and `execution_allowed=false` in HELLO;
- validates the same CREATE/FRAME/CLOSE schemas and request ordering;
- supports only 1.0x FRAME echoing, so it cannot be mistaken for a resizing or
  Neural Rendering implementation;
- returns `-2147483648` for NGX create/evaluate/CUDA result fields as a
  reserved simulation sentinel;
- never loads a v10 DLL.

The parent supervisor uses real subprocess pipes and implements:

- 15 s bounded startup;
- 30 s bounded request round-trip;
- strict response request-ID matching;
- session poisoning on timeout/protocol/host error;
- owned-process termination after poison;
- 1 s bounded close grace.

The normal `start()` method remains blocked with `V10ExecutionDisabled`;
only `start_protocol_selftest()` can spawn a process at this milestone.

## Offline native-loader review

The pinned upstream v10 implementation loads the bridge with Windows
`WinDLL`, binds the ABI surface, calls `dlss5nr_version()` and
`dlss5nr_frame_abi_version()`, and rejects a frame ABI other than 6 before
initialization.

`src/backends/dlss5_v10_native.py` now mirrors that binding plan without being
connected to the host:

- exact runtime static identity is rechecked immediately before any load;
- native loading is disabled by default and raises
  `V10NativeLoadDisabled`;
- `allow_native_load=True` is required even to reach the loader;
- the ABI-6 required function signatures are bound explicitly;
- runtime frame ABI is checked again after load;
- optional `dlss5nr_release_session` is bound if present;
- no NGX shutdown/unload routine is part of the isolated-host lifecycle plan.

The module is covered with fake-library tests. The production host currently
does not import `dlss5_v10_native` and does not reference `load_bridge`.

This gives us reviewed loader source without creating a reachable native
execution path yet.

## Intended execution architecture

The later execution milestone should keep all of these inside one owned child:

1. load the exact pinned v10 bridge/caller/NVIDIA DLL set;
2. verify runtime ABI version 6 again at runtime;
3. create Feature-18 state;
4. process bounded frames;
5. retain NGX/driver modules for the lifetime of that child;
6. terminate the owned child rather than requiring unsafe NGX global teardown.

The parent process should own:

- timeout;
- process-tree termination;
- frame/request ordering;
- payload bounds;
- exact runtime identity;
- evidence capture.

This mirrors the project's existing use of supervised native helpers while
preserving v10's distinct lifecycle.

## Next gate before native execution

Before implementing the native-load portion:

1. define exact CREATE/FRAME payload schemas;
2. define RGBA8 host-memory frame limits and output geometry rules;
3. define error/result evidence fields, including NGX create/evaluate codes;
4. define timeout/poison semantics;
5. unit-test all protocol framing and malformed-message behavior;
6. perform an offline source review of the loader implementation.

Only then should the host gain a native-load code path, and that path should
remain opt-in for a bounded 256x256, one-frame, 1.0x RTX 3070 Ti validation.
