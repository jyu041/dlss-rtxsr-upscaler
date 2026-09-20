# Documentation Index

The repository contains two kinds of documentation:

1. **Current operational documentation** — describes the behavior and policy of
   the current `main` branch.
2. **Historical engineering evidence** — Phase 4/5 reports and dated validation
   notes retained to preserve how experimental backend decisions were reached.

For normal use or contribution, start with the current documents below. A
historical report is not a current requirement merely because it contains
phrases such as "not implemented", "future work", or "candidate".

## Current user and maintainer documentation

| Document | Purpose |
| --- | --- |
| [Installation](INSTALL.md) | Source prerequisites, setup, managed runtime provisioning, startup |
| [Troubleshooting](TROUBLESHOOTING.md) | Common installation and runtime failures |
| [Architecture](ARCHITECTURE.md) | Current application/backend structure |
| [Testing](TESTING.md) | Current test classes, commands, and hardware-gate policy |
| [Security audit](SECURITY_AUDIT.md) | Runtime trust, fail-closed behavior, and containment policy |
| [DLSS 5 approval](DLSS5_APPROVAL.md) | Current v3/v10 approval and execution boundaries |
| [DLSS 5 research](DLSS5_RESEARCH.md) | Current experimental findings and benchmark interpretation |
| [DLSS5 / MFG quality-performance experiment](DLSS5_MFG_QUALITY_PERFORMANCE_2026-09-20.md) | Isolated branch controls, public-upstream boundaries, and RTX 3070 Ti promotion gates |
| [Third-party inventory](THIRD_PARTY.md) | Dependency/licensing inventory |
| [Development](DEVELOPMENT.md) | Contributor workflow |
| [Project status](PROJECT_STATUS.md) | What is complete, deliberately deferred, or hardware-dependent |
| [v0.2.0-beta.1 release notes](RELEASE_NOTES_v0.2.0-beta.1.md) | Current source-beta changes, validation scope, and limitations |
| [Binary distribution boundary](legal/BINARY_DISTRIBUTION_NOTICES.md) | Packaging/distribution constraints |

## Current hardware evidence

These dated documents support current capability claims and should remain
separate from generic installation documentation:

- [DLSS 5 v10 application hardware validation](DLSS5_V10_APP_HARDWARE_2026-09-19.md)
- [Managed grid4 worker hardware validation](MFG_GRID4_MANAGED_WORKER_HARDWARE_2026-09-19.md)
- [MFG GPU timestamp instrumentation](MFG_GPU_TIMESTAMP_INSTRUMENTATION_2026-09-18.md)
- [MFG withheld-frame quality campaign](MFG_WITHHELD_FRAME_QUALITY_2026-09-18.md)
- [DLSS 5 v10 binary/static evidence](DLSS5_V10_BINARY_STATIC_EVIDENCE_2026-09-18.md)
- [DLSS 5 v10 static ABI audit](DLSS5_V10_STATIC_ABI_AUDIT_2026-09-18.md)

## Historical engineering reports

Files beginning with `PHASE4`, `PHASE5`, and the older detailed DLSS-G
milestone reports are retained as engineering history. They document
intermediate states that were useful while reverse-engineering, validating, or
hardening the current paths.

Examples include:

- `PHASE4A_*.md` through `PHASE4E_*.md`
- `PHASE5A_*.md` through `PHASE5R_*.md`
- `PHASE5_DLSS5_V9_STATIC_AUDIT.md`
- `PHASE5_MFG_REFRESH_AUDIT.md`
- `PHASE5_PORTABLE_*.md`
- `DLSSG_*OPTIMIZATION.md`
- `PERSISTENT_DLSSG_2X_WORKER.md`
- `REAL_VIDEO_DLSSG_2X_BACKEND.md`
- `NATURAL_VIDEO_DLSSG_VALIDATION.md`

Those reports are **not** authoritative over the current README, installation,
testing, security, approval, or project-status documents. If a historical
report conflicts with current operational documentation, current operational
documentation governs.

## Portable runtime work

The no-Conda portable distribution research is retained for reference in:

- [Portable runtime decision](PORTABLE_RUNTIME_DECISION.md)
- [Phase 5 portable packaging](PHASE5_PORTABLE_PACKAGING.md)
- [Phase 5F portable runtime notes](PHASE5F_PORTABLE_RUNTIME.md)

That direction is deliberately deferred. It is not part of the active
completion criteria for the current source-based project.
