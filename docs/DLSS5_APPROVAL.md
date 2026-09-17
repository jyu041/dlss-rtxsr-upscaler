# DLSS5 Runtime Setup

The old manual approval workflow is retired.

Normal users do **not** create `approval.json`, copy runtime hashes, approve
individual binaries, or configure a mandatory Windows Firewall rule.

`setup.bat` automatically downloads the compatible DLSS 5 Visual Enhancer v3.0
runtime directly from its upstream GitHub release and installs its runtime
subtree under `runtime/dlss5-v3`. The setup helper verifies the published
archive digest automatically before activation.

After installation, the project runs a local synthetic Feature-18 self-test.
The DLSS 5 backend becomes `EXPERIMENTAL READY` only when the installed
GPU/driver/runtime combination produces verified Feature-18 execution. This is
a functional correctness check rather than a provenance approval step.

The backend also continues to reject individual renders if the runtime reports
that Feature 18 was not verified or that processing fell back to the native
non-neural path.

The retained Blueforcer source is used as the generic protocol client. NVIDIA,
ReShade, RenoDX, and Visual Enhancer runtime binaries remain third-party
components under their respective terms and are downloaded from upstream rather
than stored in this source repository.

An outbound firewall block for the third-party worker is optional. Users who
prefer that policy can create one themselves; diagnostics may report whether an
exact block is present, but it is not required for backend readiness.

Community execution on RTX 30/40 hardware does not establish official NVIDIA
support for those GPUs. The automatic self-test therefore determines whether
the installed local combination is usable instead of assuming compatibility
from the GPU model alone.
