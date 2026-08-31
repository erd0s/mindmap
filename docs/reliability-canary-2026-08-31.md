# Reliability canary started 31 August 2026

## Candidate identity

The canary runtime is the generated plugin package from implementation commit
`287f53172455`. Commit `c19acbc` only updates the retained evaluation document.
Commit `fecbcce` corrects the same-version Claude setup refresh used by the
pinned installation below. Live boundary findings then produced candidate
`689b1f3`, which is the authoritative canary revision. Both Codex and Claude
were refreshed after the clean semantic run. The critical installed files—hook
manifest, hook adapter, activity module, lifecycle module, and store module—were
compared byte-for-byte with the generated packages and matched on both hosts.

| Host package tree | SHA-256 |
|---|---|
| Codex | `11b3822b0666f55168700440c6eb921267b0b96b8b2c8506267daa25f0683106` |
| Claude | `161d2b23821dbaeda560ad1c3b3aeb778b4becaffc6a218a026fa8abffb0a24b` |

Codex's marketplace refresh removed and reinstalled the plugin. Claude's normal
same-version update reported that 0.3.0 was current but left the old cache in
place. The canary therefore used Claude's supported uninstall with `--keep-data`
followed by install. The SQLite data was not removed or rewritten. The source
setup command was corrected in `fecbcce` so a future forced Claude refresh
performs that preservation/reinstall sequence automatically.

## Initial pinned cross-machine installation

On 31 August the complete candidate, including the corrected same-version
Claude refresh, was pinned at
`fecbcce50c0e1f8b5943c6616165ff649764f98d`. It is installed from persistent,
detached worktrees rather than from a mutable branch or public release:

| Machine | Pinned worktree | CLI SHA-256 |
|---|---|---|
| DirkOS | `/home/dirk/Dev/mindmap-canary-fecbcce` | `7a53cf8320a5ae513f51c82741221ff5e8a0a8809f4ed0ba79a5e7f6809ec9e3` |
| MacBook | `/Users/dirk/Dev/mindmap-canary-fecbcce` | `2289331577af742355206abb5c7aad7e29e094e05e9ebda465d690def29bded9` |

Both CLIs report version 0.3.0 because the plugin manifests and compatibility
checks use the public semantic version. The full commit and binary digests above
are the canary provenance; a canary suffix on only the CLI made the correct
0.3.0 plugins appear stale, so it was not retained.

Before changing either installation, SQLite's online backup command produced a
machine-local rollback copy and both copies passed `PRAGMA integrity_check`:

| Machine | Backup | Backup SHA-256 | Snapshot boundary |
|---|---|---|---|
| DirkOS | `/home/dirk/.local/share/mindmap/mindmap-before-fecbcce.sqlite3` | `9698b007bd43aebadefbb549cb4c4f34f6b2b1bf8858fc6906c187aabc2cb543` | `2026-08-31T13:56:12Z`; turn 595; event 1605 |
| MacBook | `/Users/dirk/.local/share/mindmap/mindmap-before-fecbcce.sqlite3` | `9d170b3ed3e5ada116623fd73097c9d14d9469d93e8598fbe3248bd87360cb19` | `2026-08-31T13:56:50Z`; turn 28; event 109 |

This phase used the original DirkOS boundary below, `turns.id > 506` and
`events.id > 1487`; the later backup boundary was rollback provenance, not a
reset of that sample. MacBook observations began at `turns.id > 28` and
`events.id > 109`. At backup time DirkOS had 529 turns with completed output and
565 checkpointed turns; the MacBook had 27 and 28 respectively. This evidence
remains useful, but revised-candidate rates must not mix it with the new boundary.

The generated Codex package and generated Claude package each compare exactly
with their corresponding installed cache on both machines. Both marketplaces
now use the pinned local worktree, both integrations report Mindmap 0.3.0
installed, and `mindmap doctor` passes for the database, supported Python,
Codex, and Claude. On macOS it also finds the desktop application. The existing
Mindmap.app remains the public 0.3.0 notarized Developer ID build; `codesign`
verification and Gatekeeper assessment both pass. It was deliberately not
replaced because this canary changes the agent runtime and setup CLI, not the
compatible database viewer.

Package generation and validation passed on both machines. The Go CLI tests
passed normally on DirkOS. On macOS one filesystem-boundary test initially used
Go's default `/private/var/folders` temporary directory, which lies outside the
real user home that the production route correctly requires. Re-running the
unchanged candidate with `TMPDIR=/Users/dirk/.cache/mindmap-go-test-tmp` passed;
this is a test-harness portability issue, not a product bypass.

Agent hosts read plugin and hook configuration at process startup. Existing
Codex processes were left running to avoid interrupting work, so sessions that
predate this installation can retain the package they started with. New Codex
and Claude sessions on both machines were authoritative for this initial phase.
The revised boundary below supersedes that installation boundary.

## Revised candidate after boundary findings

The initial production phase exposed two related integration problems in one
resumed vault-system interaction. The agent streamed a six-operation record
through interactive pseudo-terminal input, which truncated the JSON at 4096
bytes. Atomic validation prevented a partial write, but the compressed retry
applied four operations and omitted two largely redundant node refreshes. After
that successful checkpoint, the project-required MacBook volume check and
spoken alert advanced the observed tool generation from 23 to 25. The Stop hook
correctly required a deliberate empty corrective checkpoint, revealing that an
audio-after-checkpoint instruction conflicts with the finality contract.

Commit `689b1f3057d89ababdf10be800a459ed644e457b` makes the transport and ordering
rules executable and explicit:

