# Development setup

The normal source-checkout workflow is also suitable for contributors:

```powershell
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
.\setup.bat
.\start.bat
```

`setup.bat` creates/updates the dedicated Conda environment and provisions the
normal managed backend runtime set from pinned public sources. `start.bat`
uses the saved source environment and launches through the exact Conda
executable remembered by setup.

`tools/start-dev.bat` remains available as a developer-only source launcher.

For isolated development or validation, `NVE_CONDA_ENV` may name a separate
Conda environment, or `NVE_CONDA_PREFIX` may point at an existing environment
prefix. These overrides are not required for normal users.

## Managed runtime locations

Normal source setup uses:

```text
runtime/dlssg/worker/dlssg_sm86_offline.exe
runtime/dlssg/grid4-worker/dlssg_sm86_offline.exe
runtime/dlssg/legacy/version.dll
runtime/dlssg/legacy/dlssg_sm86.ini
runtime/dlssg/official/
runtime/dlss-sr-host/
```

The `legacy` name is retained for identity compatibility; it is the validated
normal C55 direct-host profile. The newer `candidate-0.3.1` proxy-generation
runtime remains available through Runtime Manager for explicit research.

Advanced `DLSSG_*` environment overrides are retained for development and
validation, but the normal UI intentionally does not ask users to enter runtime
paths.

DLSS 5 v3 and v10 retain separate explicit approval/preflight boundaries; do
not bypass those gates during ordinary development.

## Tests

Ordinary CPU/CI coverage uses `tools/requirements/ci.txt` and the explicit
`tests/` directory. Hardware validation uses the dedicated project environment
and opt-in tools/gates documented in `TESTING.md`.

Generated working directories such as `runtime/`, `temp/`, `logs/`,
`outputs/`, and `inputs/` are intentionally not source-tracked. The
application/setup flow creates what it needs on demand.

## Native builds

Developers rebuilding project native components need the appropriate Visual
Studio C++ toolchain and separately staged NVIDIA SDK headers/libraries. Normal
users do not need those SDKs because setup provisions the validated project
binaries.

Do not copy proprietary SDK inputs, test media, generated outputs, local
settings, credentials, or other private/restricted artifacts into the
repository.

## Deferred portable work

The repository retains experimental portable-packaging infrastructure, but a
no-Conda distribution is deliberately outside the current project completion
criteria. Do not treat portable-runtime reconstruction as a prerequisite for
source-based releases unless that product direction is explicitly resumed.
