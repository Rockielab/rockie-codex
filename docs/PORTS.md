# Ports — features from SOTA autonomous-research harnesses

Historical note: many entries below preserve the original slash-command
names (`/deploy-team`, `/clean`, `/onboard`) because that is how the source
material described the feature. In this Codex port, treat those as skill
nicknames: the practical invocation path is `$skill` or natural language.

Synthesis of a three-agent source-level review of 11 repos, re-checked
against a 60-day arXiv / blog scan on 2026-04-23. Ranked by
**leverage ÷ effort**. Every entry cites a specific file + line range so
a future contributor can verify independently.

> **Ecosystem-gap claims are time-stamped.** If a claim says "nobody else
> ships this", treat that as true only up to the `verified_on:` date on
> the claim. Three papers filled our "failure taxonomy" gap between Feb
> and April 2026 (see C4 note below). Re-check quarterly.

Our differentiators that stay untouched — every new port composes *with*
these, never *replaces* them:

- **Pre-run audit agent** (uniquely ours — other harnesses are post-run only)
- **FTS5 `[LEARN]` DB** with prompt-time injection (AIDE's `generate_summary`
  is strictly worse: no dedup, no cross-project memory)
- **Waterfall** (Brainstorm → Research → Attack → Validation)
- **Pre-experiment checklist** in AGENTS.md
- **ntfy.sh preemption recovery**
- **Living-doc pattern** (STATE / ARCHITECTURE / EXPERIMENT_LOG)
- **`experiment-runs/` archived scripts per run**
- **`/deploy-team` with worktrees + dashboard**
- **Pre-commit sentinel gate** (`/clean` + compute_clean_hash)
- **doc-guard hook** for .md slop

## License gate (verified per repo)

| Repo | License | Vendor code? |
|---|---|---|
| WecoAI/aideml | MIT | ✅ yes |
| SamuelSchmidgall/AgentLaboratory | MIT | ✅ yes |
| going-doer/Paper2Code | Apache-2.0 | ✅ yes (with NOTICE) |
| All-Hands-AI/OpenHands | MIT | ✅ yes |
| huggingface/smolagents | Apache-2.0 | ✅ yes |
| stanford-oval/storm | MIT | ✅ yes |
| Future-House/paper-qa | Apache-2.0 | ✅ yes |
| Kargatharaakash/ouroboros | Apache-2.0 | ✅ yes |
| SakanaAI/AI-Scientist-v2 | "AI Scientist License v1.0" (RAIL-derived) | ❌ reimplement ideas only |
| SakanaAI/AI-Scientist (v1) | "Other" custom | ❌ reimplement only |
| HKUDS/AI-Researcher | **no license file** | ❌ reimplement only |

**Rule:** before porting from any repo not already in the green list,
run `gh repo view <owner>/<repo> --json licenseInfo` and check.

---

## Shipped status

### ✅ In the repo (smoke-test covered)

| Port | Pattern | Source | License |
|---|---|---|---|
| A1 | Dead-end registry | Ouroboros | Apache-2.0 |
| A2 | Hypothesis calibration | Ouroboros | Apache-2.0 |
| A3 | Stuck detector (4 loop types) | OpenHands `stuck.py` | MIT |
| A5 | Stage-gated AGENTS.md injection | Sakana v2 (reimplemented) | — |
| A6 | Convergence-token terminator | Sakana v1 (reimplemented) | — |
| A7 | SEARCH/REPLACE patch applier | Paper2Code `4_debugging.py` | Apache-2.0 |
| B1 | Experiments journal tree (SQLite) | AIDE `journal.py` | MIT |
| B3 | Structured post-run review skill | AIDE `submit_review` | MIT |
| B4 | Budget controller + gate hook | PaperQA2 `settings.py` | Apache-2.0 |
| C4 | Failure classification enum | — (ecosystem gap) | — |
| Queue | Autonomous experiment queue | File-as-Bus (arXiv 2604.13018) | — |
| ZCM | Zero-cost monitor + autopilot loop | arXiv 2604.05854 | — |
| Dry-run gate | Pre-train sentinel + hook | arXiv 2604.05854 | — |
| Scheduled notes | Persistent cross-wakeup notes skill | Cognition blog | — |

Plus the pre-existing differentiators: pre-run audit, FTS5 `[LEARN]` DB, waterfall, pre-experiment checklist, ntfy preemption, living-doc pattern, `/deploy-team`, pre-commit gate, doc-guard.

### ⚠️ Stale ecosystem-gap claim (updated 2026-04-23)

**C4 failure-taxonomy gap is no longer an open ecosystem gap.** Three
2026 papers shipped taxonomies between February and April:

