# Mindmap reliability improvement and evaluation plan

## Purpose

This programme improves Mindmap without changing its useful resolution. A node should still represent a meaningful thought, decision, question, plan, or work thread—not a message, command, file, or routine task. The work focuses on whether those concepts appear, change state, and remain resumable at the right time.

The evaluation must answer two separate questions:

1. Did the deterministic lifecycle and storage mechanisms behave correctly?
2. Did the agent produce a faithful, compact causal map from the conversation?

Passing unit tests answers only the first question. Rerunning all production history is useful as a final audit, but it is too slow, subjective, and changeable to be the main development loop. The primary loop therefore uses frozen regression cases derived from production failures, with explicit expected facts rather than exact prose.

## Production baseline

The 2026-08-30 audit is the comparison baseline:

- 15 monitored projects and 76 attached sessions
- 73 surviving transcripts traversed with CASS; three missing paths were zero-turn attachment artifacts
- 460 turns and 430 checkpoints before the audit's own closing checkpoint
- 214 concepts created historically and 210 present at the census
- 66 pre-audit state transitions, which were generally coherent
- nine attempted checkpoint corrections rejected after an earlier checkpoint
- two durable material checkpoint errors
- one malformed top-level payload accepted as a no-change checkpoint
- eight completed Claude responses without checkpoints, seven caused by unattended permission failures

The checked-in baseline fixture records these facts and the deterministic pass/fail state of the mechanisms relevant to them. `make eval-reliability` compares the working tree with that frozen baseline.

## Success measures

### Deterministic protocol measures

Every release candidate must achieve 100% on these measures:

- A valid interaction can checkpoint once and replay the identical payload safely.
- A different payload is rejected unless a new prompt or an explicit reconciliation has reopened that interaction.
- Every distinct same-interaction prompt is retained in order.
- A same-interaction steer invalidates the old checkpoint and allows an incremental correction without losing earlier mutations.
- Missing or unknown record fields are rejected; a deliberate empty `operations` array remains valid.
- A long post-checkpoint window receives one bounded reconciliation pass.
- Concurrent item revisions, explicit deletion tombstones, settle-then-reopen transitions, and causal parent independence continue to work.
- Claude and Codex host adapters pass the same shared lifecycle cases.

### Semantic map measures

Sanitized transcript fixtures label facts, not exact generated wording. Each fixture identifies material concepts, explicit state changes, causal relationships, forbidden chronology, and the point at which a change becomes knowable. A candidate is measured on:

- **Material concept recall:** at least 95% of labelled concepts appear. Release-blocking concepts must have 100% recall.
- **Concept precision:** no transcript-shaped nodes and no more than one unsupported concept per fixture.
- **State accuracy:** at least 95% of labelled states match; release-blocking completion and reopening transitions must all match.
- **Transition timing:** an explicit transition appears in the same interaction. A transition inferred from completed implementation evidence may appear at Stop reconciliation or the next prompt, but may not remain stale beyond one interaction.
- **Causal parent accuracy:** at least 90% of labelled non-root concepts attach to the expected parent or an accepted equivalent.
- **Frontier quality:** every unfinished labelled concept has a usable resume point; no settled node presents an ordinary unfinished action as its current frontier.
- **Compression quality:** message-, turn-, command-, and file-shaped nodes are always rejected. Node count itself is not a quality score.
- **Cold-read recovery:** a reviewer unfamiliar with the transcript can identify the governing intent, settled branches, current frontier, and next re-entry point in ten seconds.

These thresholds are initial release criteria. They should change only with documented evidence, never to make a failing candidate appear green.

### Operational measures

For a production canary, report:

- checkpoint coverage among turns with completed assistant output
- invalidated checkpoints by reason
- reconciliation attempts and successful follow-up checkpoints
- divergent payload rejections that remain unreconciled
- record or hook failures by host and execution context
- prompt-context bytes and node count per active project
- graph load and layout duration for large maps

The telemetry remains machine-local and contains counts, durations, identifiers, and failure classes—not raw transcript text.

## Evaluation layers

