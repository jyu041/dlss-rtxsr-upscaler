# Testing

Run `conda run -n dlss-rtxsr-upscaler pytest -q`. Tests cover safe paths, JSON presets, scale and alignment calculations, FFprobe parsing helpers, codec validation, cancellation, and backend non-fallback behavior. FFmpeg is used directly for bounded media plumbing because the available Windows PyAV pin has no compatible wheel on this machine. GPU tests must be explicit environment-dependent tests and are skipped when the official nvvfx/DLSS5 runtime cannot initialize. Never report a skipped GPU test as success.

This sprint's verified GPU run used an RTX 3070 and the official NVIDIA wheel: 90 frames, 320x240 to 640x480, 15.93 FPS, H.264 NVENC, and AAC audio preserved. The 1000-frame stability run is recorded in the sprint report when executed; measurements must not be inferred from this short run.
