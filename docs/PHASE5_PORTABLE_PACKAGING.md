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

An explicitly supplied, separately licensed portable runtime can be staged
without changing the source tree:

```powershell
python tools/build_portable_candidate.py --output artifacts/NVE-phase5-portable.zip `
  --python-runtime <python-runtime-directory> `
  --ffmpeg-runtime <ffmpeg-directory> `
  --python-notice <python-license-notice> `
  --ffmpeg-notice <ffmpeg-license-notice>
```

The builder requires `python.exe`, `ffmpeg.exe`, and `ffprobe.exe`, records
hashes for staged external files and their supplied text notices, and never
downloads or infers these inputs. A supplied external runtime without an
explicit notice is rejected.

## Explicit runtime commands

The optional runtime manifest can be inspected without changing files:

```powershell
python tools/manage_runtime.py inventory
python tools/manage_runtime.py verify dlssg-sm86-0.3.1-candidate
```

Only `install` and `repair` perform a pinned HTTPS download, and both print
progress while staging and verifying the runtime. They require an explicit
command invocation; `inventory`, application startup, and diagnostics never
download or activate a runtime.
