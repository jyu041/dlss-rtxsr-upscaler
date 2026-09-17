# Security and Provenance

The application is a local utility. Its UI binds to localhost and does not
enable Gradio sharing. Backend selection is explicit and a failed backend does
not silently fall back to another processing method.

## Runtime rules

- Normal `setup.bat` may download supported runtime components automatically
  when a stable public HTTPS upstream source is available.
- Project-owned binaries are obtained from this project's public GitHub release.
  Third-party binaries are downloaded directly from their upstream projects;
  this repository does not re-host the external DLSS-G or DLSS 5 archives.
- Stable release digests and pinned file identities are verified automatically
  where available. These are implementation integrity checks, not manual user
  approval requirements.
- DLSS SR still performs its native functional self-test before being considered
  ready.
- DLSS 5 no longer requires a user-created approval manifest or a mandatory
  Windows Firewall rule. Its runtime must be structurally complete and must pass
  the local Feature-18 functional self-test for the exact installed runtime.
- The DLSS 5 backend continues to reject output when the runtime does not provide
  verified Feature-18 execution or falls back to the native/non-neural path.
- An outbound firewall block for the third-party DLSS 5 worker is optional. Its
  presence may be reported in diagnostics, but it is not a readiness gate.
- Do not commit proprietary/community runtime binaries, model weights, personal
  media, generated runtime state, or diagnostic logs to the source repository.

## Public references

The retained source submodule is
[Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer),
pinned to commit `796ed5927a202ba50b5c929cd08e16b365041162`.
Its protocol/session/settings/motion/diagnostic code is used as the client for
the compatible Visual Enhancer v3 runtime.

The standard DLSS-G production setup downloads the validated legacy SM86
runtime directly from the pinned upstream `sdli1995/dlssg_for_sm86` commit and
the official provider directly from NVIDIA's Streamline v2.14.1 release.
Neither external runtime is re-hosted by this project.

The DLSS 5 v3 runtime is downloaded directly from the upstream Merserk DLSS 5
Visual Enhancer 3.0 GitHub release. The setup helper validates the published
archive digest automatically and extracts only the runtime subtree into the
managed local runtime directory.

## Review guidance

When changing a pinned automatic download, reviewers should confirm the source
URL, version/commit, applicable license/terms, and any available published
digest. Functional self-tests remain the final readiness check for native GPU
backends. Malware-scan cleanliness and a matching hash are useful integrity
signals but do not, by themselves, establish vendor provenance, compatibility,
or redistribution rights.
