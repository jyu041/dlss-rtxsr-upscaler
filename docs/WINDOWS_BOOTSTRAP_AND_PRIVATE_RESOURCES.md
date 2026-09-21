# Windows bootstrap and private resources report

Date: 2026-09-14

## A. Machine inventory

Validated on Windows 10.0.26200 with PowerShell 7, Git 2.55.0, Git LFS 3.7.1,
Conda at `C:\Users\<user>\miniconda3`, NVIDIA GeForce RTX 3070 Ti (compute
8.6), NVIDIA driver 610.62, and `nvidia-smi` at `C:\Windows\System32\nvidia-smi.exe`.
The installed Visual Studio 2022 components were discovered through
`C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe`;
MSBuild/CMake are not independently available on PATH.

## B. Original errors and current mitigation

The first `conda env update` attempted to use a localhost proxy (`127.0.0.1:9`)
and failed reading the Anaconda terms cache with `CondaToSPermissionError`.
The project environment now declares `conda-forge` plus `nodefaults`, so normal
project bootstrap does not need the `repo.anaconda.com` default channels or
their terms cache. This keeps project package resolution on the channel the
environment actually specifies rather than inheriting machine-level defaults.

A `127.0.0.1:9` proxy is also a known pattern used by sandboxed/automation
shells to intentionally block child-process network access. Setup does not
silently bypass that security boundary. It now checks the process proxy before
invoking Conda or any setup-time downloader and exits immediately with an
actionable message when the discard proxy is present, instead of spending
minutes in Conda/urllib retries. Run setup from a normal network-enabled shell
for the standard bootstrap. The optional DLSS 5 v3 archive is cached after its
first verified download, and an exact already-downloaded v3.0 archive can also
be supplied through `NVE_DLSS5_ARCHIVE` when the rest of the setup dependencies
are available normally.

The initial Conda-forge FFmpeg 8.0.1 package installed files but both FFmpeg
and FFprobe failed to launch from the environment, so it is not used as the
project’s FFmpeg solution.

## C–D. Fixes and FFmpeg

`environment.yml` retains the Python/package pins and `setup.bat` now requires
system FFmpeg/FFprobe plus both NVENC encoders. Gyan.FFmpeg 9.0.1 was installed
through winget. Verified:

* `ffmpeg` and `ffprobe` launch successfully;
* `h264_nvenc` and `hevc_nvenc` are listed;
* package source: winget id `Gyan.FFmpeg`.

## E. Python environment

The dedicated `dlss-rtxsr-upscaler` environment is Python 3.11.13 with Gradio
6.16.0, PyTorch 2.10.0+cu128 (CUDA available), PyAV 18.1.0, OpenCV 5.0.0,
NumPy 2.2.6, Pillow 12.3.0, and nvidia-vfx 0.1.0.1. `pip check` passed and
direct imports passed.

## F. Native worker

The existing x64 Release worker is present at
`native/dlssg_sm86_offline/bin/dlssg_sm86_offline.exe`; `--selftest` passed.
SHA-256: `603CFB2D14C4EC923747183FF9808EB05CB8ECF830729359455589DF4A641B7C`.
The source build still requires locally supplied NVIDIA NGX/NVAPI/Optical Flow
SDK headers and a Visual Studio C++ toolchain.

## G. Resource inventory and legal handling

The private lock manifest records the project-owned worker, the community
runtime, official NVIDIA runtime directory, driver Optical Flow DLL, and
FFmpeg. The community `version.dll` (known SHA-256
`C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2`, source
commit `5f62ff44a9c08f9841fa605e7b7160f79ccd2c40`) and adjacent INI are not
rehosted because redistribution rights were not established. NVIDIA runtime,
SDK, and `nvofapi64.dll` are also not rehosted. Exact acquisition and hash
guidance is in the private repository’s `external/README.md`.

## H–I. Historical private-resource bootstrap

A separate private resource repository was used during early bootstrap work.
It contained LFS rules, project-owned worker artifacts, lock metadata, and
bootstrap/verification utilities. Current public source installation no longer
requires access to that repository; validated public bootstrap artifacts are
retrieved from this project's pinned releases.
PowerShell syntax checks passed.

## J. Application

Project diagnostics pass for Windows, GPU, FFmpeg, FFprobe, CUDA, and Python
packages. The Gradio UI builds as `Blocks` in the pinned environment. With the
known local community and official runtime paths supplied, DLSS-G reports
`EXPERIMENTAL READY` and the private `verify.ps1` ends `READY`.
the community runtime and official runtime directory through
`DLSSG_COMMUNITY_RUNTIME` and `DLSSG_OFFICIAL_RUNTIME_DIR`. The NVIDIA driver
Optical Flow runtime is present at `C:\Windows\System32\nvofapi64.dll`.

## K–M. Tests and Git

Worker self-test passed; package imports and `pip check` passed; Python tests
passed (`69 passed, 2 skipped`); public commits `291f520`, `baf3fd7`, and
`a61d24a` were pushed; private commits `1ca9f63`, `b4e184b`, and `259e517` were
pushed. A fresh clone simulation passed for clone, LFS retrieval,
synchronization, worker self-test, and `git diff --check`. Full native rebuild,
NVOF direction test, and true DLSS-G UI readiness still require the external
SDK/runtime inputs.

## N–O. Remaining manual actions and primary result

On another machine, supply the lawful community runtime and official NVIDIA
runtime/SDK, set the two DLSS-G variables, and install Visual Studio C++ build
components if rebuilding from source. The current validation PC meets the
runtime verification criteria; a live Gradio banner was not captured before
the brief launch test was terminated, so full video processing remains an
external-runtime-dependent manual smoke test.
