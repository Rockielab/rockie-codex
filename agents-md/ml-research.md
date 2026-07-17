# AGENTS.md — ML research example

> Example specialization of the rockie template for an ML research repo.
> Copy to your project's root as `AGENTS.md` and edit the `Project` section
> for your specifics.
>
> The "Where things go" table and the upstream-back flow from
> `agents-md/AGENTS.md.template` apply equally here — read that file
> alongside this one, or pick one as your canonical AGENTS.md and
> merge the sections you want.

## Workflow: Plan → Research → Build → Audit → Run → Assess → Codify

Every cycle should make the next cycle better.

- **Plan:** Talk with the user. Understand the goal before touching code.
- **Research:** Send agents to verify claims and check novelty. Never assert facts without evidence.
- **Build:** Write code. Keep it clean. Comment the non-obvious.
- **Audit:** Send a separate agent to review code before running. Check shapes, gradients, stability. The implementer does not review their own work.
- **Run:** Use the hardware. Parallel experiments when possible.
- **Assess:** Be honest. Negative results are data. Don't spin.
- **Codify:** Update `STATE.md` and `EXPERIMENT_LOG.md`. If you learned a lesson, emit a `[LEARN]` block so it auto-saves to the learnings DB.

## Operating Doctrine (for sustained, multi-day campaigns)

The `autoresearch` skill (`.agents/skills/autoresearch/SKILL.md`)
encodes the loop that enforces these; both travel with the project.

- **One spearhead.** Pick the single result the campaign is actually
  for — the flagship experiment — and treat everything else as support
  or backlog filler. A campaign with two co-equal priorities makes
  neither one land.
- **Concurrent pipeline.** Past a single experiment, never run
  sequentially: RUN the live experiment; PLAN the next one with every
  WIN/PARTIAL/NULL branch pre-specified and pre-attacked so the
  winning branch launches the same day the current verdict lands;
  WRITE UP the previous result with an explicit pending slot for the
  current one. Zero idle gap between a verdict and the next launch.
- **Utilization, not occupancy.** If you're paying for a GPU — a
  spot-rented instance or a reserved box on a fixed compute window — idle time is
  wasted money either way. Sample utilization periodically; sustained
  low utilization on a GPU you're actively paying for is a bug to
  diagnose, not background noise. Saturation-packing (predicting SM
  utilization + memory per cell, then packing small cells N-per-GPU
  with a contention-priced ceiling instead of running each alone) is a
  pre-launch design decision, not an afterthought.
- **Research grounding.** Every design, claim, and report cites
  VERIFIED literature — a research agent confirms author, venue, and
  actual claim by web search before a citation enters any doc; the
  coordinator spot-checks load-bearing claims (e.g. fetches the
  abstract) before folding them in. Novelty is a searched absence,
  never an assumed one.
- **Novelty re-verification gate.** A novelty check done once at
  design time goes stale the moment the claim moves. Re-run it before
  every launch AND at every claim pivot — a reframed headline is a new
  claim even when the experiment underneath is unchanged, because the
  literature it now competes in has changed. See the autoresearch
  skill's gate section for the full triple-sweep protocol (external
  by-task, external by-mechanism, internal-archive).
- **Ceremony tiers.** Ceremony scales with compute committed: under 10
  GPU-hours gets one audit round; 10–50 GPU-hours gets audit plus a
  dedicated resource/placement red-team; over 50 GPU-hours, or
  anything publication-bound, gets a full multi-round adversarial
  gauntlet.
- **Model tiering.** Worker subagents (research scouts, design
  drafters, runners) use the cheaper/faster model tier. Judges, attack
  rounds, and blind assessors use the strongest available tier —
  they're the check on everything else.

## Learnings DB

A SQLite DB at `.codex/memory/workflow.db` persists durable rules, corrections, and gotchas across sessions. Relevant rules auto-inject at prompt time via the `load-relevant-rules.sh` hook.

**When you learn something worth persisting, emit a `[LEARN]` block in your response:**

```
[LEARN] <category>: <one-line rule>
Mistake: <what went wrong>
Correction: <what the right approach is>
```

When you definitively kill a research direction, emit a `[DEAD-END]` block:

```
[DEAD-END] <direction>: <reason>
Evidence: <path to run dir or paper>
```

The brainstorm agent auto-loads relevant dead-ends on future "what should we try" prompts.

