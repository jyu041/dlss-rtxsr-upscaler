# Phase 5 MFG runtime refresh audit

Audit date: 2026-09-16

## Runtime identities

| Component | Identity |
|---|---|
| Current public `sdli1995/dlssg_for_sm86` source | `117faf5c70333b34160f5d21d01c222261cc5af1` (`0.3.1`) |
| Exact 0.3.1 root `version.dll` | 29,676,832 bytes; `3D4C7D537A6E71E3A9D41FFC6487E054B26C56D27B7C0825D39EAA7EF0C7E86D` |
| Exact 0.3.1 root `dlssg_sm86.ini` | 2,727 bytes; `231574047C4989D292E592802102D2437FC636B56E535E8D70D403F20D4CCAFC` |
| Exact 0.3.1 root notice | 3,349 bytes; `AC3B44AB30A4235EDD18FECA1AB4F802D57C8D3D0EE4878DC77B81A6B127155F` |
| Legacy `version.dll` | 15,667,520 bytes; `C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2` |
| Legacy `dlssg_sm86.ini` | 581 bytes; `FD7F0722194E6E8D8C085327D9826EFFB411925A69A5E7549D70EFF26A9F18B5` |
| Frozen C55 worker | `C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916` |
| Official provider used by accepted direct-host evidence | `FF6E90EB78B827927DFF5B4ECC6B1C870C2E9BCA29ED9F48C7D348CC9E170B82` |

The exact 0.3.1 root files are the proxy/runtime generation described by the
upstream release as the 310.9 path. Windows `FileVersionInfo` returned blank PE
version fields. Authenticode reported `UnknownError` because the self-signed
`DLSSG for SM86` certificate chain is not trusted; the certificate thumbprint
was `85BA66762F851E49148D706915D09026281418E6`. The public runtime is external and GPL-adjacent at the repository/source level,
with separate NVIDIA/third-party binary material. No source or binary from it
is copied into this MIT project.

## 5X/6X protocol audit

The current implementation was inspected end to end:

- native `CREATE` accepts `generatedCount` only from 1 through 3;
- the native worker returns `maximumGeneratedFrames` as a capability value,
  but rejects a requested count above the compiled bound of 3;
- the Python client accepts multipliers only `(2, 3, 4)` and parses only 1, 2,
  or 3 generated outputs;
- video output counting, terminal-frame policy, and UI choices are all
  explicitly built around 2X/3X/4X.

The upstream README describes a higher `MaxGeneratedFrames` ceiling as a
runtime/game-dependent possibility. That statement is not proof that the
frozen C55 worker, its D3D12 allocations, its protocol, or this offline video
architecture can safely use 5X/6X. No 5X/6X control is therefore exposed.

## Compatibility status

The preserved Phase 5R evidence proves one successful 2X direct-host Evaluate
path with the validated legacy runtime on the RTX 3070 Ti. It does not prove that
the private C55 worker accepts the candidate runtime. A new C55 compatibility
probe was not executed because the local safety gate refused execution of the
unsigned third-party candidate DLL; no workaround was attempted. The frozen
C55 worker and all private resources remain unchanged.

Consequently, the current supported MFG contract remains 2X/3X/4X through the
validated C55 path. A future 5X/6X implementation requires a separately
versioned worker/protocol, complete output-order/count tests, synthetic-video
integration, cancellation/teardown validation, and explicit runtime evidence.

The refreshed candidate is selectable only through the explicit
`DLSSG_RUNTIME_PROFILE=candidate-0.3.1` profile after a hash-verified runtime
installation. The INI is proxy configuration and is retained beside the DLL;
its independent effect on this offline worker was not isolated. The default
remains the preserved legacy path. Selection does not imply C55 compatibility or
native validation, and a candidate cannot be used for native rendering without
a current compatibility attestation.
