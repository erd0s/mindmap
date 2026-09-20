# Closing the two remaining repair issues

Subsequent release and rollout status is recorded in [v0.3.2 release qualification](release-qualification-v0.3.2.md). The local investigation and qualification evidence below remains historical.

This follow-up to local commit `fb2fef20295fb56998de1c5c8eebcfb7f704489d` addresses the unwanted receiver edit in [#33](https://github.com/erd0s/mindmap/issues/33) and the unexercised Codex recovery case in [#34](https://github.com/erd0s/mindmap/issues/34). It changes semantic guidance and the isolated recovery fixture. The checkpoint protocol, revision checks and single recovery pass remain the same.

## Unchanged receiving branches

The retained failure added upstream parser status to a receiving branch's summary and resume, although the request said that branch was unchanged. Keeping its state open was insufficient: the model still rewrote its text.

The compact prompt contract now says to edit only durable concepts and fields changed by the turn and leave explicitly unchanged branches untouched. The longer guidance and shared skill explain that received evidence belongs on the handoff itself. Ancestor or sibling resumes still change when their existing next action becomes stale; extra background alone is not a reason to rewrite them. The compact rule remains within the initial checkpoint contract budget.

The original handoff fixture and scorer 6 expectations are unchanged. A new diagram-delivery fixture checks the same rule with different concepts and preserves the goal, receiver and deferred branch across both partial and completed delivery. Tests retain the distinction between preserving an unchanged branch and clearing a genuinely stale resume.

The first targeted sample passed 12/12 trials: the original case and new fixture, three trials each on Codex and Claude. All 24 turns checkpointed. Every branch explicitly marked unchanged retained its original fields; the reports also retain revisions for inspection.

The broader sample then passed 34/36 trials, exposing two further Claude scope failures: an unrelated one-off answer became a new concept, and completed work already represented by a goal became a duplicate child with its handoff reparented beneath it. Those failed reports remain intact. Guidance now calls for an empty delta for unrelated one-off questions with no lasting decision or follow-up, and recording completion on the existing concept rather than inserting a duplicate. Meaningful independent side quests and handoffs remain required. The final qualification repeats all eight selected fixtures with these changes; no fixture expectation or scorer was relaxed.

The final sample passed **48/48 trials**, 24 per host, with all **66 turns checkpointed** and no Stop recovery needed. Each host ran three trials of the original handoff, new dependency-update scope, unrelated request, planned-parent transition, stale-resume reconciliation, causal-parent independence, dense main-work/side-quest and large-map retrieval fixtures. This checks both restraint on unchanged work and necessary state/resume updates. The new dependency fixture's unchanged branches retained revision 1 throughout both steps on both hosts.

## Codex recovery after a real later tool

The earlier test asked Codex to violate the hook's final-tool rule through a lower-priority user prompt. Codex correctly moved the marker command before its checkpoint, so those three runs never reached the intended failure condition.

The revised fixture explicitly induces that ordering fault in the **initial test context of the disposable package copy**. The exception ends at the first Stop. Shipped guidance still requires the checkpoint to be the final tool; the real plugin supplies the recovery response without alteration. Package validation now verifies the generated Python hook against the canonical entrypoint so a test wrapper cannot silently become a release artifact.

For a successful test, the host must accept a prepared checkpoint, execute the marker shell command as a separate later tool, receive one stale-checkpoint Stop response, prepare without `--supersedes`, commit a new receipt and finish. The harness checks the marker file, the real PreToolUse payload, checkpoint identity and counters before and after that hook, unchanged graph revisions, and final-response capture. It never increments finality metadata in this real-tool case. Negative tests reject reordered tools, missing execution, injected counter changes, intervening corrections and altered Stop feedback.

Real-tool recovery passed 6/6 trials, three per host, on both guidance candidates. The final candidate recovered in 9.99–13.28 seconds, with at most 1,697 serialized UTF-8 bytes of Stop feedback. Explicit-stop recovery and deliberately stale recovery passed another 4/4 boundary trials, one of each per host; their largest response was 1,809 bytes. The stale-recovery case retained one unresolved checkpoint and emitted no second recovery block. The successful exploratory Codex probe is retained separately from these declared samples.

This is controlled fault qualification. It establishes that both hosts follow the production recovery path when the fault occurs; it does not estimate the frequency of that fault in live sessions.

To repeat the real-tool case, build the local packages and run `PYTHONPATH=src:. python3 scripts/test_stop_recovery.py --host both --case actual-later-tool --trials 3 --output build/stop-recovery/real-tools.json`. Select `--case explicit-stop --case recovery-failure --trials 1` for the boundary sample. These commands use disposable stores and temporary host configurations.

## Reproducible local evidence

Evidence is retained under `build/repair-closeout-2026-09-20/`. The top-level reports and `frozen-inputs.json` retain the first guidance candidate, including its broad-sample failures. The `final/` reports and `final/frozen-inputs.json` identify the final runtime, generated packages, skill, fixtures, scorer and harness. Each candidate's runtime and semantic inputs remained unchanged throughout its qualification. `review-artifacts.json` identifies the final local commit and package hashes.

The first candidate and isolated preceding-commit comparison used Codex CLI 0.155.1 with `gpt-6-astra` and Claude Code 2.1.277 with configured `fable[1m]`, resolved to `claude-fable-5-1`. That baseline handoff comparison passed 5/6 trials: Codex 3/3 and Claude 2/3. Claude's failed partial-return trial rewrote the unchanged receiver's resume. The first candidate passed 6/6 on that same fixture with those hosts and models.

Claude updated to 2.1.278 before the final qualification; Codex stayed at 0.155.1 and the configured models were unchanged. The final reports record those host versions. They qualify the final local inputs on the available hosts, rather than isolating guidance as the sole cause of differences between samples. Earlier failures remain in their original reports; fresh successes do not erase them or establish a statistical reliability rate.

The final Python suite passes 155/155, with no skipped or waived failures. Go packages, desktop service tests, the 17 frontend tests and frontend build pass. The reliability evaluator remains 12/12; the frozen finality comparison remains 6/8 with its two documented false negatives. Package content/reproducibility checks, notice checks and all three host-validator groups pass. Both plugin ZIPs reproduce byte for byte, and all frozen model inputs match after the rebuild. These checks were run individually so package rebuilding could wait until live model trials finished.

The final context profile used the existing disposable graphs, including 1,001 concepts and 10,000 extra provenance events. Maximum serialized sizes were 8,082 bytes for prompts, 3,779 for SessionStart and 1,617 for Stop, within their 8,192/4,096/2,048-byte limits. Maximum measured preparation times were approximately 0.15, 0.14 and 0.006 seconds respectively on this Mac; these are observations, not performance guarantees.

No code is pushed, merged or released by this closeout. Live installation replacement, a fresh-process canary and production-map reconciliation remain separate project items.