### Layer 1: deterministic regression suite

Run on every change and in continuous integration. These tests use isolated temporary databases and no model call. They prove storage, validation, lifecycle, state, and migration behavior. `make eval-reliability` gives a baseline-versus-candidate report; ordinary unit tests provide failure detail.

### Layer 2: sanitized semantic fixtures

Create versioned cases from the observed failures and good counterexamples:

| Case | Required result |
|---|---|
| Local installation checkpointed before completion | Final state settles after the verified install; no stale installation resume remains. |
| Workforce SaaS side quest followed by main handoff and a same-id steer | Preserve the side quest, main result, handoff, and planned explorer; checkpoint the whole interaction. |
| Malformed top-level record fields | Reject the payload and leave the interaction uncheckpointed. |
| Paperclip capture initially works, then fails in broader testing | Settle, reopen, and settle again without creating duplicate concepts. |
| Settled assessment with optional hardening child | Keep the parent settled and child open. |
| Later aggregate contradicts an older child resume | Flag or repair the stale text without changing unrelated states. |
| More than 24 distinct long-lived concepts | Preserve distinct branches; continue rejecting chronology and over-deep chains. |
| Claude unattended record command cannot execute | Emit an actionable diagnostic and leave the turn visibly uncheckpointed. |

Each fixture stores a short synthetic transcript, labelled concepts and transitions, accepted parent alternatives, and forbidden outputs. It does not store private production transcripts.

The versioned schema is JSON under `tests/fixtures/semantic/`. `seed_operations`
constructs the map visible at the start of the evaluated interaction. `prompt` is
the one synthetic user turn sent to the host. `expected.nodes` selects concepts
by stable id or semantic terms and labels their required state, causal parent,
prior state, and resume semantics. The fixture can also bound new concepts,
require unchanged concepts, and reject chronology-shaped titles. A
`reference_items` graph is a scorer test oracle, not text shown to the model.

Resume labels deliberately distinguish three meanings:

- `empty` means the text itself must be removed, as in a contradicted stale resume;
- `nonempty` means an unresolved concept must retain a usable re-entry point;
- `closed` accepts either no resume or explicit completion/conditional-reopen guidance, but rejects an ordinary unfinished action.

The deterministic scorer reports concept recall and precision, state and
transition accuracy, causal-parent accuracy, and resume accuracy. It also emits
specific structural failures. Exact generated prose is never scored.

### Layer 3: live-agent repeated trials

Deterministic tests cannot measure extraction quality. Run each semantic fixture through fresh isolated Codex and Claude sessions, at least five trials per host/model configuration. Report mean, minimum, and individual failures; never report only the best run. Keep a holdout set that is not used while editing prompts.

The existing frontier-handoff test is the first live case. Extend the runner to support the fixture schema, both hosts, repeated trials, and structural scoring. Human review remains required for cold-read quality and accepted semantic equivalents.

`scripts/run_semantic_evals.py` now provides that runner. Each trial creates a
new project, database, session, and isolated Codex plugin home; Claude loads the
selected plugin directory directly. Both hosts see the same seeded graph and
prompt. The report records the package commit, dirty state, and label; harness
commit and dirty state; host version; requested
model, fixture digest, scorer version, checkpoint delta, structural metrics,
problems, final answer, and resulting graph. JSON reports include mean and
minimum metrics per host as well as every individual trial. A live run remains
opt-in because it calls paid/non-deterministic models.

### Layer 4: version comparison

Run the same fixture set against:

1. the tagged v0.3.0 package in an isolated data directory;
2. the candidate package in a second isolated directory.

Compare per-case results and aggregate metrics. A candidate may not regress an existing passing safety case to repair a failure case. Store package version, host version, model, fixture revision, trial seed when available, and scorer version with every result.

The runner accepts `--package-root`, so the harness, fixtures, and scorer remain
fixed while only the installed Mindmap package changes. This is the important
control: running an old checkout's old tests against itself would hide newly
discovered failures. `scripts/compare_semantic_evals.py` verifies matching
host/fixture digests and scorer versions, then reports pass-rate and mean/minimum
metric deltas globally, per host, and per fixture. Use at least five trials per
cell and the same explicit host models. Model nondeterminism means a one-trial
comparison is only a wiring smoke test, not evidence of improvement.

