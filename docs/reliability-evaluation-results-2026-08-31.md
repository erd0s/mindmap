# Reliability evaluation results, 31 August 2026

## Decision

The clean `287f531` candidate is better than tagged v0.3.0 on the frozen
automated and semantic tests and shows no measured regression. It is ready for
the independent cold read and production canary, not yet for release promotion.
The cold read, canary, and repeated CASS audit remain open gates.

## Controlled semantic comparison

The current harness ran five trials for each of five temporal fixtures on both
hosts: 50 fresh isolated sessions per package and 100 sessions in total.

| Variable | Frozen value |
|---|---|
| Baseline package | tagged v0.3.0 at `41b83778d542` |
| Candidate package | clean commit `287f53172455` |
| Codex model | `gpt-5.6-sol` |
| Claude model | `sonnet` |
| Trials | 5 per package/host/fixture cell |
| Fixtures | causal parent, local-install closure, Paperclip reopen, stale resume, workforce side quest |
| Scorer | v5, applied to retained graphs from both packages |

The initial `gpt-5.6` smoke attempt was rejected as an invalid model and is not
part of the comparison. Both retained package runs executed and checkpointed all
50 sessions. Scorer changes were applied offline to both reports, never to only
one side.

| Result | v0.3.0 | Candidate | Delta |
|---|---:|---:|---:|
| Overall semantic pass | 43/50 (86%) | 48/50 (96%) | +10 points |
| Codex | 25/25 (100%) | 25/25 (100%) | 0 |
| Claude | 18/25 (72%) | 23/25 (92%) | +20 points |
| Availability | 50/50 | 50/50 | 0 |
| Checkpoint given execution | 50/50 | 50/50 | 0 |
| Mean concept precision | 0.93 | 0.98 | +0.05 |
| Minimum concept precision | 0.00 | 0.50 | +0.50 |
| Mean resume accuracy | 0.98 | 1.00 | +0.02 |
| Minimum resume accuracy | 0.50 | 1.00 | +0.50 |
| Recall, parent, state, transition means | 1.00 | 1.00 | 0 |

The comparison script found no global, host, fixture, rate, mean, or minimum
regression. This result is stronger than rerunning production history alone:
the inputs, temporal expectations, models, trial counts, package under test, and
scorer are controlled, while the model calls remain repeated rather than being
treated as deterministic.

## What improved

The stale-resume fixture passed 10/10 on the candidate. In the first candidate
run, Claude sometimes said it had cleared the resume while omitting the field
from its upsert; the store correctly retained the old value. The lifecycle
context now states the exact API behavior: omitted fields are retained, and
clearing a stale frontier requires `"resume":""`. Claude then passed 5/5.

All candidate trials recovered every material concept with correct causal
parents. Every labelled settled-to-open and open-to-settled transition occurred
in the correct interaction. The workforce temporal fixture also passed on both
hosts, preserving its already-settled side quest, completed main work, handoff,
and deferred plan rather than compressing them into a root summary.

## What remains weak

Both candidate failures are Claude Paperclip trials. Claude reopened the
existing `multi-image-capture` concept when broader evidence contradicted its
settled state and settled it again after the fix. It also created a child such
as `multi-image-paste-first-only-bug` in two of five trials. The resulting map
is coherent, but it is finer-grained than the chosen resolution and causes node
churn. Codex updated only the existing concept in 5/5 trials.

Always-visible guidance improved this targeted pair from 3/10 on v0.3.0 and
2/10 on the first candidate to 8/10 in a focused Claude run. The pre-commit full
run was more variable: Paperclip passed 1/5, while stale-resume clearing passed
5/5. The clean run then passed Paperclip 3/5 and stale-resume clearing 5/5. This
is evidence that the storage instruction is reliable and the semantic resolution
rule remains probabilistic. Further prompt tightening should not be accepted
without a holdout case because it could erase legitimately independent
investigations.

## Deterministic mechanisms

The frozen reliability baseline improves from 4/11 to 11/11. The tool-activity
generation strategy scores 6/8 finality cases with zero false positives,
outperforming the age-only, transcript-activity, and always-reconcile strategies.
Its explicit misses are hosted tools without a local `PreToolUse` event and a new
commitment introduced only in final prose.

Warning-only stale-frontier diagnostics produced one useful warning across a
copy of the 17 current project maps after false-positive tightening. They never
auto-settle causal parents. The isolated Claude denial test also passes: denied
shell and MCP execution leaves no checkpoint, records one unresolved turn, and
injects `MINDMAP_PRIOR_CHECKPOINT_MISSING_V1` at the next prompt.

## Evidence identity

The retained reports were intentionally kept outside the repository because
they contain full synthetic agent outputs and total about 2.7 MB. Their SHA-256
digests are:

| Artifact | SHA-256 |
|---|---|
| Raw v0.3.0 report | `a00f8c98a7c30748f485f04fe3d35f4f708a128cbfdedcbf83a4c58ff40a2568` |
| v0.3.0 rescored with v5 | `3038a3b7c7635cb84fe7d47d491db668c81bea9e429d23abce1a816324febf5b` |
| Raw pre-commit candidate report | `ef6fbfda983a3d3da8fc623003c65cc89e82bfc0db62e6a064fe7e33e6a19887` |
| Pre-commit candidate rescored with v5 | `6198137fbed2e932d45b9b685a7d14af3c77bd7471fc98f30d7881dee2da6219` |
| Pre-commit comparison JSON | `4e7acf03f7a345e4373a44df65dc95d7d831d0102582c52293a474862ab988e4` |
| Clean `287f531` candidate report | `4a0bf9f8315567197d004c6a6f022f2001bf7d3ef8fba0759fcc24f563d611b8` |
| Clean baseline comparison JSON | `7635eb7c50b347424b7622dd9de9db36997d020326d763624b769ceb71a72edc` |
| Blinded packet | `d352ba734fba25c9350e99b7f450cd63c58cc490c833196554c71d601e20de92` |
| Cold-read answer sheet | `d2ac430260cc89e05db235e36e5eb97f96a92aff4647fb0f66dbad5aca71456e` |
| Private cold-read key | `c0c558bc75d4f81c9219b668aa74a6d49e32c7ed35a0493041dfdf130e9abe3e` |

The earlier candidate report declares a dirty package tree and remains only
confirmation evidence. The clean report identifies package commit `287f53172455`
and `package_dirty: false`; it is the candidate artifact for the cold read and
canary.

## Remaining gates

1. Have an independent reviewer complete the ten-second recovery test using the
   generated predetermined trial-1, seed-20260831 packet.
2. Install exact commit `287f531` and canary it for at least 50 completed turns
   and one week, whichever is later.
3. Inspect local operational counters and warnings, then repeat the full CASS
   audit across every monitored project and session.
4. Promote stable thresholds into the release gate only after those results are
   retained.
