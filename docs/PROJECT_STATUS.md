# Project Status

Last reviewed against unified DLSS 5 integration branch: 2026-09-21.

## Complete for the current source-based beta

The following are implemented, documented, and covered by ordinary CI,
hardware evidence, or the clean Windows source-install acceptance workflow as
appropriate:

- recursive Git clone → `setup.bat` → `start.bat` onboarding;
- dedicated Conda environment creation/update and remembered Conda executable;
- FFmpeg/FFprobe + NVENC prerequisite verification;
- manifest-driven managed runtime installation and identity verification;
- RTX VSR application path;
- DLSS SR standalone D3D12/NGX application path;
- validated C55/grid1 DLSS Frame Generation path;
- managed grid4/GPU-resident NVOF experimental profile;
- one user-facing DLSS 5 mode with automatic preferred-runtime selection;
- preferred v10 application path with pinned preflight, isolated host,
  process-tree/firewall containment, per-frame result checks, scene-aware
  resets, clean-close enforcement, reduced working-resolution recomposition,
  optional temporal residual stabilization, and 1–4 neural passes;
- retained v3 Feature-18 compatibility runtime with its existing hash, Defender,
  firewall, approval, and self-test gates, hidden from normal backend selection;
- task-first Enhance / Configuration / Diagnostics WebUI;
- repository-root cleanup and current README;
- ordinary test suite and clean source-install acceptance CI;
- current third-party/security documentation and release provenance for managed
  project components.

## Deliberately deferred

### No-Conda portable distribution

A standalone portable ZIP with its own Python/FFmpeg/runtime dependency set is
not part of the current project completion criteria. The validated user path is
the source install using Miniconda/Anaconda.

The existing portable-builder research is retained as historical/experimental
infrastructure. Resuming it later would require a separately validated
wheel/runtime lock, licensing/notices, reproducible assembly, and clean-machine
launch evidence.

## Work that requires additional hardware or subjective evaluation

These are not repository/CI tasks that can be completed purely from GitHub:

- broader GPU/driver coverage beyond the current RTX 3070 Ti evidence;
- independent validation on additional RTX 30/40/50 configurations;
- perceptual-quality comparison of experimental grid4 and DLSS 5 outputs across
  representative real-world content;
- performance tuning that depends on GPU traces or device-specific bottlenecks.

These are useful expansion tasks, but they do not block the current validated
source-based beta workflow.

## Optional engineering directions, not release blockers

- CPU/GPU overlap or additional pipeline pipelining for DLSS 5;
- removal of the retained v3 compatibility implementation after v10 has equivalent broader hardware coverage;
- further DLSS-G performance/quality research;
- additional automated GPU regression infrastructure on a trusted
  NVIDIA-equipped runner.

## Release state

[`v0.2.0-beta.1`](https://github.com/jyu041/dlss-rtxsr-upscaler/releases/tag/v0.2.0-beta.1)
is the current published source-install beta milestone. It is intended to be
used through the validated recursive clone → `setup.bat` → `start.bat`
workflow.

The release deliberately does **not** introduce a no-Conda portable bundle.
That direction remains deferred as described above.

The historical `v0.1.0-beta.2` prebuilt ZIP remains available, but it
predates managed grid4, the DLSS 5 v10 application path, the frontend
overhaul, hardened source onboarding, and repository cleanup.

See `RELEASE_NOTES_v0.2.0-beta.1.md` for the current release scope.
