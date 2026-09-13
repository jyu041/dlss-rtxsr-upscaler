# Phase 4A — community MFG reference harness

This is a new standalone command-line path. It intentionally does not reuse
the Phase 3 worker protocol, stdin streaming, parent/child pipes, JSON request
loops, or `native/dlssg_ampere_experiment` runtime architecture.

`reference_core.hpp` adapts the small, pure Ampere/provider contract from
`nefh/MFGAmpereUnlock-RenoDx`, MIT, commit
`c88b208e3f8f12e86a261f06aef1da3a77adef27`. Attribution is retained here and
in the Phase 4A report. No NVIDIA or community binary is distributed or run.

The executable contract is:

```text
dlssg_ampere_reference.exe --selftest
dlssg_ampere_reference.exe --run-2x <provider>
```

The current source deliberately fails closed for live mode until the host is
compiled with the NVIDIA NGX SDK and the donor-derived in-memory provider
publication is wired into the minimal D3D12 path. `--selftest` remains GPU- and
DLL-free. Runtime artifacts belong under `runtime/` and are gitignored.
