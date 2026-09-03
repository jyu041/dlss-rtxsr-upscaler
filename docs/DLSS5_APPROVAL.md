# DLSS5 Runtime Approval

DLSS5 Neural Rendering is an optional experimental backend. It is unavailable
until a user supplies a legitimate compatible runtime and creates a local,
gitignored approval manifest.

Approval must record the runtime source, exact file hashes, Authenticode
results, malware-scan result, and the user's decision. The application must
also verify the manifest, signed Feature-18 evidence, and an exact enabled
Windows Firewall outbound block for the worker. Any hash change invalidates
approval; there is no automatic update or fallback.

The retained Blueforcer source is used only for the generic protocol client
and is licensed separately under MIT. NVIDIA, ReShade, RenoDX, and worker
runtime binaries are proprietary or separately licensed and are not included
in this repository.

Current public NVIDIA material describes 3D-Guided Neural Rendering as
targeting GeForce RTX 50 Series. Community Feature-18 experiments do not
establish official RTX 3070 support. A future signed runtime must first pass a
feature-support probe on the target GPU before depth or model integration.
