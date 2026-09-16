# Portable runtime release notes

The release launcher is now portable-only. `start.bat` requires the runtime
under the application directory and fails closed when Python, FFmpeg, FFprobe,
or the build manifest is absent. It does not invoke Conda or search the
system `PATH`. Developer use remains available through `start-dev.bat`.

The selected Python provider is the official CPython 3.11.9 Windows x64
PythonCore archive. Its URL, size, SHA-256, architecture, and PSF-2.0 license
are pinned in `tools/portable_toolchain.json`. PythonCore was selected over the
embeddable archive because it includes the normal `Lib`/`DLLs` layout needed by
native CPython wheels and movable `Lib/site-packages` imports. The exact locally
available FFmpeg provider
is GyanD 9.0.1 full build, GPL-3.0-or-later, with the exact upstream archive,
archive hash, and two staged executable hashes recorded there.

The CPython archive alone is not an application runtime: it still needs the
project's pinned Python packages and their native dependencies. The validated
local candidate contains those packages, but the current source assembler still
accepts them as an explicitly staged directory; a complete wheel-level lock and
Conda-free reconstruction path remain Phase 5H work. `repair.bat` reports this
state and the pinned inputs; it never falls back to a machine-wide Python or
FFmpeg.

No runtime binaries, archives, generated media, or validation output are source
tracked. They remain local release inputs or ignored evidence.

Ordinary CI uses `requirements-ci.txt`, which retains the real UI/media import
surface while excluding optional CUDA/VFX packages that are lazily imported and
validated in hardware-specific gates. The complete portable runtime still
bundles the validated CUDA/VFX packages when those features are selected.
