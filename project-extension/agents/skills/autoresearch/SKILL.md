---
name: autoresearch
description: Canonical around-the-clock research loop. Defines the agent's outer loop — read taste corpus + queue, pick the next experiment, mutate the explicitly-declared mutation surface, run the experiment under a hard time budget against a frozen metric, score, codify, repeat. Augmented with Karpathy's sharp primitives (frozen metric, time cap, explicit mutation surface) and a sustained-campaign layer (concurrent run/plan/write-up pipeline, verdict protocol, novelty re-verification gate) for multi-day operations.
---

# autoresearch

The canonical loop that distinguishes Rockie from a chat assistant.
This is what runs around-the-clock on the tenant's Fly machine.

The bones of this skill predate Karpathy's autoresearch (rockie's
existing autopilot + queue + post-run-review primitives are richer than
Karpathy's narrow loop). Phase 7 augmented those bones with three
sharp Karpathy primitives — frozen metric, time-budget per experiment,
explicit mutation surface — without stripping the broader system. A
later pass added the sustained-campaign layer below (concurrent
pipeline staffing, the verdict protocol, subagent tiering, the
pre-launch resource/placement red-team, and the novelty
re-verification gate) — the operating discipline that keeps a
multi-day, multi-experiment campaign honest once a single queue row
stops being the unit of work.

## When to invoke

- The autopilot daemon invokes this skill on every queue dequeue.
- A researcher invokes manually for a one-off experiment outside the
  queue (`/autoresearch run-once …`).
- The post-run-review skill calls back here with a follow-up experiment
  derived from a [LEARN] block.

## The canonical loop

```
┌─ taste corpus (immutable for the run) ────────────┐
│  SOUL / STYLE / METHODOLOGY / DISMISSALS / MEMORY │
│  + program.md (Karpathy convention) if present    │
└────────────────────┬───────────────────────────────┘
                     │
            ┌────────▼────────────┐
            │ PICK from queue or  │   ← queue-refill skill keeps this stocked
            │ from a [LEARN] tip  │
            └────────┬────────────┘
                     │
                     ▼
       declare mutation_surface[]  ← explicit; every other path is read-only
                     │
                     ▼
         lock metric (metric_locked=1)  ← Karpathy: no goalpost-shifting
                     │
                     ▼
         set time_budget_seconds         ← Karpathy: hard cap, default 300s
                     │
                     ▼
        ┌────────────────────────┐
        │ propose change to ANY  │
        │ file in mutation_surface│   (everything else is immutable)
        └────────────┬────────────┘
                     │
                     ▼
              run the experiment
                     │
                     ▼
        evaluate against the frozen metric
                     │
              ┌──────┴──────┐
        improvement?     no improvement?
              │              │
              ▼              ▼
         git commit     git revert
              │              │
              ▼              ▼
       post-run-review (always)
              │
              ▼
      [LEARN] / [DEAD-END] capture
              │
              ▼
       calibration row (predicted vs actual delta)
              │
              ▼
       [if best-so-far] code-pool admit
              │
              └──→ next iteration
```

## Karpathy primitives — what they buy us

### 1. Frozen metric (`metric_locked = 1`)

Once an experiment starts, the metric is locked. No mid-run redefinition,
no "we should also track X" feature creep. Every iteration in the run
is comparable to every other iteration of the same run. Goalpost-shifting
is the failure mode this prevents — agents are tempted to add metrics
that flatter their changes.

**Convention:** the `metric_name` and `lower_is_better` fields on the
experiments row are set at queue-claim time. Toggling `metric_locked = 1`
means: until this run is `closed_at`, those two fields are immutable.

### 2. Per-experiment time cap (`time_budget_seconds`)

Karpathy's repo defaults to 300s (5 min). Rockie defaults to the same;
override per experiment based on workload (DFT might be 1800s; a quick
hyperparameter check might be 60s). The cap is HARD — once exceeded,
the runner kills the process and records a `failure_class = 'timeout'`.

This forces fast iteration. Slow experiments hide under "still running"
forever; a hard cap makes them visible.

### 3. Explicit mutation surface (`mutation_surface[]`)

Each experiment declares which file paths are mutable for THIS run.
Everything else is immutable for the duration. The runner enforces by
reverting any out-of-surface changes before evaluation.

