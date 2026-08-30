# Blinded cold-read review

## Purpose

The automated scorer checks labelled concepts, states, transitions, parents, resumes, and forbidden chronology. It cannot prove that a compact map makes sense to someone who did not read the session. This review tests that human recovery directly without asking the reviewer to reconstruct the transcript.

Use the same retained reports as the v0.3.0-versus-candidate comparison. Do not rerun a model to improve a weak map after seeing the review.

Generate the packet, separate answer sheet, and private key with:

```sh
PYTHONPATH=src:. python3 scripts/prepare_cold_read.py \
  /path/to/v0.3.0-rescored.json /path/to/candidate-rescored.json \
  --output-dir /path/to/cold-read-packet --trial 1 --seed 20260831
```

The command refuses to overwrite an existing directory. Give the reviewer only
`packet.md` and `answer-sheet.md`; retain `key.json` privately until scoring is
fixed.

## Prepare the sample

1. Include one predetermined trial for every package, host, and fixture cell. Choose the trial number before reading any output; trial 1 is the default.
2. Render only the resulting causal tree: ids, titles, summaries, resumes, states, and parent indentation. Remove package, host, model, fixture, timestamps, final answers, diagnostics, scores, and commit labels.
3. Assign random neutral codes and randomize presentation order. Keep the code-to-report key separate until scoring is complete.
4. Give the reviewer the fixture's one-sentence project situation, but not its transcript, expected graph, scorer problems, or package identity.
5. Use at least one reviewer who has not read the source session or edited the fixture. A second independent reviewer is preferred for any release-blocking disagreement.

## Ten-second recovery test

Show one map for ten seconds, then hide it. The reviewer writes short answers to these questions:

1. What is the governing intent?
2. What material work or decisions are settled?
3. What remains open or planned?
4. Where would you resume, and what would you do next?

After the map is visible again, ask two quality questions:

5. Which node, state, parent, summary, or resume was confusing or contradictory?
6. Which node appeared redundant, trivial, chronological, or unsupported by the stated situation?

## Score

Score each recovery answer against the fixture labels, not exact wording.

| Measure | 1 | 0 |
|---|---|---|
| Governing intent | Identifies the root goal or an accepted equivalent | Misses or materially changes it |
| Settled outcomes | Recovers every release-blocking settled result and does not call it unfinished | Misses or reverses one |
| Active frontier | Recovers every release-blocking open/planned branch | Misses or falsely closes one |
| Re-entry point | Names a usable next action for the matching branch | Cannot tell where or how to resume |
| Internal consistency | Finds no material state/summary/resume contradiction | Finds a material contradiction |
| Resolution | Finds no message-shaped, routine, redundant, or unsupported node | Finds one or more |

A map passes only when the first four measures score 1 and neither quality question identifies a material problem. Report each cell, package totals, host totals, disagreements, and reviewer comments. Do not average away a release-blocking miss.

## Unblind and decide

Unblind only after all scores are fixed. Compare candidate and v0.3.0 by fixture and host. A candidate must not lose a previously recoverable release-blocking concept, transition, or frontier. Treat a disagreement as evidence to inspect the map and fixture; do not change the rubric or accepted equivalences merely to improve the candidate's score.

Retain the blinded packet, answer sheets, key, source report digests, reviewer identities, review date, and adjudication notes with the release evidence.
