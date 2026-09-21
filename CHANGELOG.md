# Changelog

This file is a concise release index. Detailed validation evidence and
engineering history remain under `docs/`.

## v0.2.0-beta.2 — 2026-09-21

- replace the separate DLSS 5 v3/v10 user modes with one **DLSS 5** mode;
- simplify fresh-install DLSS 5 onboarding to one setup opt-in that provisions the preferred pinned v10 runtime directly, with a single Configuration repair action and local cached preflight refresh;
- prefer the isolated v10 application runtime automatically after its explicit
  preflight, with v3 retained only as an internal compatibility fallback;
- extend the v10 video path with Auto/100/87.5/75/67/50% neural working
  resolution, residual recomposition, CUDA/CPU recomposition selection, and
  optional temporal residual stabilization;
- keep v10 1-pass and validated C55 MFG defaults unchanged while retaining
  stronger neural-pass and experimental grid4 options for explicit use.

See `docs/RELEASE_NOTES_v0.2.0-beta.2.md`.

## v0.2.0-beta.1 — 2026-09-20

Current source-install beta.

Highlights:

- validated recursive clone → `setup.bat` → `start.bat` onboarding;
- managed C55 and grid4 DLSS-G runtime paths;
- managed standalone DLSS SR host/runtime;
- optional security-gated DLSS 5 v3 provisioning;
- integrated isolated DLSS 5 v10 Experimental application path;
- Enhance / Configuration / Diagnostics frontend overhaul;
- Runtime Manager integration;
- repository, documentation, and CI cleanup.

See `docs/RELEASE_NOTES_v0.2.0-beta.1.md` and the
[v0.2.0-beta.1 GitHub prerelease](https://github.com/jyu041/dlss-rtxsr-upscaler/releases/tag/v0.2.0-beta.1).

## v0.1.0-beta.2 — 2026-09-16

Historical prebuilt beta centered on RTX VSR, standalone DLSS SR, and the
validated C55 worker.

See `docs/RELEASE_NOTES_v0.1.0-beta.2.md`.

## Earlier work

Pre-beta and Phase 4/5 engineering history is preserved in the repository's
dated and phase-named documents. Those reports are historical evidence, not
current operational requirements.
