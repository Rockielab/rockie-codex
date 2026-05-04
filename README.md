# rockie-codex

Apache-2.0 Codex port of `rockie`, a local-first research harness built
around hooks, skills, and a SQLite memory layer.

## What it gives you

- A per-project memory DB at `.codex/memory/workflow.db` with FTS5-backed `[LEARN]` and `[DEAD-END]` recall
- Repo-scoped Codex skills under `.agents/skills/`
- Guardrails like `pre-commit-gate`, `pre-train-gate`, `budget-gate`, `doc-guard`, and `stuck-detector`
- A taste/onboarding flow that writes `.rockie/taste/`
- Two team orchestration paths:
  - `deploy-team` as a repo-local Python/Codex CLI workflow
  - `deploy-team-dashboard` as a user-global Node dashboard workflow

## Honest Codex deltas

- Project hooks live in `.codex/hooks.json`; user-global hooks live in `~/.codex/hooks.json`.
- Project skills live in `.agents/skills/`; user-global skills live in `~/.codex/skills/`.
- `AGENTS.md` replaces `CLAUDE.md`.
- Historical slash names like `/onboard`, `/mode`, and `/clean` are retained as shorthand in docs, but in Codex you typically invoke the skill via `$onboard`, `$mode`, `$clean`, or natural language.
- Codex has no `PreCompact` hook event. The legacy `memory-pre-compact.sh` backstop is shipped and mapped to `Stop`; details are in [docs/EVENT-MAPPING.md](/Users/samuellarson/rockie-codex/docs/EVENT-MAPPING.md).
- The dashboard orchestrator accepts legacy model aliases and maps them to Codex models:
  - `haiku` → `gpt-5.4-mini`
  - `sonnet` → `gpt-5.4`
  - `opus` → `gpt-5.5`

## Install

```bash
git clone https://github.com/saml212/rockie-codex.git ~/rockie-codex
cd ~/rockie-codex
./install.sh ~/path/to/your/project
```

That installs:

- project runtime into `<project>/.codex/`
- project skills into `<project>/.agents/skills/`
- user-global dashboard/runtime helpers into `~/.codex/` unless `--project-only` is used

Then:

```bash
cp ~/rockie-codex/agents-md/AGENTS.md.template ~/path/to/your/project/AGENTS.md
```

For a first session, ask Codex to use `$onboard`.

## Verify

```bash
bash tests/smoke-test.sh
```

The smoke suite currently covers 75 assertions, including installer idempotency, hook behavior, DB initialization, migrations, FTS recall, autopilot safety parsing, and fake-provider GPU routing.

## Repo layout

```text
project-extension/
  codex/          # repo-installed hooks, scripts, memory schema, hooks.json
  agents/skills/  # repo-installed Codex skills
user-extension/
  codex/          # home-installed hooks, scripts, teams, user skills
agents-md/        # AGENTS.md templates
docs/             # public architecture, install, and mapping docs
tests/            # smoke suite + fakes
```

## Core docs

- [docs/EVENT-MAPPING.md](/Users/samuellarson/rockie-codex/docs/EVENT-MAPPING.md)
- [docs/ARCHITECTURE.md](/Users/samuellarson/rockie-codex/docs/ARCHITECTURE.md)
- [docs/install.md](/Users/samuellarson/rockie-codex/docs/install.md)
- [docs/quickstart.md](/Users/samuellarson/rockie-codex/docs/quickstart.md)
- [docs/PORTS.md](/Users/samuellarson/rockie-codex/docs/PORTS.md)

## Status

This repo is a public Codex-native port, not a claim of feature-perfect parity with the original Claude-targeted harness. The current behavior is documented, tested, and intentionally explicit about the remaining runtime differences.
