# Development setup

The normal source-checkout workflow is also suitable for contributors:

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

`setup.bat` creates/updates the dedicated Conda environment and provisions the
normal managed backend runtime set from pinned public sources. `start.bat`
detects whether it is running from a complete portable package; otherwise it
loads the saved source environment and launches through Conda.

`start-dev.bat` remains available as a developer-only launcher when you want to
explicitly launch the Conda environment without the portable-runtime detection
performed by `start.bat`.

For isolated development or validation, `NVE_CONDA_ENV` may name a separate
Conda environment, or `NVE_CONDA_PREFIX` may point at an existing environment
prefix. These overrides are not required for normal users.

The managed DLSS-G source defaults are:

```text
runtime/dlssg/worker/dlssg_sm86_offline.exe
runtime/dlssg/candidate-0.3.1/version.dll
runtime/dlssg/official/
```

Advanced `DLSSG_*` environment overrides are retained for compatibility and
research, but the normal UI intentionally does not ask users to enter runtime
paths.

The portable builder still requires explicit validated runtime directories for
the dependency-bearing Python environment and FFmpeg. Do not copy proprietary
NVIDIA SDK inputs, test media, generated outputs, local settings, credentials,
or other restricted/private artifacts into the repository.

Run ordinary tests with `requirements-ci.txt`; hardware-specific validation uses
the separate project environment and explicit opt-in gates.
