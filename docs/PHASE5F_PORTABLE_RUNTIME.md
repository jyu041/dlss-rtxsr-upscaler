# Portable runtime release notes

`start.bat` supports both a complete portable package and the validated source
checkout. It prefers a complete portable runtime when present; otherwise it
loads the saved source environment and launches through Conda. A developer-only
source launcher remains available at `tools/start-dev.bat`.

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
accepts them as an explicitly staged directory. A complete wheel-level lock and
Conda-free reconstruction path are deliberately deferred and are not part of
the current source-based release criteria. `repair.bat` reports the portable
candidate state and pinned inputs; it never falls back to a machine-wide Python
or FFmpeg.

No runtime binaries, archives, generated media, or validation output are source
tracked. They remain local release inputs or ignored evidence.

Ordinary CI uses `tools/requirements/ci.txt`, which retains the real UI/media import
surface while excluding optional CUDA/VFX packages that are lazily imported and
validated in hardware-specific gates. The complete portable runtime still
bundles the validated CUDA/VFX packages when those features are selected.
