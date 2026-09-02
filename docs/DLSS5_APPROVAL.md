# DLSS5 Runtime Approval

Status: **APPROVED FOR LOCAL EXPERIMENTAL USE**

The v3.0 release is retained in the local, gitignored quarantine path `runtime/audit/dlss5-v3/`. The exact hashes in `runtime/dlss5-v3/approval.json` were manually approved by the user after source review, Microsoft Defender scanning, and VirusTotal review. Approval is local and experimental only.

Required evidence before approval:

- Confirm the runtime was legitimately obtained and may be used locally as intended.
- Review `runtime/audit/dlss5-v3/reports/binary_hashes.json` and `static_script_review.md`.
- Confirm the exact files and hashes to be authorized.
- Run the application only in an isolated test environment and capture behavior/logs.
- Set `approved` to `false` immediately if any approved binary hash changes; a future runtime is never automatically approved.

The native worker remains closed-source. Its outbound and inbound access is blocked by existing Windows Firewall rules matching the exact staged worker path. RTX VSR remains supported and unchanged.

The controlled first execution passed protocol v4 and signed Feature-18 verification on five synthetic 128x128 RGBA8 frames. Subsequent synthetic checks passed temporal motion/scene reset, 1.5x and 2x scaling, Preview Frame, 3-second Preview Clip, 90-frame full video with audio, Unicode input, and owned-worker cancellation.
