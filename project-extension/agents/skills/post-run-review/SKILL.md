---
name: post-run-review
description: After an experiment finishes, structured review emits {is_bug, failure_class, summary, metric, lower_is_better}, auto-closes the journal node, emits a [LEARN] block when is_bug=true, and files a [DEAD-END] when the failure_class is "bad-hypothesis". Use immediately after any training/eval run — the agent invokes this without user prompt as the last step of the Assess phase.
---

# /post-run-review — structured Assess → Codify

Ports the AIDE `submit_review` pattern (MIT, `aide/agent.py` L19–44 +
`parse_exec_result` L296–339). Ours adds the C4 failure-class
classification — `bug | bad-hyperparam | bad-hypothesis` — which no
other autonomous-research harness currently cleanly separates.

## When to invoke

Automatically, as the final step of the Assess phase, after any
experiment with a journal node (`journal.py add …` was called at Plan
time). Don't invoke on trivial scripts.

## What the skill does

Given:
  - Journal node id (`--node N`)
  - Log / stdout from the run (`--log PATH`)
  - Optional metric override (`--metric NAME=VAL`)

The agent reads the log, forms a structured verdict, and writes:

```json
{
  "is_buggy": 0 | 1,
  "failure_class": null | "bug" | "bad-hyperparam" | "bad-hypothesis",
  "metric_name": "val_loss",
  "metric_value": 3.42,
  "lower_is_better": 1,
  "summary": "one-paragraph what-happened",
  "learn_block": "<optional [LEARN] emitted separately>",
  "dead_end_block": "<optional [DEAD-END] emitted separately>"
}
```

and then:

1. Calls `journal.py close <node> --metric ... --is-buggy ... --failure-class ... --analysis "..."`.
2. If `is_buggy=1` and it's a clear durable rule: emits a `[LEARN]` block in its response (Stop hook captures it).
3. If `failure_class=bad-hypothesis`: emits a `[DEAD-END]` block.
4. If `actual_delta` for this run was predicted: `calibration.py close <run_id> "<hypothesis>" <actual>`.

## Failure-class meanings (IMPORTANT)

| class | means | action |
|---|---|---|
| `bug` | implementation error (shape mismatch, off-by-one, NaN from wrong init) | fix the code, retry; emit [LEARN] with the gotcha |
| `bad-hyperparam` | logic is sound but config misses (lr too high, batch wrong, seed bad) | tune; keep the hypothesis alive |
| `bad-hypothesis` | idea itself doesn't work at the scale tested | emit [DEAD-END]; do NOT re-propose this direction |

Mis-classifying a `bad-hypothesis` as a `bug` will cause the agent to
loop on a fundamentally broken idea. Mis-classifying a `bug` as a
`bad-hypothesis` will kill directions that would have worked after a
fix. Be honest. When uncertain, prefer `bad-hyperparam` — it keeps the
option open and triggers the cheapest next action (tune).

## Composition

- **Journal tree (B1):** this skill closes journal nodes; best-so-far
  view automatically updates.
- **[LEARN] DB:** bugs become durable rules so the same class of bug
  isn't re-hit by a future agent on a sibling branch.
- **Dead-end registry:** bad-hypothesis directions become queryable
  and auto-injected into future brainstorm prompts.
- **Hypothesis calibration:** `actual_delta` closure feeds the
  scorecard; over time the agent's priors either improve or drift.
- **Pre-run audit agent (ours, uniquely):** pre-catches many of the
  `bug` class before running. This skill is the post-run backstop.

## Agent invocation template

```
Given the log at <path> and journal node <N>, produce the structured
review. Be honest about failure class — mis-classification loops the
agent on broken ideas or kills good ones. Then close the node, emit
[LEARN] or [DEAD-END] as appropriate, and close the calibration entry.
```

The agent must:

1. Read the log.
2. State the verdict in one paragraph.
3. Run the three CLIs (`journal close`, optional `calibration close`, emit blocks).
4. End its response. The Stop hooks do the rest.
