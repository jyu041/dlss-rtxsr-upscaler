# NVIDIA Video Enhancer v0.2.0-beta.2

This beta consolidates the project's DLSS 5 work into one user-facing mode and
makes the validated source-install workflow substantially simpler for new users.

## Recommended installation

Prerequisites remain Windows 10/11 x64, a compatible NVIDIA RTX GPU/driver,
Git, Miniconda/Anaconda, FFmpeg/FFprobe with H.264 + HEVC NVENC, and the
Microsoft Visual C++ 2015-2022 Redistributable x64.

From PowerShell:

```powershell
git clone --branch v0.2.0-beta.2 --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
.\setup.bat
.\start.bat
```

During setup, DLSS 5 is a single explicit opt-in:

```text
Enable DLSS 5 now? [Y/N]
```

Choosing Yes downloads or reuses the exact pinned v10 archive, verifies it,
extracts only the allowlisted runtime payload, runs the Microsoft Defender
preflight, stages the runtime, and verifies application readiness. No manual
DLL copying, runtime-path entry, v3 provisioning, or separate Configuration
preflight is required for normal use.

The release intentionally remains a source-install beta rather than a no-Conda
portable bundle.

## Major changes since v0.2.0-beta.1

### Unified DLSS 5

- The separate **DLSS 5 v3** and **DLSS 5 v10 Experimental** choices are
  replaced by one **DLSS 5** mode.
- The isolated v10 application runtime is the preferred implementation.
- The older v3 implementation remains only as an internal compatibility path
  for existing/manual legacy installations.
- The UI reports when a compatibility fallback is used instead of silently
  hiding the runtime selection.

### DLSS 5 v10 quality/performance pipeline

The preferred v10 path now includes the application-level controls that were
previously available only around v3:

- Auto / 100 / 87.5 / 75 / 67 / 50% neural working resolution;
- residual recomposition back onto the native-resolution source;
- CUDA-preferred or CPU recomposition;
- optional motion-compensated temporal residual stabilization;
- shared neural color-strength and tone-preservation controls.

The existing v10-native controls remain available:

- 1-4 neural passes;
- face/skin protection;
- grain preservation;
- native shimmer suppression;
- optional NVOF preference.

One pass remains the conservative default. Higher pass counts are treated as
stronger enhancement levels, not as a simple quality ranking.

### DLSS 5 setup and repair

- `setup.bat` now provisions the preferred pinned v10 runtime directly after
  one explicit DLSS 5 opt-in.
- The exact verified v10 ZIP is retained under
  `runtime/downloads/Visual.Enhancer.v10.0.zip`.
- Expired/missing local Defender-preflight evidence can be refreshed from that
  verified cache without another ~690 MB download.
- Configuration now exposes one **Install / Repair DLSS 5** recovery action.
- Normal onboarding no longer depends on the obsolete v3 archive URL.

### DLSS-G / Multi Frame Generation

- Validated C55/grid1 remains the default DLSS-G path.
- The grid4/GPU-resident NVOF candidate remains available as an explicit
  experimental performance option.
- RTX 3070 Ti matrix and recreation-soak testing covered 2X/3X/4X for both
  validated C55 and grid4.
- Grid4 showed materially lower native processing time, but the default was not
  changed because subjective review slightly favored the validated output.

### Video/output reliability

- DLSS 5 v10 H.264 output now explicitly uses SDR `yuv420p` for broader player
  compatibility.
- Decode/processing/encode timing was split more clearly, including
  steady-state v10 processing FPS instead of conflating setup overhead with
  frame throughput.
- Frame transport uses reusable buffers to reduce Python allocation/copy churn.

## Validation

Primary hardware evidence remains Windows 11 on an NVIDIA GeForce RTX 3070 Ti
8 GB.

The unified v10 migration was tested with the existing 640x480 owned clip. The
new reduced-resolution cases completed successfully with CUDA recomposition:

- 100% baseline: about 23.28 processing FPS;
- 75% working resolution: about 25.83 processing FPS;
- 66.7% working resolution: about 27.55 processing FPS;
- 75% + temporal stabilization 0.5: about 16.83 processing FPS;
- 4-pass native: about 9.93 processing FPS;
- 4-pass at 75%: about 11.90 processing FPS.

On that source, 75% and 66.7% retained quality metrics close to native-resolution
v10 while improving steady-state throughput. The CPU optical-flow temporal
stabilizer reduced the residual-flicker metric but currently carries a
substantial performance cost.

The clean-install acceptance run also verified the intended new-user sequence:

```text
clone -> setup.bat -> Enable DLSS 5: Y -> start.bat -> DLSS 5 READY
```

Hardware evidence is recorded in:

- `docs/DLSS5_UNIFIED_V10_HARDWARE_2026-09-21.md`;
- `docs/DLSS5_V10_APP_HARDWARE_2026-09-19.md`;
- `docs/MFG_GRID4_MANAGED_WORKER_HARDWARE_2026-09-19.md`;
- `docs/DLSS5_MFG_QUALITY_PERFORMANCE_2026-09-20.md`.

## Known limitations

- The main video pipeline remains SDR-focused.
- DLSS SR receives estimated optical-flow guidance rather than renderer motion
  vectors, depth, or jitter.
- C55/grid1 remains the validated DLSS-G default; grid4 remains experimental.
- DLSS 5 may materially reinterpret semantic image content.
- The preferred v10 path remains restricted to 1.0x output and the existing
  1920x1080-equivalent native-input validation boundary.
- Reduced neural working resolution changes internal workload, not final output
  dimensions or the validated input boundary.
- The current temporal residual stabilizer is CPU-heavy and is a future
  GPU-optimization target.
- Broader RTX 30/40/50 GPU/driver coverage remains future validation work.
- A no-Conda portable distribution remains deliberately deferred.

## Documentation

- [Installation](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/INSTALL.md)
- [Project status](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/PROJECT_STATUS.md)
- [Testing](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/TESTING.md)
- [Security audit](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/SECURITY_AUDIT.md)
- [DLSS 5 approval](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/DLSS5_APPROVAL.md)
- [Unified DLSS 5 hardware evidence](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.2/docs/DLSS5_UNIFIED_V10_HARDWARE_2026-09-21.md)

Project-owned source remains MIT licensed. Third-party components and NVIDIA or
other proprietary runtimes retain their own terms. No NVIDIA endorsement is
implied.
