---
name: queue-refill
description: Refill the experiment queue when it drops below target (default 5 pending items). Brainstorms 3–5 new high-quality experiments informed by recent [LEARN] rules, killed dead-ends, best-so-far results, and hypothesis-calibration drift. Use when `queue.py refill-needed` returns non-zero, when the user asks "what should we try next", or as a scheduled task between GPU-bound runs.
---

# /queue-refill — auto-refill the experiment queue

Keeps the autonomous agent's forward-looking work queue full. This is
the "Prioritization Specialist" pattern from arXiv 2604.13018 adapted
to our harness.

## When to run

- **Scheduled:** every N hours (via `/schedule` or `/loop`), so the
  queue is always ≥ target when a GPU frees up.
- **Reactive:** when `queue.py refill-needed` exits non-zero.
- **Manual:** user asks "what should we try next?" or "refill the queue".

## What the skill does

1. **Read recent context from workflow.db:**
   - Last 20 `[LEARN]` rules (`learnings` table)
   - All active `dead_ends` for this project
   - `best_so_far` view (per metric)
   - `calibration_scorecard` — which hypotheses were over/under-predicted
   - `experiments` table — recent nodes, stages, failure_class distribution

2. **Read STATE.md** to understand current research direction.

3. **Brainstorm 3–5 new queue items.** Each item must:
   - Be a single-sentence testable hypothesis
   - Include a predicted metric delta (forced quantitative prior)
   - Not overlap an active `dead_ends` direction (query before proposing)
   - Prefer building on best-so-far (extend the working path) unless
     there's evidence the path is saturating
   - Match the current `stage.py get` suggestion (draft → tune → creative → ablation)

4. **Call `queue.py add` for each.** Example:

   ```bash
   python3 .codex/scripts/queue.py add \\
       --hypothesis "Matrix token init with log-normal std 0.02 reduces warmup loss vs normal(0, 0.02)" \\
       --metric val_loss --predicted-delta -0.04 \\
       --priority 2 --minutes 45 --stage creative
   ```

5. **Report what was added** in a single message to the user.

## Constraints

- **Never** re-propose an active dead-end direction. If the FTS5 search
  on `dead_ends` matches what you're about to add, skip it.
- **Always** include a predicted_delta. Missing priors break
  hypothesis calibration.
- **Priority scale:** 1 = highest (block the queue if nothing else), 5 =
  nice-to-have. Default 3.
- **Estimated_minutes:** be honest. Under-estimating torches the budget
  controller. Over-estimating means the scheduler never picks it.

## Composition

- **Dead-end registry:** filters out re-walked directions before
  they reach the queue.
- **Hypothesis calibration:** brainstorm agent should read the
  scorecard — if sign-accuracy < 60% on recent runs, proposes should
  be simpler / lower-delta until priors improve.
- **Journal tree:** proposals should extend the best-so-far node's
  lineage when possible (`--parent <id>`) rather than always spawning
  from root.
- **Stage-inject hook:** current stage gates what kinds of proposals
  are appropriate (ablation stage → only strip-out variants, not
  creative ideas).

## Failure modes

- **Brainstorm hallucinates metrics:** use only metrics that appear in
  recent `experiments` rows for this project.
- **Item collision:** the `UNIQUE` on project doesn't exist for the
  queue (intentional — same hypothesis at different priorities is fine),
  so be careful about re-adding an identical hypothesis on rapid calls.
