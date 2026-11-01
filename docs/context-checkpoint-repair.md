# Context and checkpoint repair qualification

Subsequent release and rollout status is recorded in [v0.3.2 release qualification](release-qualification-v0.3.2.md). The local investigation and qualification evidence below remains historical.

This local 0.3.2 candidate repairs automatic context growth, missing validator guidance, and checkpoint correction/retry handling. The reviewed starting commit was `649343675bc8da9ecb137dfed73557e2c44f95e0`; its working tree was clean before implementation. Publishing, live installation replacement, and canary rollout have not been performed.

The [September 20 closeout](repair-closeout.md) records the subsequent fixes and fresh qualification of the two remaining issues, #33 and #34. The earlier samples below remain as historical evidence, including their failures and coverage limits.

## Changed behavior

Automatic context has a complete serialized response budget: 8,192 UTF-8 bytes for prompts, 4,096 for SessionStart, and 2,048 for Stop recovery. The essential decoded checkpoint contract is within the first 1,800 bytes. Stop never renders the map. PreCompact and PostCompact remain silent. Numeric guidance is generated from the same definitions used by the validator, including the formerly literal ID limit.

Ordinary context is an explicitly partial deterministic selection, with root discovery, exact IDs/parents/revisions, relevant settled decisions, and counts of omitted concepts and notices. The requested concept takes precedence over large ancestor text. Omitted fields are disclosed. Historical plans do not authorize unrelated work. Bounded retrieval supplies complete fields, branch discovery, warning/deletion pages, and change-detecting continuation cursors; the full snapshot export remains available deliberately. Reads preserve every stored concept and revision.

A short private command binds the exact database/project/host/session/interaction, including long identities and paths. Preparing JSON returns an immutable commit command. The fast hook recognizes only that entire registered foreground command; retry coverage advances without duplicate writes or provenance. A deliberate correction supplies the checkpoint token it supersedes and can commit before Stop. Ordinary conflicting repeats still fail; old payload replay alone never acknowledges later activity. Revisions, deletion protection, atomic rollback, prompt reopening and the single Stop recovery pass remain enforced. Stop freshness checks and invalidation now share a transaction with competing corrections and retry coverage updates.

See [checkpoint-protocol.md](checkpoint-protocol.md) for the decision table, migration and retrieval contract, [architecture.md](architecture.md) for runtime responsibilities, and [the work tracker](repair-work-tracker.md) for completed tasks and the review/release sequence in GitHub.

## Deterministic verification

The retained Python baseline was 111/114, with three documented macOS fixture failures. This change fixes those fixtures separately: collision tests use distinct physical paths and inject the colliding route; path discovery compares canonical paths. No test is skipped or waived. Go tests also encountered `/var` versus `/private/var` temporary-path failures under the default Mac environment; the complete Go tests pass with a canonical `TMPDIR`.

At `fb2fef2`, the Python suite passed 152/152, including both orderings of tool-activity/commit concurrency. The strict gate passed. Those checks included that Python suite, the reliability evaluator (12/12, including an explicit corrective checkpoint before Stop), Go packages, frontend tests/build (17/17), desktop service tests, package reproducibility/content checks, notice checks, and both host validators. `make validate-strict` passed with `TMPDIR` set to a canonical repository-local temporary directory. Both generated ZIP archives reproduced byte for byte, and the frozen source/package hashes remained unchanged after the gate. A separate shared-schema probe created a Python prepared checkpoint, read it through the Go command, and wrote revision 2 through Python afterward. The closeout adds recovery-harness regressions, bringing the passing Python suite to 155 tests.

The frozen checkpoint-finality predicate comparison is unchanged at 6/8, with zero false positives and two known false negatives. It compares frozen strategies and does not demonstrate complete live observability.

Regression cases cover both generated launchers, Claude activity without a prompt ID, ordinary and prepared retries, explicit corrections and repeated empty deltas, competing corrections, actual Stop/correction races, rollback, session end, deactivation, same-ID steering, long identities/paths, all Stop reasons, explicit stop, compaction, inactive status, warnings/tombstones, exact limits and one over, canonical Unicode payload bytes, paging/change detection, unrelated prompts, deeply nested relevant concepts, and four maximum-size roots competing with an explicitly requested child.

## Context preparation profile

`scripts/profile_bounded_context.py` creates disposable graphs with maximum-length Unicode fields at 0, 21, 101 and 1,001 concepts, then adds 10,000 provenance events to the largest graph. In this local run, the maximum serialized sizes across both hosts were 8,128 bytes for prompts, 3,643 for SessionStart, and 1,617 for Stop. The largest prompt preparation took about 0.16 seconds under Python allocation tracing and peaked near 9.4 MB of traced allocations. Stop peaked near 0.0063 seconds and 144 KB. These are observations from this machine, not timing thresholds or explanations for historical hook timeouts.

