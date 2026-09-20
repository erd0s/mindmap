# September repair: work tracker

Use the [GitHub project](https://github.com/users/erd0s/projects/2) and [tracker #40](https://github.com/erd0s/mindmap/issues/40) for current status and delivery order. The private project is linked to the repository and includes completed work, the selected implementation, the superseded draft and the remaining rollout tasks.

The repair is merged in [PR #41](https://github.com/erd0s/mindmap/pull/41), release commit `fb2d09006080fd9f31222df44f8a51c47a9e6d49`. Version 0.3.2 contains the implementation and qualification completed locally at `894bd7c`, plus the release changelog. See [release qualification](release-qualification-v0.3.2.md) for publication evidence and the live-installation boundary.

| Stage | Work |
| --- | --- |
| Done | [#31 audit/protocol baseline](https://github.com/erd0s/mindmap/issues/31), [#32 reproducible validation](https://github.com/erd0s/mindmap/issues/32), and [#35 candidate comparison](https://github.com/erd0s/mindmap/issues/35). |
| Merged | [#24 bounded context/retrieval](https://github.com/erd0s/mindmap/issues/24), [#25 corrections/retries](https://github.com/erd0s/mindmap/issues/25), and [#26 validator-derived guidance](https://github.com/erd0s/mindmap/issues/26), through PR #41. Earlier resume-state and nonpersistent-session fixes came through [PR #23](https://github.com/erd0s/mindmap/pull/23). |
| Done | [#33 semantic scope repair](https://github.com/erd0s/mindmap/issues/33): final 48/48 trials and 66 checkpointed turns, preserving the existing expectations. |
| Done | [#34 autonomous Stop recovery](https://github.com/erd0s/mindmap/issues/34): 6/6 real-tool trials across both hosts plus 4/4 recovery boundary checks; production Stop feedback unchanged. |
| Published | [#36 reviewed v0.3.2 artifacts](https://github.com/erd0s/mindmap/issues/36): signed preflight and the independent tag release workflow passed at the same commit. Downloaded checksums, pinned provenance and macOS signatures were verified. |
| Next, awaiting host shutdown | [#37 installation and fresh-process verification](https://github.com/erd0s/mindmap/issues/37): authorized, with consistent backups prepared. Mac Codex was observed at 0.3.2 outside the explicit installer; its removed 0.3.1 cache was restored for existing sessions. The other three installations remain at 0.3.1. Finish and quit affected processes, complete the cutover, then verify all four installations and fresh-process hooks. |
| After installation | [#38 bounded canary](https://github.com/erd0s/mindmap/issues/38): synthetic workload first, then a bounded real-session sample with explicit denominators and stopping conditions. |
| Separate follow-up | [#39 source-root map reconciliation](https://github.com/erd0s/mindmap/issues/39): production-map changes remain separately scoped. |

The separate [draft PR #27](https://github.com/erd0s/mindmap/pull/27), reviewed at `559968aa0e33f789f476373e2d8f93e9ef1dcb39`, was closed as superseded after PR #41 merged. Its branch and worktree are retained. The [comparison](repair-candidate-review.md) explains the selected protocol and incorporated safeguards. Original investigation [#17](https://github.com/erd0s/mindmap/issues/17), documented duplicate [#22](https://github.com/erd0s/mindmap/issues/22), PR #27 and tracker #40 remain references.

Local implementation and bounded qualification are complete. Publication does not imply that every active session has switched runtime or that the live canary has passed. The observed partial cache transition and restored compatibility path are recorded in [release qualification](release-qualification-v0.3.2.md). No running host was terminated and no production map was rewritten by the release task.

Historical evidence remains under `build/repair-qualification/` and `build/repair-followup-2026-09-19/`. The [closeout](repair-closeout.md), including retained failed samples, is under `build/repair-closeout-2026-09-20/`; final model reports are in its `final/` directory. Release verification, backups metadata, project readback and prepared cutover instructions are under `build/repair-release-2026-09-20/`.
