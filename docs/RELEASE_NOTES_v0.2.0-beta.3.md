# NVIDIA Video Enhancer v0.2.0-beta.3

This is the public-launch source beta. It keeps the unified DLSS 5 / DLSS-G /
DLSS SR functionality from beta.2, incorporates the final setup hardening found
during the release audit, and improves the repository landing experience for
new users.

## Recommended installation

Prerequisites are Windows 10/11 x64, a compatible NVIDIA RTX GPU/driver, Git,
Miniconda/Anaconda, FFmpeg/FFprobe with both H.264 and HEVC NVENC, and the
Microsoft Visual C++ 2015-2022 Redistributable x64.

From PowerShell:

```powershell
git clone --branch v0.2.0-beta.3 --recurse-submodules https://github.com/jyu041/dlss-rtxsr-upscaler.git
cd dlss-rtxsr-upscaler
.\setup.bat
.\start.bat
```

Use this recursive clone path rather than GitHub's automatically generated
**Source code (zip/tar.gz)** downloads, which do not populate the pinned
submodule and are not the validated beta.3 install artifact.

During setup, DLSS 5 remains a single explicit opt-in:

```text
Enable DLSS 5 now? [Y/N]
```

Choosing Yes downloads or reuses the exact pinned v10 archive, verifies it,
stages only the allowlisted runtime payload, runs the Microsoft Defender
preflight, and verifies application readiness.

The release remains a source-install beta rather than a no-Conda portable
bundle.

## Changes since v0.2.0-beta.2

### Setup hardening

- Setup now checks `h264_nvenc` and `hevc_nvenc` independently. A partial
  FFmpeg build can no longer pass the prerequisite gate merely because one of
  the two required encoders is present.
- Regression coverage protects the two-encoder requirement.
- The fresh-source acceptance path continues to exercise the intended
  `clone -> setup.bat -> start.bat` workflow.

### Repository maintenance

- Merged-branch pruning now runs automatically after merged pull requests.
- Cleanup remains guarded against deleting the default branch or branches with
  open pull requests.
- The public launch leaves `main` as the only active repository branch after
  cleanup.

### Project presentation

- The README now opens with a compact visual overview of the local enhancement
  pipeline.
- The landing page highlights the four user-facing paths: RTX VSR, DLSS SR,
  DLSS Frame Generation / MFG, and experimental DLSS 5 Neural Rendering.
- The normal installation contract and experimental boundaries remain explicit.

## Validation

The release-audit patch was validated on GitHub Actions with:

- **528 passed, 3 skipped** in the ordinary test suite;
- public bootstrap-release verification passing;
- the fresh source-install acceptance workflow passing through setup and local
  UI launch; and
- merged-branch cleanup completing successfully.

Primary hardware evidence remains Windows 11 on an NVIDIA GeForce RTX 3070 Ti
8 GB. Beta.3 does not broaden the hardware claims from beta.2; it packages the
already validated application state with the final setup and launch-readiness
cleanup.

## Known limitations

- The main video pipeline remains SDR-focused.
- DLSS SR receives estimated optical-flow guidance rather than renderer motion
  vectors, depth, or jitter.
- C55/grid1 remains the validated DLSS-G default; grid4 remains experimental.
- DLSS 5 may materially reinterpret semantic image content.
- The preferred DLSS 5 v10 path remains restricted to 1.0x output and the
  existing 1920x1080-equivalent native-input validation boundary.
- Broader RTX 30/40/50 GPU and driver coverage remains future validation work.
- A no-Conda portable distribution remains deliberately deferred.

## Documentation

- [Installation](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.3/docs/INSTALL.md)
- [Project status](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.3/docs/PROJECT_STATUS.md)
- [Testing](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.3/docs/TESTING.md)
- [Security audit](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.3/docs/SECURITY_AUDIT.md)
- [DLSS 5 approval](https://github.com/jyu041/dlss-rtxsr-upscaler/blob/v0.2.0-beta.3/docs/DLSS5_APPROVAL.md)

Project-owned source remains MIT licensed. Third-party components and NVIDIA or
other proprietary runtimes retain their own terms. No NVIDIA endorsement is
implied.
