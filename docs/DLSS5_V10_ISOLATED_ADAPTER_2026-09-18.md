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

Payloads are bounded to 64 MiB.

Reserved commands:

- HELLO
- CREATE
- FRAME
- OUTPUT
- CLOSE
- ERROR

The protocol is transport scaffolding only. It does not yet define a native
frame-memory implementation.

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