- arXiv **2603.06847** "Characterizing Faults in Agentic AI" — 37 types
  / 13 categories / 12 root-cause classes / 13 symptom classes, validated
  with 145 practitioners at 83.8% agreement.
- arXiv **2602.21806** "Bugs in Modern LLM Agent Frameworks" — 15 root
  causes × 7 symptoms × 5 lifecycle stages, 998 bugs mined from CrewAI
  + LangChain.
- arXiv **2604.17658** ErrorProbe — three-stage Strategist/Investigator/
  Arbiter diagnosis pipeline.

Our `bug | bad-hyperparam | bad-hypothesis` enum is still useful as a
*coarse* pre-classification that routes `[LEARN]` and `[DEAD-END]`, but
the "nobody owns this" framing in our README is wrong as of 2026-04-23.
The correct roadmap move is to **adopt 2603.06847's 13 categories as a
second enum field**, keeping our 3-value column as the pre-classifier.

### 🆕 New from the 60-day arXiv scan (2026-02-23 → 2026-04-23)

These jumped from "future" to "port this sprint" based on freshly-
published ablations or licenses:

- **Anthropic three-agent harness** (planner / generator / evaluator
  with context-reset, not compaction) — anthropic.com/engineering/
  harness-design-long-running-apps, 2026-03-24. Sustained a 6-hour,
  $200 autonomous run a solo agent couldn't match at $9. Composes
  directly with `/deploy-team`. Effort: M.
- **AiScientist File-as-Bus reference impl** — github.com/AweAI-Team/
  AiScientist. Ablation removing File-as-Bus drops MLE-Bench Lite by
  31.82 points (largest delta in any 2026 agentic-research paper we
  saw). We already cite 2604.13018 as inspiration for Queue; the code
  is now public. Upgrade `STATE.md`-as-string-file → structured
  workspace map.
- **HCC three-tier memory** (arXiv 2601.10402) + **Hindsight 20/20
  four-network memory** (arXiv 2512.12818, CC-BY 4.0) promote our
  "two-tier memory" roadmap item from design-stage to port-stage.
  Hindsight hits 83.6% vs 39% baseline on LongMemEval with a 20B.
- **Beyond pass@1 reliability metrics** (arXiv 2603.29231) — RDC / VAF
  / GDS / MOP. Meltdown rates hit 19% on frontier models, and
  **memory scaffolds universally DECREASED long-horizon performance**.
  Mandatory pre-port gate for the memory ports above.
- **MINJA + eTAMP memory-poisoning** (arXiv 2601.05504, 2604.02623).
  Our `[LEARN]` FTS5 is an attack surface now. Ship the GVU Verifier
  from the roadmap before autopilot phase 3.

### 🚧 Still in the roadmap

- A4 Three-mode search policy (AIDE) — depends on B1 (shipped); implementable as thin wrapper over journal.py + LLM prompt builders.
- B2 VLM plot reviewer — needs plot-generation contract design first.
- B5 Timeout → forced-final-answer failover — needs a direct Agent SDK integration point we don't have today.
- B6 Bias-probe panel reviewer — new /deploy-team template; 1-day port.
- B7 Planning-interval /replan — simple skill; waiting for a proven need.
- B8 Persona-parallel waterfall — cost-multiplier; hold until B4 budget is proven.
- C1 Staged macro-workflow — Sakana v2 reimplementation; needs journal tree transitions (has B1) + per-stage prompt templates.
- C2 Checkpoint/resume as JSON — nearly free given B1 (the DB *is* the checkpoint); add a `/snapshot` + `/restore` skill pair.
- C3 Best-so-far code pool — `code_pool` table schema shipped; CLI is TBD.
- C5 Semantic Scholar novelty loop — needs SS API wrapper.
- Two-tier memory (frozen brief + rolling log) — convention doc needed.
- GVU operator separation (Generator/Verifier/Updater for safe rule evolution) — design-heavy; revisit once `[LEARN]` DB grows.
- AgentRxiv-style embedding retrieval — parallel index to FTS5; waiting for a proven query-shape.

## Tier A — same-day wins (S effort, high leverage)

### A1. `[LEARN]` dead-end registry — ✅ SHIPPED
- **Source:** Kargatharaakash/ouroboros → `dead_ends.json` + `llm_agent.py`
- **What:** FTS5 table `dead_ends(direction, reason, killed_at, evidence_path)`
  auto-injected into brainstorm prompts, mirroring the `[LEARN]` pipeline.
- **Why now:** We already have "dead directions stay dead" as prose in
  AGENTS.md, but new subagents never see it. This makes it queryable.