Karpathy's convention: just `train.py`. Rockie's mutation_surface is a
list — most experiments only mutate one file, but model-architecture
sweeps may need to mutate `model.py` AND `train.py`. The point is
EXPLICIT declaration, not the count.

This makes diffs interpretable, prevents accidental config edits, and
gives downstream code-pool admission a clean "what changed" delta.

## What rockie has that Karpathy doesn't (don't lose this)

These are the broader primitives the taste corpus + memory schema
already provide:

- `dead_ends` registry — directions tried + rejected, with reasons.
  Future agents won't redo your failed work.
- `hypothesis_calibration` — predicted vs actual metric delta. Tracks
  whether your hypothesis-quality is improving over time.
- `code_pool` — best-K archive across runs. Cherry-pick winning ideas
  forward.
- `experiments` tree — parent/child journal lets you bisect your own
  research lineage.
- GPU procurement through Rockie's deidentified capacity market.
  Karpathy assumes one GPU on the desk.

## Procedure

```
# 1. Pick an experiment (queue-refill keeps the queue stocked).
#    The autopilot daemon does this; manual: pick a `pending` row from
#    experiment_queue ORDER BY priority, created_at LIMIT 1.

# 2. Lock metric + budget + surface from the queue row:
EXP_ID=$(.agents/skills/autoresearch/scripts/start.sh QUEUE_ID)

# 3. Mutate. The agent edits files in mutation_surface. Anything else
#    triggers an immediate revert.

# 4. Run the experiment under the budget:
.agents/skills/autoresearch/scripts/run.sh "$EXP_ID"
# (kills the process when time_budget_seconds elapses; records timeout
# as failure_class=timeout)

# 5. Evaluate. The runner reads the metric_value and compares against
#    the prior best for the metric_name (with lower_is_better in mind).

# 6. Commit if improved, revert if not. Either way, post-run-review
#    runs and emits [LEARN]/[DEAD-END]. The autopilot loop continues.
```

## Anti-patterns

- **Unlocking the metric mid-run** to "also track X" — defeats the
  purpose. Lock it; if you genuinely need a different metric, that's a
  new run.
- **Skipping the time cap** — slow experiments creep into "always
  running". Better to hit the cap and record `timeout` than to silently
  block the queue.
- **Defaulting mutation_surface to "the whole repo"** — that's no
  surface at all. Pick one to three files. If you need more, you may
  be conflating two experiments.
- **Optimising without taste** — `program.md` (Karpathy convention) or
  the SOUL/STYLE/METHODOLOGY corpus (rockie convention) MUST be loaded
  into the agent's context every iteration. Without taste, you get
  technically-correct-but-research-garbage output.

## Concurrent pipeline staffing (sustained, multi-day campaigns)

The canonical loop above is the per-experiment micro-loop. Once a
campaign runs for days rather than a single queue row, staff three
roles at once — never sequentially, never idle between them:

- **RUN N** — the live experiment executing right now. Poll it BLIND
  (see Verdict protocol below).
- **PLAN N+1** — a design pass drafting the next experiment with every
  WIN / PARTIAL / NULL branch of N pre-specified AND pre-attacked, so
  the winning branch can launch the same day N's verdict is recorded.
  Zero idle gap between a verdict landing and the next launch.
- **WRITE UP N−1** — a write-up pass for the previous result, carrying
  an explicit pending slot for N's verdict.

Use this once the queue has more than one experiment in flight across
more than a day of wall-clock; for a single short experiment the
canonical loop above is sufficient on its own.

## Verdict protocol (never shortcut this)

- Runs are BLIND: runners and pollers report structure only — did it
  crash, how many cells finished, error greps — never metric values,
  before the assess stage.
- On completion, dispatch a FRESH assess agent (judge-tier model, no
  narrative memory of the run) that applies bands FROZEN before the
  run started to the raw artifacts.
- RECORD FIRST: write the verdict to the experiment/design record
  BEFORE any dependent stage dispatches and before it's surfaced to
  the researcher.
- The coordinator then cross-checks the recorded verdict against the
  raw files itself. If two rounds make conflicting claims about the
  same artifact, read the raw artifact directly and record the
  tiebreak — never average, split the difference, or default to the
  more recent claim.
