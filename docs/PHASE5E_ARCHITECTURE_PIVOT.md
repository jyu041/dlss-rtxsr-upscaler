# Phase 5E — MFG architecture pivot

The Phase 5D result is **direct-host compatibility not established**, not
proof that current 0.3.1 cannot work on RTX 30-series.

## Two different contracts

The validated legacy path is:

```text
C55 standalone host → community DLL presents the direct NGX feature ABI
```

The current 0.3.1 upstream path is a proxy deployment:

```text
application / Streamline → normal NGX/Streamline calls → proxy → embedded factory runtime
```

The pinned upstream source commit is
`117faf5c70333b34160f5d21d01c222261cc5af1`. Its proxy architecture is not a
drop-in replacement for the C55 direct-host ABI. The observed C55 result
(`FRAME_GENERATION_AVAILABLE=0`, missing MFG capability parameters, and pipe
closure before HELLO) is therefore recorded as an architecture mismatch.

## Minimum current-generation contract

The accepted RTX 3070 Ti Streamline evidence is recorded in
`docs/PHASE5C_ACTIVATION_REPORT.md` and `docs/PHASE5D_WORKING_CONTRACT.md`.
It requires D3D12, a Streamline-managed DXGI swapchain and Present boundary,
the DLSS-G plugin, Reflex/PCL initialization, and the community donor/proxy
path. The public Streamline DLSS-G API does not provide a post-generation
intermediate-frame readback interface. A hidden/minimized swapchain may be a
future host design, but it is not yet a proven offline capture contract.

Accordingly no speculative C60 host, swapchain hook, or generated-output
claim was added. C55 remains the validated legacy backend; 0.3.1 remains a
separate current-proxy candidate requiring a purpose-built Streamline host.

## Provider baseline

The local provider component uses only the official NVIDIA-RTX/Streamline
v2.14.1 release archive and selectively extracts the release `nvngx_dlssg.dll`
plus its license notice. Streamline interposer, common, Reflex, and PCL
binaries are not copied into the legacy C55 runtime merely because a normal
Streamline application may use them; each belongs to a future versioned host
boundary with its own identity and license review.
