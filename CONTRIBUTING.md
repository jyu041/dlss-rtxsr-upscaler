# Contributing

Contributions, bug reports, testing results, and documentation improvements are welcome.

## Before You Start

This is an unofficial community project. NVIDIA, proprietary, and community runtime binaries are not distributed here. Do not commit or attach proprietary runtimes, SDK archives, model files, private media, credentials, or other restricted binaries. Hardware-specific behavior can vary by GPU, driver, and runtime.

## Development Setup

```bat
git clone --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
setup.bat
start.bat
```

See [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/TESTING.md`](docs/TESTING.md), [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md), and [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) before making backend or runtime-related changes.

## Making Changes

- Create a focused branch and keep the change scoped.
- Avoid unrelated refactors.
- Preserve fail-closed backend behavior and never silently substitute one backend for another.
- Do not add silent runtime or model downloads.
- Do not commit generated media or local runtime files.

## Testing

```powershell
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pytest
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
```

Hardware-dependent tests may skip when the required local runtime is unavailable. A skipped hardware test must not be presented as successful hardware validation.

## Pull Requests

Include what changed, why, affected backend(s), tests performed, and tested GPU/driver/runtime details where relevant. Include screenshots for UI changes when useful. Keep pull requests reasonably small.

## Runtime and Binary Policy

Do not commit `*.dll`, `*.exe`, SDK archives, model weights, runtime packages, or test/source media that cannot be redistributed. See [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md) and [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md).

## Reporting Security Issues

Do not post credentials, private runtime files, or other sensitive material in issues. This repository does not currently have a dedicated private vulnerability reporting channel; redact sensitive details and use the least-public disclosure available to you.
