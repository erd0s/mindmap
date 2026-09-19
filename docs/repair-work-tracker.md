# September repair: work tracker

Start with the [GitHub project](https://github.com/users/erd0s/projects/2) or [tracker #40](https://github.com/erd0s/mindmap/issues/40). The project contains 17 issue/PR items with explicit status and delivery order, plus views for the delivery board, current review, completed work, and next/blocked work. The `repair-2026-09` label also groups the repository issues.

The local candidate is version 0.3.2, based on `649343675bc8da9ecb137dfed73557e2c44f95e0`. It is implemented and deterministically verified. The candidate comparison is complete; semantic review and one Codex recovery coverage gap remain. No source push, merge, release, live installation replacement or production-map rewrite was performed in this task.

| Stage | Work |
| --- | --- |
| Done | [#31 Audit baseline and protocol decision table](https://github.com/erd0s/mindmap/issues/31); [#32 local validation and reproducible review packages](https://github.com/erd0s/mindmap/issues/32). |
| Earlier work merged | [PR #23 resume-state and nonpersistent-session fixes](https://github.com/erd0s/mindmap/pull/23). [#17](https://github.com/erd0s/mindmap/issues/17) and its documented duplicate [#22](https://github.com/erd0s/mindmap/issues/22) remain linked as original context. |
| Implemented locally | [#24 bounded context and retrieval](https://github.com/erd0s/mindmap/issues/24), [#25 corrections and retries](https://github.com/erd0s/mindmap/issues/25), [#26 validator-derived guidance](https://github.com/erd0s/mindmap/issues/26). These issues remain open pending review and delivery. |
| Comparison complete | [#35 candidate comparison](https://github.com/erd0s/mindmap/issues/35): selected the explicit prepare/commit protocol and incorporated warning, UTF-8, stale-replay and migration safeguards from the separate PR. See [candidate review](repair-candidate-review.md). |
| Current review | [#33 semantic failures](https://github.com/erd0s/mindmap/issues/33): fixed ambiguous matching but retained the real unchanged-receiver failure. |
| Recovery review | [#34 autonomous Stop recovery](https://github.com/erd0s/mindmap/issues/34): controlled cases 18/18, boundary checks 4/4, and real later tools on Claude 3/3. Codex reordered the tool before its checkpoint in 3/3 trials, leaving that particular path unexercised. |
| Gated delivery | [#36 release](https://github.com/erd0s/mindmap/issues/36), then [#37 backups, four installations and fresh-process verification](https://github.com/erd0s/mindmap/issues/37), then [#38 bounded canary](https://github.com/erd0s/mindmap/issues/38). Each step retains its review and authorization prerequisites. |
| Separate map follow-up | [#39 authorized source-root reconciliation](https://github.com/erd0s/mindmap/issues/39). This is not permission for bulk map changes or cross-project synchronization. |

The existing [draft PR #27](https://github.com/erd0s/mindmap/pull/27), head `559968aa0e33f789f476373e2d8f93e9ef1dcb39`, contains a separate implementation of #24-#26. Its checks apply to that head. The [comparison](repair-candidate-review.md) selected this local candidate and incorporated the additional safeguards. The draft PR remains unchanged and unmerged.

The project is private and linked to the repository. It was created using the existing authorized GitHub login on DirkOS, without changing credentials or granting new permissions. All 17 entries, statuses and order values were read back and verified. The saved roster and verification are in `build/repair-qualification/github-project/`. The completed audit, validation and candidate-comparison tasks (#31, #32 and #35) are closed; the existing bug issues remain open and are marked Implemented locally in the project until review and delivery are decided.

See [repair qualification](context-checkpoint-repair.md) for results and limits, and [checkpoint protocol](checkpoint-protocol.md) for the implementation contract. Initial evidence remains under `build/repair-qualification/`; final comparison, recovery reports, source/package manifests and ZIP checksums are under `build/repair-followup-2026-09-19/`.
