# Security and Provenance

The application is a local utility. Its UI binds to localhost, does not enable
Gradio sharing, and does not silently download or execute external runtimes.
Backend adapters fail closed when a dependency is missing or unapproved.

## Runtime rules

- NVIDIA VFX, DLSS/NGX, and DLSS5 runtimes must be obtained separately from a
  legitimate source and remain outside Git.
- DLSS SR validates the exact SHA256 of the configured `nvngx_dlss.dll` before
  use and requires a native self-test.
- DLSS5 validates a user-controlled approval manifest, all required hashes,
  signed Feature-18 evidence, and an exact enabled Windows Firewall outbound
  block for the local worker.
- A changed hash invalidates approval. There is no silent fallback to resize,
  RTX VSR, or another DLSS mode.
- Do not place proprietary DLLs, model weights, media, approval manifests, or
  generated logs in tracked paths.

## Public references

The only retained source submodule is
[Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer),
pinned to commit `796ed5927a202ba50b5c929cd08e16b365041162`. Only its generic
`dlss5` protocol/session/settings/motion/diagnostic code is used; ComfyUI is
not installed or modified.

The official public [NVIDIA Streamline](https://github.com/NVIDIA-RTX/Streamline)
SDK may be staged locally for development, but its normal public 2.12.0
package does not establish the required Feature-1004/DLSS NR plugin. It is
ignored and is not redistributed. The existing unsigned `nvngx_dlssnr.dll`
must not be used.

## Review guidance

Before enabling an experimental runtime, record its source, exact hashes,
Authenticode status, Defender result, and the runtime's applicable license.
Keep the worker outbound firewall rule enabled and use synthetic or owned
media for tests. Malware-scan cleanliness does not establish vendor
provenance or redistribution rights.
