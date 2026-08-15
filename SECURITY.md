# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or exposed secret. Use GitHub's private vulnerability reporting for this repository. Include the affected version, reproduction steps, impact, and any suggested mitigation.

You should receive an acknowledgement within seven days. A fix and disclosure schedule will depend on severity and whether downstream users need time to update.

## Security boundary

Mindmap is a local tool. It opens no network listener and sends no telemetry. Its SQLite database contains normalized coding-agent transcript evidence and should be treated as sensitive.

The agent plugins execute local lifecycle hooks. Review their source before trusting them, keep Codex and Claude Code current, and install releases only from this repository. Release installers verify downloaded binaries with the checksums attached to the same GitHub release; macOS desktop releases are signed and notarized.

Subtree deletion removes concepts from the current map but retains provenance events and transcript evidence. It is not a secure-erasure function.

## Supported versions

Security fixes are issued for the latest release. Older pre-1.0 versions may be asked to upgrade before a report is investigated further.
