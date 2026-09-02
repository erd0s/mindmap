# Mindmap v0.3.1 release qualification

This record separates the published release evidence from the manual checks that
must finish before the follow-up release. The v0.3.1 release is public and its
automated release gate passed. Post-release functional qualification is still in
progress.

## Published release

| Field | Result |
|---|---|
| Release | [v0.3.1](https://github.com/erd0s/mindmap/releases/tag/v0.3.1) |
| Published | 2 September 2026 at 10:31:26 UTC |
| Tag | Annotated `v0.3.1` |
| Commit | `61df677e44f7d8258b421efc1323ef1e38141709` |
| Workflow | [Release run 33619563617](https://github.com/erd0s/mindmap/actions/runs/33619563617) |
| Workflow result | Passed |
| Release assets | 23 |

The protected release environment was approved only after the tag and workflow
head resolved to the commit above. The release gate, 17 cross-platform terminal
builds, plugin packaging, macOS signing and notarization, attestations, and
publication completed successfully.

Every downloaded asset matched `checksums.txt`. GitHub attestation verification
passed for `mindmap_linux_amd64`, both plugin archives, and the universal macOS
DMG. Independent checks on the downloaded DMG and application confirmed:

- a valid Developer ID Application signature and Apple certificate chain;
- the hardened runtime;
- successful notarization and stapling for both the DMG and application;
- Gatekeeper acceptance;
- the `io.github.erd0s.mindmap` application identifier;
- version 0.3.1; and
- universal `x86_64` and `arm64` application slices.

GitHub reported one non-blocking workflow annotation: the pinned
`softprops/action-gh-release` release action still declares Node 20 compatibility,
so GitHub forced it to Node 24. The action should be updated and revalidated before
the follow-up release.

## Functional scenarios completed

The Linux scenarios used the public `mindmap_linux_amd64` binary and both public
plugin archives with an isolated database and home directory. The Apple-silicon
macOS scenario used the public shell installer with another isolated profile.
The real Mindmap databases and pinned canary installations were not changed.

### Terminal and lifecycle

- Start, project listing, status, snapshot, stop, and restart passed. Stop marked
  the project paused, retained all 42 concepts present at that point, and made an
  inactive prompt hook silent. Restart restored active tracking and the same map.
- The terminal viewer rendered under `xterm-256color` and
  `screen-256color`, opened and closed the shortcut overlay, redrew after a
  resize, and exited cleanly.
- `TERM=dumb` produced a static ASCII snapshot with no escape bytes. A
  non-UTF-8 locale also selected the ASCII rendering path.
- A direct pseudo-terminal rendered after the harness assigned a nonzero window
  size. The first zero-size pseudo-terminal was a harness error, not a product
  failure.
- A change recorded while the terminal viewer was open appeared within one
  second.
- Deletion cancellation left the graph unchanged. Confirmed deletion created the
  expected tombstone, and an explicit `restore: true` record restored the
  selected Unicode test concept.
- Activation from the isolated home directory was blocked with
  `MINDMAP_ACTIVATION_BLOCKED_V1`; the hook did not attach the outside session or
  guess the active child project.

### Checkpoint and graph boundaries

- A valid record payload larger than 4096 bytes committed through
  non-interactive standard input.
- Starting `record --file -` with interactive terminal input failed immediately
  with exit status 2 and directed the caller to a pipe, heredoc, or payload file.
  The graph did not change.
- The map grew from 4 to 30 concepts across two checkpoints, proving that the old
  24-concept lifetime ceiling is gone.
- A checkpoint with 21 new concepts, a fifth independent root, an eleventh depth
  level, and a numbered turn node each failed independently with exit status 2.
  Every failed checkpoint was atomic.
- Reusing a Codex interaction for a steered prompt emitted
  `MINDMAP_CHECKPOINT_REOPENED_V1`, retained both prompts, and accepted an
  incremental corrective checkpoint.
- A tool observed after a checkpoint reopened the turn immediately and reported
  the saved and current generations. A two-minute-old generation-aware clean
  checkpoint did not reopen because of age alone. A two-minute-old legacy
  zero-generation checkpoint did reopen through the compatibility fallback.
- A notification observed before the final record passed Stop. The same
  notification observed after the record triggered a corrective pass.

### Agent and package interoperability

- The real Codex frontier-handoff evaluation passed. The model completed the
  fixture task and attached its settled retry-policy decision to the intended
  delivery-reliability frontier rather than to the root or decoy branch.
- The real Claude unattended-denial scenario passed: Claude returned normally,
  wrote no checkpoint, retained one unresolved turn, and exposed the missing
  checkpoint diagnostic on the next prompt.
- With normal Model Context Protocol configuration and built-in Bash denied,
  Claude used Serena's `execute_shell_command`, wrote one checkpoint, retained no
  unresolved turn, and saved tool generation 3 at checkpoint generation 3.
- The public Claude package wrote a child concept which the public Codex package
  read on its next prompt. Concurrent records from both public packages
  completed without a lock error and both changes appeared in the snapshot.

### Public installers and native runtime

- The public v0.3.1 shell installer installed the checksum-matching Linux AMD64
  binary into an isolated directory; the binary reported version 0.3.1.
- The same tagged installer installed the checksum-matching Darwin ARM64 binary
  on the MacBook. Version, start, status, `TERM=dumb` ASCII rendering, stop, and
  paused status passed. The temporary profile was removed afterward.

## Remaining qualification

Do not create the follow-up release tag until these checks are complete or Dirk
explicitly waives them:

At the 2 September 2026, 11:47 BST census, fresh post-candidate DirkOS
sessions had 52 turns with completed output; all 52 were checkpointed. The
MacBook had two post-boundary completed turns, both from a session that predates
the revised candidate, so they do not satisfy the fresh-session sample. This is
a progress count, not the final semantic or failure audit.

1. Complete the revised cross-machine canary. The DirkOS turn-volume threshold
   is met, but the time gate does not open until 7 September 2026 at 15:58:47
   BST. A representative fresh-session MacBook sample, confirmation that every
   pre-candidate agent session was restarted, and the final failure and semantic
   audit also remain.
2. Have an independent reader complete the blinded ten-second cold read and
   record whether they identify the root intent, settled work, active frontier,
   and next step.
3. Run the Finder and LaunchServices desktop scenarios in a disposable macOS
   user account. This includes multi-window behavior, picker shortcuts, viewport
   independence, keyboard accessibility, stale-revision deletion, live refresh,
   relaunch persistence, and Finder-launched Codex Desktop and Claude Desktop
   hooks. The available MacBook has only Dirk's daily account, which the runbook
   explicitly excludes from these destructive scenarios.
4. Repeat the macOS desktop scenarios on real Intel hardware. The universal
   binary contains the Intel slice, but no Intel runtime host was available.
5. Run the Windows binaries and PowerShell installer on a real Windows host.
   Neither PowerShell nor Wine was available on the Linux qualification host.
6. Complete late-agent installation and same-version forced-refresh checks in a
   clean user profile with real Codex and Claude installations.
7. Update the release action that produced the Node 20 compatibility warning,
   then rerun the signed release preflight.

Any product defect found by the remaining scenarios must be fixed, committed,
and requalified before the follow-up signed release.
