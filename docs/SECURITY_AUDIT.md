# Security and Provenance

The application is a local utility. Its Gradio UI binds to localhost and does
not enable a public share link. Video processing is local.

Network access is used only by explicit user-initiated provisioning or runtime
management actions such as `setup.bat`, Runtime Manager install/repair, and
the managed DLSS 5 v10 provisioner/preflight. The retained v3 provisioner is
legacy compatibility tooling and is not part of normal onboarding. Ordinary
startup does not silently replace or download a backend runtime.

Backend adapters fail closed when a dependency is missing, modified,
unapproved, or incompatible.

## Runtime rules

- Managed runtime sources, sizes, hashes, destinations, and activation policies
  are recorded in `src/runtime_manager/manifest.json`.
- Project-managed downloads are explicit actions and are verified before
  activation.
- DLSS SR validates the approved host/runtime identity and requires its native
  self-test for readiness.
- DLSS-G validates the project worker identity, the pinned SM86 direct-host
  runtime, and the official NVIDIA provider. The experimental grid4 worker has
  its own pinned identity and never silently replaces C55/grid1.
- DLSS 5 v3 requires the pinned archive/file identities, Authenticode
  observation, Microsoft Defender scan, exact enabled outbound firewall rule,
  local approval evidence, and successful Feature-18 self-test.
- DLSS 5 v10 remains separate from v3. Its application path requires the pinned
  v10 identity, fresh static/Defender preflight, isolated child execution,
  temporary exact-interpreter outbound firewall containment, process-tree
  checks, per-frame result validation, and mandatory clean close/cleanup.
- A changed hash or failed gate invalidates readiness. There is no silent
  fallback to resize, RTX VSR, or another DLSS mode.
- Do not place proprietary DLLs, model/runtime archives, user media, approval
  manifests, generated logs, or credentials in tracked source paths.

A pinned hash establishes identity, not inherent trust or vendor endorsement.
A clean malware scan does not establish provenance, support, or redistribution
rights.

## Public references and retained source

The retained source submodule is
[Blueforcer/ComfyUI-DLSS5-Enhancer](https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer),
pinned to commit `796ed5927a202ba50b5c929cd08e16b365041162`. The project
uses retained generic protocol/session/settings/motion/diagnostic code; ComfyUI
itself is not installed or modified by this application.

Other public upstream sources used by manifest/provisioning policy include
NVIDIA Streamline, the validated SM86 DLSS-G project, and the explicitly pinned
Merserk DLSS 5 archives. Their binaries and licenses remain governed by their
respective upstream/vendor terms.

## Review guidance

Before changing an experimental runtime identity or expanding an execution
boundary, record the source, exact hashes, applicable license, signature status,
security-scan result, containment requirements, and hardware evidence.

Use synthetic or owned media for validation, and keep hardware-dependent gates
explicit rather than treating a skipped test as a successful validation.
