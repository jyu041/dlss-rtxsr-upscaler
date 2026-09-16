# Phase 5 portable packaging

`tools/build_portable_candidate.py` creates a deterministic, source-only
candidate from the committed `HEAD`. It includes `build-manifest.json` and
`SHA256SUMS`, and refuses to run with staged or unstaged source changes.

This milestone deliberately does not bundle Python, FFmpeg, NVIDIA runtimes,
community DLLs, or other binary material. Those components remain governed by
their own runtime-manager policies and are supplied or installed only through
an explicit, validated path.

`start.bat` now prefers a future validated embedded interpreter at
`runtime/python/python.exe`; when that directory is absent it retains the
Conda development fallback. The current source-only candidate therefore
remains a developer artifact until a separately licensed, reproducible Python
runtime is staged.

Example:

```powershell
python tools/build_portable_candidate.py --output artifacts/NVE-phase5.zip
```
