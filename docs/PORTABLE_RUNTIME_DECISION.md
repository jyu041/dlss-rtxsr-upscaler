# Portable runtime decision — Phase 5E

No-Conda turnkey launch is not claimed by this phase.

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

Therefore the current decision is: keep Conda as the validated developer and
test path; retain the portable builder as an explicit packager for a supplied,
independently audited runtime; do not ship or advertise a portable runtime
until its Python archive, wheel set, FFmpeg build, notices, and clean-machine
HTTP test have all been recorded.

The dependency split is now explicit in `requirements-runtime.txt`,
`requirements-test.txt`, and `requirements-dev.txt`. This prevents pytest and
audit tooling from being treated as end-user runtime dependencies.