Delivery size is bounded; graph selection and provenance queries still scale with stored data. The read path avoids transcript/session exports and does not construct the full map text before trimming it.

## Model-backed qualification

The initial sample is retained unchanged under `build/repair-qualification/`: scorer 5 passed 40/42 trials, Codex 21/21 and Claude 19/21, with all 54 turns checkpointed and no Stop recovery. Models were Codex CLI 0.155.0 with `gpt-6-astra` and Claude Code 2.1.277 with configured `fable[1m]`, resolved to `claude-fable-5-1`. Each selected fixture received three trials per host in isolated stores.

Follow-up review found that the workforce failure was ambiguous matching: the deferred explorer referred to the separate completed handoff. Scorer 6 checks that deliverable's identity in its ID/title and preserves the state, parent, distinct-node and deferred-plan requirements. The existing parser handoff uses its known ID plus separate parser/sidecar content checks. Negative tests retain detection of a missing/duplicated deliverable and an unexpectedly changed receiver. The offline seed helper also now reflects the real store's trimming of input text; model-produced fields are still compared exactly. See [candidate review](repair-candidate-review.md) for the rationale.

The retained sample rescores to 41/42: Codex 21/21, Claude 20/21. The unchanged-receiver failure remains failed. Targeted baseline comparisons at `6493436`, rescored consistently, remain workforce 3/3 per host and handoff Codex 3/3, Claude 2/3. A baseline miss does not waive a candidate miss.

A fresh comparison of the consolidated candidate used scorer 6, the same models and three trials per handoff/workforce fixture per host. It passed 11/12 trials: Codex 5/6 and Claude 6/6, with all 24 turns checkpointed. Codex handoff trial 1 changed the receiving branch's summary and resume during partial return; all other selected trials passed. Results are retained in `build/repair-followup-2026-09-19/semantic-final.json`. The runtime, generated packages, fixture expectations and semantic harness remained unchanged during those runs. That sample kept #33 open for the subsequent guidance repair and qualification described in the [closeout](repair-closeout.md).

## Autonomous Stop recovery

The isolated recovery matrix passed 18/18 trials: missing checkpoint metadata, post-checkpoint tool generation and legacy zero-generation age fallback, three trials per case per host. Every run used the intended host adapter, consumed one real Stop recovery response and committed a new prepared request without `--supersedes`. Prior graph writes and revisions survived. The largest response in that matrix was 1,697 serialized UTF-8 bytes; recovery took 7.43–18.34 seconds from the initial final response to the next Stop.

Explicit-stop recovery passed once per host, disabling tracking after a fresh checkpoint while retaining the final response. Deliberately stale recovery also passed once per host: no second block was emitted, and the unresolved count remained one. These four boundary runs bring controlled recovery checks to 22/22. Their largest Stop response was 1,809 bytes.

A separate real-tool sequence passed 3/3 on Claude. Codex moved the requested shell command before its checkpoint in all three trials, obeying the final-tool rule; its real-post-checkpoint recovery path was therefore **not exercised (0/3 eligible trials)**. Those three setup failures are retained and are not counted as recovery successes. This coverage limit kept #34 in review until the isolated ordering-fault setup was corrected; see the [closeout](repair-closeout.md) for fresh trials on both hosts with unmodified production Stop responses.

Two harness mistakes are explicitly excluded. An early temporary copy omitted the Codex marketplace, so Codex loaded the Claude adapter; it was stopped and an adapter assertion added. Early explicit-stop prompts included explanatory prose, whereas lifecycle commands intentionally require an exact invocation; corrected exact-command trials passed. These were harness setup errors, not silently discarded runtime failures. The original reports remain alongside the corrected results.

To reproduce controlled recovery, run `PYTHONPATH=src:. python3 scripts/test_stop_recovery.py --host both --trials 3 --case missing --case later-tool --case legacy-age --output build/stop-recovery/report.json`. The test wrapper and fault injection are never included in either plugin. These trials establish recovery under controlled conditions, not a production recovery rate.

## Remaining release work and limits

This is a locally committed review candidate, not a published release or installed replacement. The package manifest identifies version 0.3.2; source and package hashes identify the exact local contents. Before installation, review the source, retain consistent SQLite backups and previous packages, finish and quit host sessions, verify every installed file on both machines, and exercise fresh-process hook/checkpoint/Stop delivery. Existing forced-refresh support remains the installation mechanism.

Unknown tool wrappers and bundled/background commands are conservatively treated as ordinary activity. Hosted activity, asynchronous completion after preparation, and commitments that appear only in final prose remain observation gaps. Prepared commands and JSON are private retained local state; active hosts must not be left pointing at a replaced runtime. A legacy individual field/record larger than the bounded retrieval page requires deliberate snapshot export.

The synthetic smoke sample is not a production reliability estimate. Only the dense side-quest and handoff fixtures have targeted same-model baseline comparisons. No live-session canary, billing-savings estimate, or claim about overall coding productivity is made.