### Layer 5: production canary and full audit

After automated and live fixtures pass, deploy the candidate to a small set of new sessions. Review the local operational measures after at least 50 completed turns or one week, whichever comes later. Then repeat the CASS cross-project audit. The full audit validates external validity; it is not the only evidence of improvement.

## The former 24-concept limit

The public Git history contains the 24-concept limit from its first commit, but the pre-release CASS history shows its origin. During the causal-tree adversarial review, the store accepted 30 message-shaped roots and a 30-link chronological chain. The implementation briefly used limits of 40 and 30, then tightened the lifetime total to 24 while adding root, depth, per-checkpoint, and chronology guards. The evidence supports a semantic safety rail, but it does not establish 24 as a performance boundary.

The lifetime node ceiling is therefore removed. These guards remain:

- at most 20 new concepts in one checkpoint
- at most four independent roots
- at most ten levels of causal depth
- rejection of numbered message, turn, prompt, response, tool-call, and event names
- instructions to prefer roughly 5–20 concepts for an ordinary initial backfill and zero to three changes for a normal turn

“Small” now describes concept resolution rather than total project complexity.

### Scale benchmark

The following local benchmark used representative summaries and resumes on this development machine:

| Concepts | Total write time | SQLite project view | Context construction | Injected context size | Dagre layout |
|---:|---:|---:|---:|---:|---:|
| 24 | 16.5 ms | 0.28 ms | 0.74 ms | 9 KB | 8.1 ms |
| 50 | 23.2 ms | 0.33 ms | 0.91 ms | 19 KB | 6.6 ms |
| 100 | 37.8 ms | 0.65 ms | 2.32 ms | 37 KB | 9.3 ms |
| 250 | 101.0 ms | 1.34 ms | 3.55 ms | 93 KB | 26.6 ms |
| 500 | 170.8 ms | 1.46 ms | 3.37 ms | 186 KB | 64.1 ms |

SQLite and layout do not justify a limit of 24. Reinjecting the entire graph into every turn is the real scaling concern. Track context bytes in production and live evaluation. If large real maps degrade cost or semantic accuracy, introduce an adaptive context projection that always includes roots, the active frontier, its ancestors, and recently changed or explicitly requested branches. Do not delete concepts or silently merge complexity to reduce prompt size.

## Implementation sequence

### Phase 0: freeze evidence and measures

Status: complete for the initial deterministic baseline.

- Check in the production baseline and deterministic comparison runner.
- Document semantic and operational measures.
- Preserve the original failures as sanitized fixtures.
- Record benchmark conditions and avoid timing assertions in ordinary unit tests.

### Phase 1: close deterministic protocol gaps

Status: implemented and verified in the current working tree.

- Require the `operations` field and reject unknown payload and operation fields.
- Preserve multiple prompts for one interaction.
- Reopen a checkpoint when a distinct same-id prompt arrives.
- Keep earlier mutations and require an incremental corrective checkpoint with current revisions.
- Give checkpoints older than 60 seconds at Stop one bounded reconciliation pass.
- Remove the lifetime 24-concept limit while retaining semantic structure guards.

The 60-second rule catches the two audited long-running premature checkpoints. It is a safety net, not a semantic proof: a fast omission can still pass, and a legitimately long final response may trigger one unnecessary reconciliation. Measure both false negatives and false positives before treating the threshold as permanent.

### Phase 2: make checkpoint finality explicit

Status: planned.

- Evaluate whether transcript activity can distinguish substantive post-checkpoint work from the record result and final prose on both hosts.
- Compare that design with explicit draft/final checkpoint generations.
- Retain append-only checkpoint provenance and expose unresolved invalidations.
- Replace or supplement the time heuristic only when the new mechanism scores better on the frozen cases.

### Phase 3: detect stale semantic frontiers

Status: planned.

