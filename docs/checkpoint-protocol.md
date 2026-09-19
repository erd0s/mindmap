# Bounded context and checkpoint protocol

Automatic delivery has a fixed envelope: 8,192 UTF-8 bytes for prompts, 4,096 for SessionStart, and 2,048 for Stop recovery, including JSON serialization. The essential checkpoint contract comes first. Selected history is evidence to reconcile against the current request, never authorization to resume unrelated work. Full storage and deliberate snapshot export remain available.

## Recording decision table

A prepared request stores immutable JSON, its turn and prompt version, the observed tool generation, and the checkpoint token it explicitly supersedes. Preparation does not accept a checkpoint. Its returned commit command is a literal, registered command; hosts can correlate that command without interpreting arbitrary shell programs.

| Request | Result |
| --- | --- |
| First prepared commit, only its own registered commit calls since preparation | Atomically validate, mutate, and checkpoint current observed generation. |
| Repeat the same registered commit, with no intervening unclassified activity | Return the same receipt; refresh coverage without duplicate events or mutations. |
| Different ordinary payload for a checkpointed turn | Reject, even when its own invocation advances the counter. |
| Deliberate correction with the current checkpoint token | Accept a delta against current item revisions before Stop. |
| Old identical payload after actual work | Replay does not acknowledge that work; a prepared retry rejects stale coverage. |
| Explicit empty correction | Accept and retain a distinct audit event, even with an identical digest. |
| New prompt under the same interaction | Retain prior mutations, reopen, and reject requests prepared for the earlier prompt. |
| Bare old payload after Stop or prompt reopening | Reject without mutation or checkpoint. A newly prepared request can explicitly reconcile even identical empty JSON. |
| Invalid operation, stale item revision, competing correction | Roll back; retain the previous checkpoint and its detectable staleness. |
| Stop decides to invalidate an older checkpoint while a correction commits | Read freshness and invalidate in the same transaction as competing commits; do not invalidate a newer receipt or retry coverage refresh. |
| Direct record without host activity | Preserve zero observed coverage and the legacy age fallback. |

Only a supported shell tool whose entire command exactly equals the registered commit command is classified as a commit invocation. Bundled commands, background execution, unknown tools, or extra shell syntax count as ordinary activity. Tool events remain counted even if the command fails. Unobserved hosted activity and asynchronous work completing after preparation remain observation limits: finish and join work before preparing.

The direct `record` interface remains available. A correction uses `--supersedes TOKEN`; this is an explicit acknowledgement of reviewed work, not permission inferred from a counter difference. Ordinary exact payload replay remains mutation-idempotent but cannot refresh tool coverage without correlation. Use the prepared command for transport retries, including when its first response was lost.

If Stop has already invalidated a stale checkpoint, its token is cleared. Review the later work and prepare a fresh request without `--supersedes`; prior map mutations remain. Stop gives this recovery one pass. A bare replay of a previously committed payload cannot acknowledge a reopened turn; preparation distinguishes deliberate reconciliation without requiring an artificial summary change.

Storage changes are additive tables and nullable turn metadata. The fast hook preserves raw activity if it runs before the first full migration creates request tables. Existing Go readers use named columns and continue to read complete graphs. Old Python writers cannot enforce the new request protocol; do not mix runtime versions during a deployment. Installation and publishing are separate from this local repair.

## Retrieval and delivery

The injected command prefix is bound to project, host, session and interaction in SQLite. Its private shell file invokes the pinned local interpreter/runtime and database; long paths and identities stay out of the model-visible command. SessionStart and retained inactive status use read-only bindings with no invented prompt identity. Start and sync still require full transcript reconstruction; legacy maps still require explicit causal reconciliation.

`read` returns at most 16,384 UTF-8 bytes including its trailing newline. Select `--roots`, `--parent ID`, `--id ID`, or `--notices`; no selector pages the full concept inventory. Copy `next_cursor` into `--cursor` with the same selector. Each page uses one read transaction, and the cursor fingerprints items, warning content, and tombstones. Concurrent changes require restarting the read; exact item revisions independently protect writes. A legacy individual record that exceeds the page budget directs the caller to deliberate snapshot export. Current validator-bounded concept records fit.

Selection is deterministic, with explicit IDs and request-word matches ahead of current-session contributions, unfinished state and update time; ID ties are stable. The root overview has its own 1,024-byte serialized budget so four large roots cannot displace a requested child. It may omit whole titles or roots; `read --roots` provides complete discovery. Exact parent IDs preserve navigation. Selected large concepts may omit summary/resume as complete fields, with an explicit "Fields omitted" notice. A requested deep concept has priority over the full text of its ancestors. Warning text that refers to many started children gives a bounded set and a count of additional children; `read --parent ID` retrieves them. Up to five exact warning codes and IDs receive a separate 1,024-byte reservation before optional concept prose; omission counts and bounded notice retrieval retain the complete details. Selection does not mutate the stored graph. Hook and CLI text use UTF-8 independently of the host terminal encoding.

## Storage compatibility and local evidence

Migration adds `turns.checkpoint_token`, `context_bindings`, `record_requests`, and a provenance-query index. Existing checkpoints receive stable tokens without changing their tool coverage. Every deliberate acceptance has a new receipt in event keys, so identical empty corrections remain auditable; genuine retries create no new provenance event. Go viewers continue to use the existing graph and event schema. Migration is additive, but an older runtime does not understand request correlation; do not run mixed hook versions against a turn during deployment.

Command files and prepared JSON are local private data and are retained with their turn. They are not credentials or an authorization boundary. A removed temporary command can be recreated by a fresh hook; never replace its contents with a different binding. Optional `MINDMAP_DIAGNOSTICS_PATH` records local hook context, tool-correlation metadata and retrieval output for qualification. Those diagnostics can contain private map text and should stay local. It adds no model-visible instructions and is disabled by default.

Publishing, live installation replacement, cache verification on both machines, fresh-process canaries and rollback remain separate release steps. Before that step, retain consistent database backups and previous package artifacts, finish active sessions, quit host processes, verify installed file hashes, then test fresh hook/checkpoint/Stop delivery. A matching version alone is insufficient evidence of installed content.