## Pre-Experiment Checklist (MANDATORY before every experiment)

1. **State the hypothesis in one sentence.** If you can't, don't run it.
2. **Predict the metric delta.** Record `predicted_delta` with `calibration.py add` — forces you to have a quantitative prior, and lets the harness track your calibration over time.
3. **Compute FLOPs, memory, and param count on paper.** 10 minutes. No exceptions.
4. **Try to disprove it in 5 minutes.** "Could a simpler baseline do this?"
5. **Check the literature first.** Send a research agent BEFORE building.
6. **Design the comparison before the experiment.** What's the baseline? Are params matched?
7. **Define success criteria.** What metric improvement justifies the compute cost?
8. **Verify the claim is novel.** Don't claim uniqueness without checking.

After the run, `calibration.py close <run_id> <hypothesis> <actual_delta>` closes the loop. Periodically `calibration.py report` to see if your priors are improving.

## Waterfall for new ideas

1. **Brainstorm agent** — Generate ideas.
2. **Research agent** — Validate against literature.
3. **Attack agent** — Find fatal flaws.
4. **Validation agent** — Confirm or deny each attack with evidence.

Only build what survives all four stages.

## Skill catalog — pull the framework expertise

`ml-training` is the largest category in the Rockie catalog (~50 skills),
with `ml-inference` alongside it. Before hand-rolling a training or eval
setup, check whether the expertise already exists:

```bash
rockie skill catalog --search grpo --json         # or: --category ml-training
rockie skill pull grpo-rl-training --out .agents/skills/grpo-rl-training
$grpo-rl-training                                 # usable immediately
```

Real pull ids include `grpo-rl-training`, `verl`, `openrlhf`,
`trl-fine-tuning`, `simpo`, `unsloth`, `lm-evaluation-harness`,
`llm-as-judge-evaluation`, `vllm`, `sglang`, `tensorrt-llm`. These ship
`templates/` and `examples/` you can run, not just prose.

Pull by `catalog_id`, invoke by the pulled `SKILL.md`'s frontmatter
`name` — they differ for ~13% of entries (`pull vllm` →
`$serving-llms-vllm`).

Fold this into the Waterfall's **Research** step: check the catalog
alongside the literature. Pull only what the current direction needs —
each kept skill costs a description at every session start, so
`rm -rf .agents/skills/<name>` when you're done. Details: `$find-skills`.
No `rockie` CLI on PATH? Skip it and do the work directly.

## Hard Rules (ML-research-specific; seed with `examples/seed_example_ml_research.py`)

- Verify before claiming. Use web search or research agents.
- Audit code with a separate agent before running.
- Smoke test every model (forward, backward, gradient check) before training.
- Use standard benchmarks for publishable claims.
- Save the exact script alongside experiment results for reproducibility.
- Log everything to a file. Produce a human-readable summary at the end.
- Smoke test must include EVAL batch size, not just training — eval can OOM even if training fits.
- Use the same dataset for ALL experiments in a comparison.
- DDP eval on rank 0 only will NCCL-timeout if eval >10 min. Set timeout to 30 min AND cap eval batches.
- HF cache defaults to container disk. Symlink `HF_HOME` to persistent volume immediately.
- Sweep experiments (multiple configs, one script, sequential) save GPU downtime. Add `try/except` so one crash doesn't kill remaining configs.
- The param-matched baseline ablation blocks ALL downstream decisions. Run it first.
- Making an op cheaper doesn't fix a quality gap. Speed ≠ quality.

## Repo Layout

- `STATE.md` — Current project state, what's running, dead ends
- `ARCHITECTURE.md` — Architecture spec with verified citations
- `EXPERIMENT_LOG.md` — Every experiment and result
- `references.md` — Paper references library
- `experiment-runs/` — Archived exact scripts from each experiment
- `archive/` — Dead ends and superseded docs

## Hardware

- Local dev box — quick iteration for <15M params
- Cloud GPU(s) — connection details in a gitignored setup doc
- Bigger cloud — reserved for runs after code is proven

## Data

Code lives in this repo. Data and checkpoints live elsewhere.

- Large datasets and checkpoints are gitignored.
- A pointer file at the repo root documents where to find them.

## Research Direction

_(one paragraph, editable each cycle. Keep it current — stale direction statements mislead future agents.)_

## User Context

_(describe who you are and how you want to collaborate)_