- Add warning-only checks for settled nodes with action-like resume text, direct summary contradictions, stale aggregate roots, and planned/open reversions without recorded rationale.
- Distinguish unfinished resumes from maintenance or “reopen when” guidance.
- Let the agent reconcile warnings; never auto-settle causal parents.

### Phase 4: harden host integrations

Status: planned.

- Add a Claude unattended permission and launcher self-test.
- Make record failures visible at the next prompt and in local diagnostics.
- Test Codex steers and Claude fresh subagent sessions separately while keeping shared store behavior identical.
- Mark zero-turn and missing transcript attachments explicitly.

### Phase 5: build semantic comparison and release gates

Status: in progress.

- Generalize the live frontier runner to the full fixture set and both hosts. **Implemented for the first five semantic cases.**
- Add repeated-trial structural scoring and human cold-read review. **Automated scoring and repeated runs are implemented; the review rubric/run remains.**
- Compare tagged v0.3.0 with the candidate package.
- Run a production canary, then repeat the full CASS audit.
- Promote the reliability evaluation to a release gate after its remaining target case passes and live scoring is stable.

## Current result

The deterministic suite moves from 4/8 passing baseline cases to 8/8 on the working tree. Strict schema validation, same-interaction steer recovery, growth beyond 24 concepts, and the observed long premature-checkpoint window now pass. The full local validation gate passed after that slice, including 83 Python tests, 17 frontend tests, Go tests, package parity, builds, and official Codex and Claude validators. One isolated live Codex frontier-handoff trial also passed.

The first semantic-runner calibration gives useful evidence rather than a blanket green result. On the local-install closure case, Codex and Claude both settled the existing node without creating another concept (2/2). On the Paperclip contradiction, both hosts correctly reopened the existing settled concept; Codex reused it compactly, while Claude also created a redundant symptom child and therefore failed the resolution/precision constraint (Codex 1/1, Claude 0/1). These are smoke trials, not stable rates. They show that the shared lifecycle can deliver the required transition on both paths, while host prompting/model behaviour can still differ in graph resolution.

General semantic detection of fast post-checkpoint omissions remains a programme-level gap; the one-minute safeguard still needs production false-positive measurement. The remaining semantic cases need repeated runs, the Claude permission case still needs an integration fixture, and v0.3.0-versus-candidate reports plus human cold-read scoring are required before release.

## Commands

```sh
make eval-reliability
PYTHONPATH=src python3 scripts/evaluate_reliability.py --json
PYTHONPATH=src python3 scripts/evaluate_reliability.py --require-targets
make test
make validate
make test-frontier-handoff
make test-semantic-evals
```

For an actual controlled before/after semantic comparison, create a detached
v0.3.0 worktree and run the current harness twice. Keep both non-zero trial
results: a semantic failure is valid report data, not a runner crash.

```sh
baseline_checkout=/var/tmp/mindmap-eval-v0.3.0
git worktree add --detach "$baseline_checkout" v0.3.0

set +e
PYTHONPATH=src:. python3 scripts/run_semantic_evals.py \
  --host both --runs 5 --package-root "$baseline_checkout" --label v0.3.0 \
  --output /var/tmp/mindmap-v0.3.0-results.json
PYTHONPATH=src:. python3 scripts/run_semantic_evals.py \
  --host both --runs 5 --package-root . --label candidate \
  --output /var/tmp/mindmap-candidate-results.json
set -e

PYTHONPATH=src:. python3 scripts/compare_semantic_evals.py \
  /var/tmp/mindmap-v0.3.0-results.json \
  /var/tmp/mindmap-candidate-results.json
```

Pin `--codex-model` and `--claude-model` explicitly for a retained comparison,
and require clean package and harness working trees.
Inspect every failed graph and final answer before deciding that an alternative
is genuinely equivalent; only then amend a fixture with the rationale. Remove
the detached worktree with `git worktree remove "$baseline_checkout"` after the
reports are no longer needed.

Do not add `--require-targets` to the release gate until every listed target is expected to pass on the maintained branch. The non-strict report is useful during phased implementation because it shows remaining red cases without hiding completed improvements.
