# Testing

Run deterministic tests explicitly against the repository test directory:

```powershell
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pytest
conda run --no-capture-output -n dlss-rtxsr-upscaler python -m pip check
```

The ordinary suite covers paths, configuration, media helpers, progress,
monitoring, UI behavior, cancellation, presets, and backend non-fallback
behavior. Hardware tests are explicit and may be skipped when the relevant
local runtime is absent. A skipped hardware test is not a successful backend
validation.

Backend validation classes:

- RTX VSR: NVIDIA VFX installation and GPU smoke tests.
- DLSS SR: native D3D12 host, approved NGX hash, and Quality self-test.
- DLSS5: user-approved runtime, firewall check, protocol test, and signed
  Feature-18 evidence.

Use synthetic or owned media. Do not run unrestricted recursive pytest
discovery when an extracted local runtime tree exists; target `tests`
explicitly.