- `record --file -` rejects interactive terminal stdin before reading it and
  directs the caller to a non-interactive pipe, heredoc, or existing payload
  file;
- injected context and the durable skill require audio, clipboard writes,
  notifications, cleanup, and all other tools before the final record;
- an automated record test commits a valid payload larger than 4096 bytes
  through non-interactive stdin, while a separate test rejects TTY stdin;
- the fast `PreToolUse` path now closes its SQLite connection explicitly.

`make validate` passed with 104 Python tests, all Go suites, 17 frontend tests,
the production frontend build, both generated packages, notices, and all three
official host-validator groups. Focused tests and Go builds also passed from the
pinned worktree on both machines. The independently built archives were
byte-identical across DirkOS and the MacBook:

| Package | SHA-256 |
|---|---|
| Codex | `5a1f2c6b32870875c4d1baa64e61caf8c34fcb152209ea61c5204a704c3d19a7` |
| Claude | `e7d75cb974bc98cd89f4111383ffdb747b7d379696f534ff27dc1c93ac821563` |

Both local marketplaces now point at persistent detached
`mindmap-canary-689b1f3` worktrees. Each installed Codex and Claude cache
matches its generated host package exactly. Both integration and doctor checks
pass, and installed runtime probes reject TTY stdin immediately while parsing a
greater-than-4-KiB non-interactive payload completely. The Go CLI hashes remain
unchanged because this revision changes the bundled Python agent runtime and
guidance, not the management CLI.

Fresh online backups were taken before installation and passed
`PRAGMA integrity_check`:

| Machine | Backup | Backup SHA-256 | Pre-install boundary |
|---|---|---|---|
| DirkOS | `/home/dirk/.local/share/mindmap/mindmap-before-689b1f3.sqlite3` | `536cc38acfd89af8f44a6cb59606c145f7c96e2557f60f5a79c599a775246c4d` | `2026-08-31T15:56:40+01:00`; turn 613; event 1655; completed output 543; checkpointed 582 |
| MacBook | `/Users/dirk/.local/share/mindmap/mindmap-before-689b1f3.sqlite3` | `571db303f0575058c672c06c2e66352b915cda5cc584c43fb1d1ce889ea31bf2` | `2026-08-31T15:56:40+01:00`; turn 30; event 128; completed output 29; checkpointed 30 |

The revised canary starts at `2026-08-31T15:58:47+01:00`. DirkOS measurements
must use `turns.id > 613` and `events.id > 1655`; MacBook measurements must use
`turns.id > 30` and `events.id > 128`. The earliest eligible review is now
`2026-09-07T15:58:47+01:00`. The revised canary completes only after both
conditions hold:

1. at least 50 post-boundary DirkOS turns contain non-empty final assistant
   output, with a representative post-boundary MacBook sample;
2. at least one week has elapsed since the revised start timestamp.

All agent processes that began before the revised installation are excluded.
Close and resume each active Codex and Claude session before treating later work
as evidence for `689b1f3`.

## Superseded initial boundary

| Field | Baseline |
|---|---:|
| Start | `2026-08-31T00:47:59+01:00` |
| Earliest eligible review | `2026-09-07T00:47:59+01:00` |
| Highest existing turn id | 506 |
| Highest existing event id | 1487 |
| Existing projects | 17 |
| Existing sessions | 79 |
| Existing turns | 506 |
| Existing turns with completed output | 478 |
| Existing checkpointed turns | 475 |
| Existing trailing unresolved turns | 8 |

The historical counts describe the starting database only. Canary rates must
use `turns.id > 506` and `events.id > 1487`; otherwise old missing checkpoints
would be incorrectly attributed to the candidate.

The initial `fecbcce` phase would have completed only after both conditions held:

1. at least 50 post-boundary turns contain non-empty final assistant output;
2. at least one week has elapsed since the start timestamp.

## Measures

Report these separately for Codex and Claude and in aggregate:

- completed-output turns, checkpointed completed-output turns, and coverage;
- unresolved completed-output turns, with each failure classified;
- `turn.checkpoint_invalidated` counts by reason;
- post-checkpoint invalidations that did and did not receive a later successful
  checkpoint on the same interaction;
- distribution of saved and final tool generations, including the last tool;
- semantic warnings by code and project, with manual true/false-positive review;
- prompt-context bytes and node count for active projects;
- sampled node creation timing, state transitions, settled resumes, redundant
  concepts, and distinct side-branch retention.

The target is 100% checkpoint coverage for completed output, excluding only an
explicitly reproduced and classified host denial. Every observed
`post_checkpoint_tool_activity` invalidation must be followed by a successful
corrective checkpoint. No new stale settled action, lost material branch, or
durable state transition may survive beyond the next interaction.

The semantic sample must include both hosts and at least one turn with tool work
after an initial checkpoint. It should also inspect every new warning and every
Claude turn that creates more than one concept. The remaining known risk is
Claude promoting concrete contradictory evidence into a redundant child while
also transitioning the existing concept correctly.

## Review sequence

1. Freeze a read-only database copy and record its digest.
2. Calculate the post-boundary operational measures without raw transcript text.
3. Inspect every failure, invalidation, and semantic warning in CASS and the
   corresponding map history.
4. Complete the independent blinded cold read from the retained trial-1 packet.
5. Repeat the full cross-project CASS audit, including sessions created during
   the canary.
6. Decide whether to retain the candidate, tighten the Claude resolution rule
   behind a new holdout fixture, or roll back the canary package.
