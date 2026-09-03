# Testing

Run `PYTHONPATH=. conda run -n dlss-rtxsr-upscaler python -m pytest tests -q`. Tests cover safe paths, JSON presets, scale and alignment calculations, FFprobe parsing helpers, codec validation, cancellation, and backend non-fallback behavior. GPU tests must be explicit environment-dependent tests and are skipped when the approved DLSS5 runtime cannot initialize. Never report a skipped GPU test as success.

The approved DLSS5 self-test is `PYTHONPATH=. conda run -n dlss-rtxsr-upscaler python -m src.backends.dlss5_selftest`. It rechecks the approval manifest, all five native hashes, the exact outbound firewall rule, RTX 3070 pairing, protocol v4, clean worker shutdown, and signed Feature-18 evidence. It uses synthetic RGBA8 content only.

The extracted release tree is intentionally outside the normal test root. If it exists locally, do not run unrestricted recursive pytest discovery because the embedded Python distribution contains test-like package directories; target `tests` explicitly.

This approved local run completed the DLSS5 synthetic matrix: protocol v4 Feature-18 verification on 5 frames at 128x128, 30-frame temporal processing with scene-cut reset, 1.5x and 2x scaling, a 3-second/90-frame H.264 NVENC preview and full render with audio, Preview Frame, Unicode input, and owned-worker cancellation. AV1 is not offered on the RTX 3070 path.

The UX test coverage includes 15 unit tests for progress/ETA, monitoring snapshots, tooltip coverage/escaping, and independent Unicode/corrupt-store preset handling. The real Gradio launch test passed (`2 passed`). Hardware progress coverage passed for both DLSS5 and RTX VSR. `pip check` reported no broken requirements; `pip-audit` reported no known vulnerabilities and could not audit the local CUDA Torch build because it is not published on PyPI.

This sprint's verified GPU run used an RTX 3070 and the official NVIDIA wheel: 90 frames, 320x240 to 640x480, 15.93 FPS, H.264 NVENC, and AAC audio preserved. The 1000-frame stability run is recorded in the sprint report when executed; measurements must not be inferred from this short run.
