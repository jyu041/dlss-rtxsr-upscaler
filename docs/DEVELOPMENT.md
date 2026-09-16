# Development setup

The normal user experience is the extracted portable package described in the
root README. Contributors working from a source checkout may use Conda for
development and ordinary tests:

```bat
setup.bat
start-dev.bat
```

`start.bat` is intentionally portable-only and is not a developer-environment
launcher. The portable builder currently requires explicit validated runtime
directories for the dependency-bearing Python environment and FFmpeg. Do not
copy proprietary NVIDIA runtimes, test media, generated outputs, or local
settings into the repository.

Run ordinary tests with `requirements-ci.txt`; hardware-specific validation
uses the separate project environment and explicit opt-in gates.
