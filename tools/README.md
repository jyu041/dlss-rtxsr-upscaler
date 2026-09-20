# Tooling Guide

The normal user workflow is still:

```text
setup.bat
start.bat
```

Files in `tools/` are primarily maintainer, validation, or research utilities.
A normal user should not need to run them.

## Current maintenance and readiness tools

- `manage_runtime.py` — manifest-driven runtime inventory and explicit
  install/update/verify/repair/remove/import actions.
- `check_rtx_vsr_readiness.py` — RTX VSR readiness diagnostics.
- `check_dlss_sr_readiness.py` — DLSS SR readiness/self-test entry point.
- `check_dlssg_readiness.py` — DLSS-G managed-runtime/readiness diagnostics.
- `provision_dlss5_v3.py` — explicit pinned DLSS 5 v3 provisioning and
  security validation.
- `prepare_dlss5_v10_candidate.py` / `audit_dlss5_v10.ps1` — explicit v10
  candidate staging/static preflight used by the Configuration workflow.
- `start-dev.bat` — developer source launcher using the remembered Conda
  environment.

## Hardware validation and research

The `run_*`, `validate_*`, `capture_*`, `score_*`, benchmark, soak, and
synthetic-input tools are retained for reproducible backend validation. They
are not part of ordinary installation.

Important current hardware gates include:

- `run_dlss5_v10_app_smoke.ps1`
- `run_dlssg_grid4_managed_candidate.ps1`
- `run_mfg_grid_quality_ab.ps1`
- `validate_dlssg_candidate.py`
- `benchmark_dlss5_quality.py` / `benchmark_dlss5_v10_quality.py` — bounded real-video DLSS5 quality/performance matrices.
- `benchmark_dlssg_grid4_matrix.py` — C55/grid1 versus managed grid4 2X/3X/4X hardware matrix.
- `validate_dlssg_recreation_soak.py` — repeated fresh-process DLSS-G feature-creation determinism gate.
- `audit_dlssg_sm86_035.py` — static-only identity/configuration audit for the incompatible upstream 0.3.5 proxy candidate; never executes it.

See `../docs/TESTING.md` and the dated hardware-evidence documents before
running those gates.

## Deferred portable-distribution research

No-Conda portable distribution work is deliberately deferred. The following
files remain for future research/reproducibility and are not current release
requirements:

- `assemble_portable_runtime.py`
- `build_portable_candidate.py` / `build_portable_candidate.ps1`
- `check_portable_runtime.py`
- `generate_portable_lock.py`
- `repair_portable.ps1`
- `portable_runtime_lock.json`
- `portable_toolchain.json`

See `../docs/PORTABLE_RUNTIME_DECISION.md` for the current decision.

## Historical release tooling

Version-specific tooling for already-published releases lives under
`history/`. Those files are retained for audit/reproducibility only and must
not be treated as generic current release builders.

## Requirements

Maintainer dependency sets are grouped under `requirements/`:

- `ci.txt` — ordinary hosted CI.
- `runtime.txt` — application runtime dependency set.
- `test.txt` — runtime + pytest.
- `dev.txt` — test dependencies + maintainer audit tooling.
