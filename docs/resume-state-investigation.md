# Resume-state and local session coverage investigation

This investigation addresses #17 and the duplicate #22. It distinguishes stale resume guidance from expected tracking limits, and adds bounded corrections and regression coverage. The cases below retain the technical failure, evidence type and expected outcome. Private project identities, map identifiers, session records and detailed chronology are omitted.

The original investigation checked the cases against installed v0.3.1 and existing fixes. All five remained stale at that check. Production maps were not rewritten, and the changes described here have not been released or installed for normal use.

## Resume-state cases

| Case | Before | Source evidence | Expected outcome | Failing layer or boundary |
|---|---|---|---|---|
| A: started phase | A phase remained planned after a later checkpoint added an open child; related resumes still described completed preparation and the first working session as future work. | The source conversation reported that work had started, and its checkpoint recorded the new child without reconciling related concepts. | Open the started phase, settle completed preparation, and replace stale ancestor and sibling resumes. Keep remaining acceptance work and later phases unfinished. | Agent reconciliation at record time; context lacked a warning about the planned parent. |
| B: completed remote handoff | A handoff remained planned after the receiving project completed it on another machine. | Completion was recorded only in the receiving project; no later source-root session received it. | Settle the handoff with the received result while retaining the broader open goal. | Completion evidence does not cross project or machine boundaries automatically. |
| C: completed local handoff | Handoff and prerequisite concepts still asked for work completed in another project on the same machine. | The receiving project recorded completion, but no later source-root session received that evidence. | Settle the completed concepts and refresh their resumes; retain unrelated planned follow-up work. | Evidence remains scoped to the receiving project. |
| D: missing return evidence | A handoff remained open despite later sessions under the source root. | The receiving project had recorded the requested result, but the later source conversations did not contain it. | Settle the handoff once the source conversation receives the result; preserve the receiver's separate remaining work. | A later source session cannot reconcile evidence it has not received. |
| E: partial return | A handoff still said that no outcome had returned. | Another project recorded a verified partial result and explicit remaining follow-ups. | Record the partial result on the existing handoff, keep it open, and identify what remains. | Cross-project evidence boundary plus the need to distinguish partial from complete delivery. |

The warning `planned_parent_after_child_activity` detects an open or settled child's creation, state change or settlement after its planned parent's last revision. Same-checkpoint preparation, wording edits and reparenting of older children are counterexamples. The check is advisory: it does not change the map. A broader check for any non-planned child was rejected because preparatory decisions can legitimately coexist with planned work.

Item timestamps are shared within a checkpoint, while provenance events receive individual timestamps. The warning compares record identity, including the payload digest, so clock advancement within one record does not look like later work. Tests cover both operation orders, new and existing parents, later wording edits, and a later checkpoint within a reused interaction.

The injected context and management skill tell the agent to reconcile started phases, completed prerequisites and returned handoffs in the same checkpoint. They also preserve broader unfinished goals and paused branches. Mindmap does not transport evidence between projects; handoff reconciliation requires that evidence in a source-root conversation.

## Session coverage

Sessions were correlated by host identity, runtime and session identity, then compared with active roots and checkpoint records. Sessions outside active registered roots were expected non-coverage. A separate class of nonpersistent utility runs beneath an active root was attached but could never checkpoint under its execution contract.

A minimal isolated reproduction uses an active project with an ephemeral Codex run, a read-only sandbox and a constrained output schema. Before the fix, it created an attached session and turn, counted tool activity and retained final output, but recorded no checkpoint. It also kept no transcript for later reconstruction. After the fix, the same run leaves no session row by default; explicit opt-in restores tracking.

Payload probes against Codex 0.154.0 observed `transcript_path: null` for ephemeral runs and a rollout path for persistent runs. The permission field did not distinguish the read-only sandbox. Automatic exclusion therefore uses persistence: an unattached Codex session with a present null or empty transcript path is excluded; an absent field is not treated as proof of nonpersistence.

`MINDMAP_TRACKING=off` opts a launcher out, and `MINDMAP_TRACKING=on` opts it in. Explicit management actions still work. An attached session retains tool counting and checkpoint enforcement, including after launcher opt-out. The evaluation harness explicitly opts in because it uses nonpersistent sessions.

Claude Code probes against 2.1.268 observed `CLAUDE_CODE_ENTRYPOINT=sdk-cli` in hooks launched by `claude -p`; Mindmap neither reads nor stores this signal. Claude Desktop's value was not verified, so no Claude execution-mode exclusion was added. Launchers can use the explicit tracking override.

## Validation and limits

- The reviewed implementation passes all 114 Python tests in an isolated Linux checkout. On macOS, three existing filesystem assumptions fail: two case-insensitive directory collisions and one temporary-path alias comparison.
- Go and desktop server-tag tests pass with a canonical temporary directory and `TERM=xterm-256color`. All 17 frontend tests, the frontend build, package reproducibility, notices and three host validator groups pass.
- An isolated subprocess probe passes 48 combinations of host, transcript field, launcher policy and explicit invocation. It also checks tool counting and checkpoint invalidation after an attached session opts out. These synthetic payload checks do not establish a live host contract.
- Deterministic reliability cases pass 11/11. The checkpoint-finality comparison remains 6/8, with no false positives and two known false negatives.

Two semantic fixtures cover the reconciliation behavior: `planned-parent-transition` starts a validation phase while preserving later work; `handoff-completion-reconciliation` records a partial return before settling a completed handoff while preserving the source project's unfinished work.

The historical live evaluation ran three trials per fixture and host on a dirty working tree, using Codex `gpt-5.6-sol` and Claude `sonnet`. Offline rescoring with scorer v5 gives Codex 6/6 and Claude 5/6, with all 12 trials executed and checkpointed. The Claude miss added a redundant settled child despite the expected state and resume transitions.

Two fixture details were revised after inspecting retained graphs: the partial-return prompt made an unmet delivery dependency explicit, and the completion step allowed a refreshed summary on a still-open concept. Those graphs were rescored without new model calls. Subsequent warning and attached-session corrections were tested deterministically. Fixture commit identifiers and test timestamps were also replaced with synthetic values for public delivery, preserving their format and timing relationships.

A fresh isolated Codex evaluation then used clean source `2924390`, the reviewed generated package, the final redacted fixtures and unchanged scorer v5. Codex CLI 0.154.0 with `gpt-5.6-sol` passed three trials per fixture: **6/6 trials and 9/9 steps**, each with a new checkpoint. All nine sessions ran sequentially without retries or changes to fixtures, expectations, scorer or package. Temporary projects, maps and a temporary plugin installation kept the run separate from normal use.

The full historical and fresh reports are not a controlled before/after comparison: the historical package was dirty and its graphs were rescored offline, host coverage differs, and the handoff fixture digest changed. The matching Codex planned-parent subset passes the existing comparison checks, with 3/3 trials on each side and no metric regression; the historical provenance limits still apply. The Claude evaluation has not been rerun; its historical 5/6 result includes the known miss. This small Codex-only sample does not establish broader reliability or a fresh Claude result. Detailed evidence remains outside the public repository.

The changes provide source-level corrections and guidance. They do not repair existing production maps, deploy integrations or guarantee semantic reconciliation in every agent run. Installation and source-root reconciliation remain separate delivery steps.
