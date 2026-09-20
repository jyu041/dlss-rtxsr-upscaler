# Portable runtime decision — deferred

> **Current project decision:** a no-Conda portable distribution is deliberately
> deferred and is not part of the active completion criteria for the current
> source-based release. The validated user path is recursive clone → setup.bat
> → start.bat with Miniconda/Anaconda available.

No-Conda turnkey launch is not claimed by the current project.

The official CPython 3.11.9 Windows x64 embeddable archive is the only
portable-Python option currently considered sufficiently reproducible for a
future candidate. It is fixed-version and obtainable from the official Python
distribution, but it is an embeddable distribution rather than a complete
application environment: package installation, dependency resolution, and
native CUDA/VFX wheel compatibility still require a separately verified
process.

The repository’s currently validated application environment uses Python 3.11
with the pinned `nvidia-vfx==0.1.0.1`, CUDA-enabled PyTorch, PyAV, OpenCV,
Gradio, and FFmpeg/NVENC. No clean extraction has yet demonstrated that the
full production import set works from CPython’s embeddable layout without
Conda or a system Python.

Therefore the current decision is: keep Conda as the validated source-install
and test path, and retain the portable builder only as historical/experimental
packaging infrastructure. No portable-runtime work is required before the next
source-based beta. If that product direction is resumed later, its Python
archive, wheel set, FFmpeg build, notices, and clean-machine HTTP test must be
validated before advertising it.

The dependency split is now explicit in `tools/requirements/runtime.txt`,
`tools/requirements/test.txt`, and `tools/requirements/dev.txt`. This prevents pytest and
audit tooling from being treated as end-user runtime dependencies.