- Surface the verdict first, with honest odds, no spin. Never
  fabricate dates or results.

## Subagent tiering

Workers (research scouts, design drafters, write-up agents, runners)
use the cheaper/faster model tier. Judges, attack rounds, and blind
assessors use the strongest available tier — they're the check on
everything else, so under-provisioning them defeats the point. See
the `prefer_opus_for` / `prefer_sonnet_for` fields on the `[workflow]`
table in `.agents/skills/mode/SKILL.md` for rockie's own default split
(workhorse tier for research/fix-application, top tier for
attack/novelty-check/high-risk calls).

## Pre-launch resource/placement red-team

Every GPU-committing launch gets an adversarial pass before it burns a
dollar: does the workload actually fit the target hardware (predicted
utilization + memory, not a guess)? Is the timeout realistic at the
measured rate? Is this a duplicate of a run already in flight? Is
there an undischarged gate blocking this launch?

**Ceremony scales with compute committed, not with excitement:**

| Compute committed | Ceremony |
|---|---|
| < 10 GPU-hours | 1 audit round |
| 10–50 GPU-hours | audit + a dedicated resource/placement red-team pass |
| > 50 GPU-hours, or anything publication-bound | full multi-round adversarial gauntlet |

**Utilization, not occupancy.** If you're paying for a GPU — spot-rented
or a fixed uptime-metered box — idle time is wasted money either way.
Sample utilization periodically; sustained low utilization on a GPU
you're actively paying for is a bug to diagnose, not background noise
(fix with exact tmux-session names or exact PIDs — see the `ops`
seeds in `examples/seed_example_ml_research.py` for the remote-box
`pkill -f` trap this rules out). Saturation-packing — predicting SM
utilization and memory footprint per cell, then packing several small
cells onto one GPU with a contention-priced ceiling instead of running
each alone at low utilization — is a pre-launch design decision, not
an afterthought.

## Novelty re-verification gate

A novelty check done once at design time goes stale the moment the
claim moves. Re-run it BEFORE every launch and at every CLAIM PIVOT —
a reframed headline is a NEW claim even when the experiment underneath
is unchanged, because the literature it now competes in has changed
(a reframed claim can land in a far more crowded literature than the
one it was first checked against — same experiment, different
competing field).

The gate, triple-sworn:

1. **External sweep, by-TASK angle** (worker agent, web-verified): who
   has run this task family / protocol, in what train-test regime?
2. **External sweep, by-MECHANISM angle** (independent worker agent):
   who has built this mechanism or claimed this property? Hunt
   specifically for publications after the last check.
3. **Internal-archive sweep** (worker agent, read-only): does your own
   experiment log, dead-end registry, and design history already
   contain, constrain, or contradict the planned cells or claim?

Both external agents are prompted ADVERSARIALLY ("find the scoop") and
must return a kill-question verdict plus the narrowest honest unclaimed
statement. A judge-tier agent (mandatory for publication-bound claims)
adjudicates all three, records the verdict in the relevant design doc
or research memo, and only then lets the dependent stage proceed.

## Schema additions (migration 005)

See `platform-skills/memory/migrations/005_karpathy_primitives.sql`:

- `experiments.metric_locked` (0/1)
- `experiments.time_budget_seconds` (int, NULL = no cap)
- `experiments.mutation_surface` (TEXT, JSON-encoded list of paths)
- Same three columns on `experiment_queue` for pre-population.

## References

- karpathy/autoresearch (March 2026) — vendored at `rockie-workspace/references/karpathy-autoresearch/` (Phase 7 follow-up — not yet pulled).
- Sakana AI Scientist (sakana.ai/ai-scientist) — broader-scope alternative; rockie's primitives are closer to Sakana shape than Karpathy's narrow loop.
- DeepMind FunSearch (arxiv.org/abs/2302.12588) — function-discovery flavor; not the Rockie pattern.

## Sequencing

The autoresearch loop runs WITHIN a runtime variant — rockie-claude /
rockie-codex / rockie-byok. The Phase 6 alignment agent keeps the
overlay copies of this skill in sync across the three. The post-run-review
+ queue-refill + autopilot skills are the loop's neighbors and must
stay coherent with the conventions documented here.
