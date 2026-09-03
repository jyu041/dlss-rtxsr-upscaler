# Architecture

`app.py` launches a localhost Gradio UI with analytics disabled. `src/core`
owns settings, paths, diagnostics, job ownership, media inspection, and
progress. `src/video` owns FFmpeg-facing operations. `src/backends` contains
strict RTX VSR, standalone DLSS SR, and experimental DLSS5 adapters.

Each backend is independently gated. Missing runtimes or failed self-tests
produce diagnostics and stop that operation rather than falling back to
another backend.

RTX VSR processes frames through the NVIDIA VFX Python bridge. DLSS SR uses a
separate native D3D12/NGX host with persistent per-job state and DIS motion
guidance. DLSS5 uses the retained generic protocol client and a separately
approved local worker. All runtime binaries and generated media stay outside
the tracked source tree.