- **Composes with:** `[LEARN]` pipeline — same capture pattern, separate table.
- **Effort:** S

### A2. Hypothesis calibration (predicted vs actual delta) — ✅ SHIPPED
- **Source:** Kargatharaakash/ouroboros → `hypothesis.py`
- **What:** Every experiment logs `predicted_delta` alongside the hypothesis;
  after the run, `actual_delta` is diffed. Rolls up into a calibration score.
- **Why now:** Upgrades pre-experiment-checklist item #1 from "state the
  hypothesis" to "state the hypothesis AND predict the delta."
- **Composes with:** `experiment-runs/` YAML — two new fields; new
  `hypothesis_calibration` view over workflow.db.
- **Effort:** S

### A3. Stuck detector — loop taxonomy
- **Source:** All-Hands-AI/OpenHands → `openhands/controller/stuck.py` L281–479
- **What:** Five concrete detectors over the event history: (a) repeating
  action-observation, (b) repeating action-error, (c) agent monologue,
  (d) alternating action-observation cycle, (e) condensation-error loop.
  Each returns `(loop_type, repeat_count, start_idx)`.
- **Why now:** We have preemption recovery but no *semantic* stuckness
  detection. Agents can spin silently for hours.
- **Composes with:** New PreToolUse hook reads recent transcript; emits
  a nudge or triggers `/replan` when stuck. New `[LEARN]` category
  `loop_type`.
- **Effort:** S (port detector logic; rebind to our event stream)

### A4. Three-mode search policy (draft / debug / improve)
- **Source:** WecoAI/aideml → `aide/agent.py` L61–92 (`search_policy`),
  L175–269 (prompt builders), L276–294 (`step`)
- **What:** Single function picks next action — *draft* if not enough
  initial attempts, *debug* w/ probability `debug_prob` on a random buggy
  leaf (bounded by `max_debug_depth`), else *greedy improve*. Atomic
  changes only.
- **Why now:** The AIDE agent loop is ~60 LOC + prompt strings; it's the
  best-studied ML-research agent loop and maps 1:1 to our Build+Run phases.
- **Composes with:** Waterfall picks *what*; this picks *which surviving
  variant to iterate on next*. Pre-run audit sits between policy and exec.
- **Effort:** S

### A5. Stage-gated task description
- **Source:** Sakana v2 → `treesearch/agent_manager.py` L216–247 (**reimplement**)
- **What:** Don't show the agent context it doesn't need yet. Stage 1-2
  agents don't see the experiment plan or risk factors; stage 3 sees the
  plan; stage 4 sees risk factors + limitations.
- **Why now:** Our AGENTS.md is always-on. Subtractive context is cheap
  leverage.
- **Composes with:** AGENTS.md grows `{{#stage:creative}} ... {{/stage}}`
  blocks that load-relevant-rules.sh respects.
- **Effort:** S

### A6. Convergence-token terminator
- **Source:** SakanaAI/AI-Scientist → `perform_review.py` L158 (pattern only)
- **What:** Reflection loops exit when the model emits a sentinel phrase
  (`"I am done"`) instead of burning N fixed rounds. Hard cap is backstop.
- **Why now:** Free quality-of-life improvement on every existing loop
  (our waterfall, /deploy-team, any reflection skill).
- **Composes with:** `/deploy-team` agent-done sentinel already uses
  `AGENT_DONE` — generalize the pattern.
- **Effort:** S (two lines per loop)

### A7. SEARCH/REPLACE patch format
- **Source:** going-doer/Paper2Code → `codes/4_debugging.py` L7–54 (parser),
  L88–102 (prompt)
