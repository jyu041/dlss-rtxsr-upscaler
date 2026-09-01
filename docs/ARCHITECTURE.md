# Architecture

`app.py` launches the Gradio UI on `127.0.0.1` with analytics disabled. `src/core` owns paths, JSON settings, media inspection, diagnostics, safe process ownership, and one-job cancellation. `src/video` owns FFmpeg-facing operations. `src/backends` contains strict adapters for nvvfx and DLSS5; unavailable backends raise clear errors instead of falling back.

The intended full pipeline is bounded streaming: FFmpeg decode to CPU, one frame to the backend, copy result to independent output memory, enqueue to encoder, release temporary GPU/DLPack references, and continue. The RTX adapter implements the per-frame lifetime boundary; the machine-specific SDK/video-worker integration remains gated until `nvvfx` is installed and smoke-tested.
