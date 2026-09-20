# September repair: candidate review

The local 0.3.2 implementation is the selected basis for the repair. It implements the handoff's explicit correction protocol and bounded retrieval. The separate draft [PR #27](https://github.com/erd0s/mindmap/pull/27), reviewed at `559968aa0e33f789f476373e2d8f93e9ef1dcb39`, supplied additional failure cases incorporated here. Both candidates descend from `649343675bc8da9ecb137dfed73557e2c44f95e0`. This source review does not merge, close or replace the draft PR.

## Comparison and disposition

| Concern | Draft PR #27 | Selected local implementation |
| --- | --- | --- |
| Correction intent | Classifies intervening shell work and accepts a different payload after qualifying work. | An explicit current checkpoint token authorizes reconciliation. A command's own counter increment cannot authorize a conflicting repeat. |
| Pure retry | Recognizes selected literal record/heredoc/printf forms and maintains several activity counters. | Matches the entire immutable registered commit command. No shell parsing; unknown, compound and background forms remain ordinary activity. |
| Identical empty corrections | Requires a new summary after invalidation to distinguish a replay. | A new prepared request or explicit superseding token distinguishes deliberate reconciliation without changing the JSON digest. |
| Replay after reopening | Rejects an old committed digest. | Incorporated this safeguard for bare records. New preparation can deliberately acknowledge unchanged work; old prepared requests remain invalid. |
| Stop/correction race | Compares a saved checkpoint during invalidation. | Reads freshness and invalidates within one write transaction, serializing against correction and retry coverage updates. |
| Automatic budgets | Prompt/SessionStart 8,192 bytes; Stop 3,072. | Prompt 8,192, SessionStart 4,096, Stop 2,048, including serialized envelopes. |
| Retrieval | Directs omitted context to a complete snapshot. | Paged inventory, roots, children, individual concepts and notices, each bounded to 16,384 bytes. Complete snapshot export remains deliberate. |
| Selected text | Truncates prose previews, retaining identities. | Omits complete fields when necessary; keeps exact IDs, revisions and parent links. Reserves a bounded root overview and prioritizes the requested concept. |
| Warnings | Reserves space for five exact warning codes and IDs. | Incorporated a five-warning, 1,024-byte reservation before optional concept prose. Full details remain available through bounded notice retrieval. |
| Character transport | Writes hook output as UTF-8 independently of the terminal encoding. | Extended this safeguard to both hook input/output and bound CLI commands. Packaged tests use ASCII, CP1252, UTF-16 and UTF-8 host settings. |
| Migration | Preserves unknown activity from old writers and before migration. | Added a regression and fix preserving the raw fast-hook increment when request tables do not exist yet. Absent metadata never proves a retry. |
| Validation | PR reports Linux tests and its own review/checks. | Full local gate, repaired Mac fixtures, model trials and isolated real-host recovery evidence apply to the exact local artifacts. PR checks are not counted as checks of this candidate. |

The repair keeps complete graph storage, optimistic item revisions, user-deletion protection, transactional rollback, explicit stop behavior, and one Stop recovery pass. Choosing explicit requests avoids depending on heuristics that infer whether arbitrary shell text constitutes real work.

## Semantic qualification review

The original scorer-5 sample remains recorded as 40/42. Inspection found one genuine unchanged-receiver failure and one ambiguous selector: the explorer's resume mentioned Avery's handoff, even though a separate completed handoff node existed with the correct parent and state.

Scorer 6 separates identity from references. The workforce handoff selector searches ID/title; it still rejects a missing handoff or duplicate handoffs. The pre-existing parser handoff is selected by its fixed ID, and separate required-content checks retain the parser/sidecar evidence requirement. State, parentage, node-count limits, deferred-plan checks and unchanged receiving fields remain enforced. Tests prove that a cross-reference cannot satisfy a missing deliverable and that the real receiver rewrite still fails.

Rescoring also exposed whitespace normalization in the offline seed helper: fixture input contained trailing spaces that the real store trims. The helper and reference snapshots now reproduce stored text. No model-created field is normalized away during comparison. The retained sample rescores to Codex 21/21 and Claude 20/21; the unchanged-receiver failure remains. The same-model baseline retains its Claude handoff failure, so that failure is neither newly excused nor hidden by the scoring repair.

A fresh bounded comparison used three trials per selected handoff/workforce fixture per host, with frozen runtime/packages and scorer 6. All outcomes, including failures, remain in the local follow-up evidence. [Issue #33](https://github.com/erd0s/mindmap/issues/33) led to the narrower editing guidance and further qualification recorded in the [closeout](repair-closeout.md). A small green sample does not prove that the known failure mode is impossible.

## Recovery qualification method

`scripts/test_stop_recovery.py` copies both host packages and both marketplace definitions into a temporary location. It uses disposable maps and host configuration. A test-only wrapper invokes the real generated hook and records the host adapter, payload, response, checkpoint metadata and graph digest. It is not shipped in either plugin.

Controlled faults exercise missing checkpoint metadata, a later tool generation and the legacy zero-generation age fallback. A separate case now explicitly induces the ordering fault through the disposable copy's initial test context, then requires a real shell tool after an accepted checkpoint. No finality metadata is injected in that case, and production Stop responses remain unchanged. Boundary cases cover explicit-stop deactivation and deliberately stale recovery. Checks require a new prepared receipt without `--supersedes`, one bounded recovery block, retained graph revisions and final response, and an accurate unresolved count. The [closeout](repair-closeout.md) explains why the original user-prompt setup could not exercise this path on Codex.

The first exploratory copy omitted the Codex marketplace definition, allowing Codex to load the Claude adapter. Those runs were stopped/excluded from qualification, retained with their exclusion reason, and followed by an explicit adapter assertion. The semantic harness used the complete checkout and was not affected by this copy error.

These trials measure whether a model follows recovery under a known condition. They do not measure natural failure incidence or live-installation reliability. Final results, hashes and release limits are recorded in [the qualification report](context-checkpoint-repair.md).
