# Mindmap 0.3.2 release qualification

The release contains the repair merged in [PR #41](https://github.com/erd0s/mindmap/pull/41), commit `fb2d09006080fd9f31222df44f8a51c47a9e6d49`. Its tree matches the qualified candidate plus the release changelog. The separate draft PR #27 was closed as superseded; its branch and worktree were retained.

The local repair and retained model samples are described in [the closeout](repair-closeout.md). The final sample passed 48/48 semantic trials covering 66 checkpointed turns, 6/6 real-tool recovery trials and 4/4 recovery boundary checks. These bounded samples do not establish a production reliability rate.

## Release checks

- Python: 155/155; frontend: 17/17 plus production build; Go packages and desktop service tests passed.
- Go race tests and `go vet` passed. The native unsigned universal macOS app preflight passed.
- Runtime vulnerability checks passed: both Go modules and production npm dependencies reported no vulnerabilities. The preflight inventory recorded three moderate Dependabot alerts for development-only Vitest/mocker dependencies; their separate dependency-update work was not merged into this runtime repair.
- Package content, byte-for-byte reproducibility, notice checks and all host validators passed. GitHub Linux/macOS checks and CodeQL passed on PR #41.
- The [manual release preflight](https://github.com/erd0s/mindmap/actions/runs/35536329381) passed at the release commit, including signing, notarization, stapling, Gatekeeper assessment, the complete artifact manifest and provenance attestations. Its publishing job was skipped as designed.
- All 22 preflight artifacts matched the authenticated checksum manifest. Both CI-built plugin ZIPs matched the locally qualified ZIPs byte for byte.

| Plugin | SHA-256 |
| --- | --- |
| Codex | `02587a270320d72a1b9a50a1d36c6fcf753c317547cefedc226202564fa14213` |
| Claude | `af508fd67fa53e369bb1017a8689568f7bdb30190515a37f7bc84c9d9f524cd2` |

The annotated tag `v0.3.2` points to the same commit. The independent [tag release workflow](https://github.com/erd0s/mindmap/actions/runs/35536705506) passed and [published v0.3.2](https://github.com/erd0s/mindmap/releases/tag/v0.3.2) with the signed desktop app, terminal binaries, plugin ZIPs, checksums and attestations.

All 22 downloaded release artifacts matched the published checksum manifest. Its attestation verified against the repository, release workflow, exact source commit and `refs/tags/v0.3.2`. Both published plugin ZIPs still match the qualified local packages. The downloaded DMG and universal app passed local signature, stapled-ticket and Gatekeeper checks; the app reports version 0.3.2 and contains both Apple-silicon and Intel binaries. The published Mac arm64 and Linux amd64 terminal binaries also executed successfully and reported version 0.3.2, without replacing the live binaries.

## Live installation and canary

Release and rollout were authorized after the local closeout. Consistent SQLite backups and complete copies of the four installed plugin packages were prepared on the Mac and Linux workstation. Both database backups passed integrity checks. Private backup manifests remain on their respective machines under `~/.local/state/mindmap/release-backups/`.

The controlled live cutover is queued because affected Codex/Claude processes are still running. The existing forced-refresh procedure removes cached runtime paths; [the installation instructions](../README.md#install) require active hosts to finish and quit first. No running host was terminated and the release task did not invoke the live installer or forced refresh.

The final inventory nevertheless observed Mac Codex registered at 0.3.2, with every file matching the published ZIP and the former 0.3.1 cache directory removed. The cause of that cache replacement was not attributed. Mac Claude and both Linux installations remained at 0.3.1. To preserve the path used by existing sessions, the 23-file Mac Codex 0.3.1 cache was restored exactly from the verified backup; the registered default remained 0.3.2. This follows the compatibility-cache recovery recorded for [v0.3.1](release-qualification-v0.3.1.md). Remove that compatibility copy only after all old processes have ended.

A later check found all 23 restored compatibility-cache files removed again. The restoration therefore did not provide a durable bridge for old sessions; the verified backup outside the managed cache remains intact. The cause remains unattributed. Finish and quit the affected hosts before completing the controlled cutover.

This partial version transition is not a completed installation check: fresh-process hook delivery and the four-installation cutover remain outstanding. The before/after inventories, restoration and failed persistence check are retained with the release evidence.

After a quiet window, refresh the backups, use the existing installer pinned to v0.3.2, then run `mindmap setup --refresh --all` on each machine. Verify every installed file against the release ZIPs, identify any host-owned markers, and start fresh processes to check actual hook delivery, checkpoint acceptance and Stop behavior. These remaining checks belong to [#37](https://github.com/erd0s/mindmap/issues/37).

The bounded canary in [#38](https://github.com/erd0s/mindmap/issues/38) follows installation verification. It has not been run against the new live installations. Production-map reconciliation remains separate in [#39](https://github.com/erd0s/mindmap/issues/39).

Rollback must stop all affected writers again and retain a fresh database backup. The schema additions are additive, but old Python writers do not enforce the new request protocol. Do not mix runtime versions or blindly replace a database that contains newer graph writes with the pre-upgrade snapshot.

Release evidence and the prepared cutover instructions are retained locally under `build/repair-release-2026-09-20/`. Database backups and private session evidence are not published.
