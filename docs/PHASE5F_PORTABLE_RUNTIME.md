# Phase 5F portable runtime

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
is GyanD 9.0.1 full build, GPL-3.0-or-later, with the two staged executable
hashes recorded there. The exact upstream FFmpeg archive URL was not recovered
from the local WinGet installation, so a release builder must not silently
substitute a different archive.

The CPython archive alone is not an application runtime: it still needs the
project's pinned Python packages and their native dependencies. The current
candidate therefore remains incomplete until a reproducible, redistributable
dependency staging procedure is recorded and verified in a clean extracted
directory. `repair.bat` reports this state and the pinned inputs; it never
falls back to a machine-wide Python or FFmpeg.

No runtime binaries, archives, generated media, or validation output are source
tracked. They remain local release inputs or ignored evidence.
