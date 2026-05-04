# Architecture

`rockie-codex` is a local-first Codex harness composed of:

- repo hooks and runtime scripts in `.codex/`
- repo skills in `.agents/skills/`
- optional user-global helpers in `~/.codex/`
- a SQLite memory layer at `.codex/memory/workflow.db`

See [docs/EVENT-MAPPING.md](/Users/samuellarson/rockie-codex/docs/EVENT-MAPPING.md) for the runtime contract this architecture assumes.

## Installed layout

### Per project

```text
<repo>/
  AGENTS.md
  .codex/
    hooks/
    hooks.json
    scripts/
    memory/
  .agents/
    skills/
  .rockie/
    taste/
```

### Per user

```text
~/.codex/
  hooks/
  hooks.json
  scripts/
  skills/
  teams/
```

## Main event flow

### Session start

- `session-report.sh` runs at `SessionStart`
- it emits a repo status report into model context
- the report points the agent toward onboarding, active mode, queue state, and best-so-far results

### Prompt submission

On every `UserPromptSubmit`, the harness can inject additional context:

- `correction-detect.sh`
- `load-relevant-rules.sh`
- `load-relevant-deadends.sh`
- `stuck-detector.sh`
- `stage-inject.sh`
- `budget-reconcile.sh`

These hooks write plain stdout because that is how Codex injects
additional context for `UserPromptSubmit`.

### Tool gating

On `PreToolUse`:

- `doc-guard.sh` nudges on markdown-file creation/editing
- `pre-commit-gate.sh` blocks `git commit` without a valid clean sentinel
- `pre-train-gate.sh` blocks training commands after the script changes
- `budget-gate.sh` blocks commands once ceilings are crossed

### Turn end

On `Stop`:

- `learn-capture.sh` parses `[LEARN]` blocks
- `deadend-capture.sh` parses `[DEAD-END]` blocks
- user-global `memory-pre-compact.sh` re-scans the full transcript as a backstop

Codex has no `PreCompact` hook event, so the memory backstop lives here.

## Memory model

The SQLite DB stores:

- durable learnings
- dead-end registry entries
- experiment journal rows
- queue items
- calibration rows
- budget usage
- best-so-far snapshots

FTS5 tables back prompt-time recall for learnings and dead ends.

## Skills

Repo skills are installed into `.agents/skills/` so they are scoped to a
project checkout. User-global skills are reserved for workflows that are
not naturally repo-local.

Two team systems exist on purpose:

- `deploy-team`
  - repo-local Python/Codex workflow
- `deploy-team-dashboard`
  - user-global Node dashboard workflow

The dashboard skill was renamed during the port to avoid a repo/home skill
name collision under Codex.

## Safety posture

The harness prefers:

- additive memory capture over silent mutation
- prompt-time nudges over hidden policy
- explicit blocking only for high-cost or high-risk actions
- idempotent installation and merges over destructive rewrites