- **What:** LLM emits `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks
  per file; parser does string-match-and-replace with `.NNN.bak` backups
  before overwrite.
- **Why now:** Cheaper than full-file rewrites; trivial rollback the
  audit agent can diff.
- **Composes with:** `/clean` sentinel validates, pre-commit-gate enforces.
- **Effort:** S

---

## Tier B — week-scale, high leverage

### B1. AIDE Journal / Node tree (SQLite-backed)
- **Source:** WecoAI/aideml → `aide/journal.py` full file, especially `Node`
  L21–101, `Journal.get_best_node` L172–180, `generate_summary` L182–192
- **What:** Dataclass tree `(parent, children, is_buggy, metric,
  debug_depth, analysis, stage_name)`. `MetricValue` + `WorstMetricValue`
  sentinels give clean `max()` semantics. `generate_summary()` dumps only
  good nodes for the next prompt.
- **Why now:** Replaces "EXPERIMENT_LOG.md is the source of truth" with a
  structured SQLite tree. Log becomes a rendered view. `debug_depth` is
  exactly what our audit agent needs. Unblocks B2, A4, and checkpoint/resume.
- **Composes with:** Extend `workflow.db` schema — don't fork a new DB.
  Reference `experiment-runs/` paths; don't re-store scripts.
- **Effort:** M (schema + migration + render pipeline)

### B2. VLM reviewer of training curves
- **Source:** Sakana v2 → `perform_vlm_review.py` L33+ / L126+ (**reimplement**)
- **What:** After each experiment, a vision model reviews generated plots:
  describes axes, flags "loss plateaus after X epochs", critiques captions,
  asks "is this figure informative or are all bars the same height?".
- **Why now:** Catches flat-curve failures that scalar metrics miss.
- **Composes with:** Plugs into Assess step. Feeds `[LEARN]` blocks. Sonnet
  vision works; no VLM-specific model dep.
- **Effort:** M (plot-generation contract + reviewer skill)

### B3. Structured post-run review (`submit_review`)
- **Source:** WecoAI/aideml → `aide/agent.py` L19–44, `parse_exec_result`
  L296–339
- **What:** After every run, separate LLM call with a JSON-schema-constrained
  tool returns `{is_bug, summary, metric, lower_is_better}`. Metric
  direction *inferred from the run*.
- **Why now:** Closes Assess→Codify automatically — auto-emits `[LEARN]`
  when `is_bug=true`.
- **Composes with:** Our pre-run audit stays put; this is post-run.
- **Effort:** S

### B4. Budget controller
- **Source:** Future-House/paper-qa → `src/paperqa/settings.py`
- **What:** Centralized dataclass with `max_timesteps`, `timeout=500s`,
  `max_concurrent_requests=4`, `evidence_k=10`, `max_answer_attempts`.
  Every subsystem reads from one place.
- **Why now:** No global budget ceiling today. `$`-tracking with hard abort
  is an open ecosystem gap we can own.
- **Composes with:** `.codex/budget.toml` + PreToolUse hook that reads
  cumulative token/wallclock/$ and aborts over threshold.
- **Effort:** S

### B5. Timeout → forced-final-answer failover
- **Source:** Future-House/paper-qa → `agents/main.py` `_run_with_timeout_failure()`
- **What:** On timeout, forcibly invokes a `GenerateAnswer` tool and marks
  status `TRUNCATED` instead of crashing. Retries malformed-message
  exceptions via `tenacity`.
- **Why now:** Our research/audit subagents currently have no graceful
  degradation path.
- **Composes with:** Wrap Agent invocations; save partial work to
  `experiment-runs/`.
- **Effort:** S

### B6. Bias-probe panel reviewer
- **Source:** SakanaAI/AI-Scientist → `perform_review.py` L10–15, L125–140
  (**reimplement**)
- **What:** N reviewers with positive-bias prompt + N with negative-bias
  prompt; meta-reviewer synthesizes consensus. Reflection-convergence
  token terminates.
- **Why now:** Upgrades our single audit agent into a bracketed panel for
  go/no-go on expensive runs.
- **Composes with:** New `/deploy-team` template (`audit-panel.json`).
- **Effort:** M

### B7. Planning-interval / `/replan`
- **Source:** huggingface/smolagents → `src/smolagents/agents.py` L541–741
- **What:** Every `planning_interval` steps the agent pauses, reviews
  remaining steps, and emits a fresh plan. Prior planning messages stripped
  to avoid anchoring.
- **Why now:** Long-running auto-sync sessions never re-plan → drift.
  Naturally pairs with A3 (re-plan on stuck).
- **Composes with:** New `/replan` skill; hook-triggered every N tool calls.
- **Effort:** S

### B8. Persona-guided parallel waterfall agents
- **Source:** stanford-oval/storm → `knowledge_storm/storm_wiki/modules/
  knowledge_curation.py` (`_run_conversation`)
- **What:** One conversation simulator per persona; each generates
  perspective-specific questions in parallel; dedupe into an
  `InformationTable`.
- **Why now:** Upgrades Brainstorm/Attack from one agent to N persona-tagged
  agents (theorist / skeptic / empiricist / literature-hawk).
- **Composes with:** `/deploy-team` already has worktrees — add persona
  templates + dedupe pass.
- **Effort:** M (cost-multiplier; gate on B4 budget controller)

---

## Tier C — strategic, bigger bites

### C1. Staged macro-workflow (Sakana v2 reimplementation)
- **Source:** Sakana v2 → `treesearch/agent_manager.py` L143–167, L343–536
  (**reimplement**)
- **What:** 4-stage state machine above the waterfall: initial → baseline-tune
  → creative → ablation. Per-stage goals + LLM-evaluated completion. Best
  node of stage N seeds stage N+1.
- **Why now:** The *macro* loop AIDE lacks. Sits above `search_policy`.
- **Composes with:** Waterfall becomes the stage-transition gate. Each
  stage has its own pre-experiment checklist view.
- **Effort:** M (1 week)

### C2. Checkpoint/resume as JSON
- **Source:** Sakana v2 PR #90, AgentLab phase-pickling — **both reimplement
  as JSON**, not pickle. Pickle is fragile across Python versions.
- **What:** JSON snapshot of STATE.md + pool + FTS5 offset pointer at phase
  boundaries.
- **Why now:** Our ntfy chain handles process preemption but not state
  preemption.
- **Composes with:** If B1 (Journal in SQLite) ships first, this is nearly
  free — the DB *is* the checkpoint.
- **Effort:** S if after B1, M standalone

### C3. Best-so-far code pool with random restart
- **Source:** SamuelSchmidgall/AgentLaboratory → `mlesolver.py` L213–271
- **What:** Size-K pool of highest-scoring code snapshots; iteration samples
  a parent from pool, mutates, scores, displaces worst if better.
- **Why now:** Search-frontier structure for multi-day runs. Composes with B1.
- **Composes with:** Pool lives in SQLite; audit agent gates admissions.
- **Effort:** S

### C4. Failure classification enum
- **Source:** (gap across all harnesses — none cleanly separate these)
- **What:** Three-value enum on every post-run review: `bug | bad-hyperparam
  | bad-hypothesis`. Added to `experiment-runs/` schema and B3's review.
- **Why now:** Nobody owns this yet — ecosystem gap. Prevents the
  `[LEARN]`-DB from conflating fix-the-code with reject-the-idea.
- **Composes with:** B3 review, `[LEARN]` category routing.
- **Effort:** S

### C5. Semantic Scholar novelty loop
- **Source:** SakanaAI/AI-Scientist → `generate_ideas.py` L372–430
  (**reimplement**)
- **What:** LLM picks search queries, hits Semantic Scholar, reads top-10
  abstracts + citations, loops until commits to novel / not-novel.
- **Why now:** Strengthens Research-agent stage with structured multi-turn
  evidence loop.
- **Composes with:** Captures top-3 paper IDs into FTS5 so future runs
  retrieve prior verdicts.
- **Effort:** M (SS API rate limits)

---

## Explicit rejects (load-bearing — don't revisit)

- **Paper/LaTeX writeup pipelines** — out of scope for ML research harness
- **Full RAG over paper corpora** (PaperQA2) — we don't have a fixed
  corpus worth indexing; revisit only if we add one
- **smolagents AST sandbox** — not a real sandbox; author admits escapes
- **AutoGen / CrewAI** — pure orchestration DSL; Codex Agent SDK covers it
- **HITL prompts** — we are autonomous-first; ntfy + pre-commit gate cover escapes
- **Ouroboros self-rewriting methodology loop** — metric-gaming risk; our
  `[LEARN]` + dead-ends covers ~80% without unsupervised AGENTS.md rewrites
- **AI-Scientist NeurIPS 9-dim rubric** — designed for *papers*, not code
- **AI-Researcher `idea_agent` self-novelty scoring** — strictly worse
  than our Attack→Validation stages; opaque self-scoring
- **Paper2Code 4-stage planning** — our pre-experiment checklist covers it

---

## Recommended 90-day port order (dependency-ordered)

**Week 1** — Tier A foundation (all S):
  1. A1 dead-end registry (trivial FTS5 pipeline)
  2. A2 hypothesis calibration (two YAML fields + diff)
  3. A6 convergence token (two lines per loop)
  4. A7 SEARCH/REPLACE patch format
  5. A5 stage-gated task description

**Week 2-3** — Tier A agent-loop:
  6. A3 stuck detector (port + rebind event stream)
  7. A4 three-mode search policy

**Week 4-6** — Tier B infrastructure:
  8. B1 AIDE Journal in SQLite (unblocks C2 + C3)
  9. B3 structured post-run review
  10. B4 budget controller
  11. B5 timeout failover

**Week 7-9** — Tier B quality:
  12. B2 VLM reviewer
  13. B7 `/replan` skill
  14. B6 bias-probe panel

**Week 10-12** — Tier C strategic:
  15. C2 checkpoint/resume (free post-B1)
  16. C3 best-so-far pool
  17. C4 failure classification
  18. C1 staged macro-workflow

B8 persona-parallel and C5 novelty loop are stretch goals — hold until
budget controller (B4) is live and validated.
