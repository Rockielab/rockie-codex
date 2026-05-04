# Event Mapping

This document records the real Codex runtime contract used by
`rockie-codex`. It is the source of truth for port decisions.

## Verified runtime layout

- Repo hooks: `<repo>/.codex/hooks.json`
- User hooks: `~/.codex/hooks.json`
- Repo skills: `<repo>/.agents/skills/<name>/SKILL.md`
- User skills: `~/.codex/skills/<name>/SKILL.md`
- Repo instructions: `AGENTS.md`

These paths were verified against the public `openai/codex` source on
2026-05-04.

## Hook event mapping

| Original rockie assumption | Codex event | Port decision |
|---|---|---|
| `SessionStart` | `SessionStart` | Direct port |
| `UserPromptSubmit` | `UserPromptSubmit` | Direct port |
| `PreToolUse` | `PreToolUse` | Direct port |
| `Stop` | `Stop` | Direct port |
| `PreCompact` | no equivalent | `memory-pre-compact.sh` is shipped and registered under `Stop` as a full-transcript backstop |

## Output semantics that mattered

- `SessionStart` plain stdout or JSON `additionalContext` is injected into model context.
- `UserPromptSubmit` plain stdout or JSON `additionalContext` is injected into model context.
- `PreToolUse` does not support model-context injection. It can only advise or block.
- `Stop` is useful for capture/backstop work but is not a replacement for a true pre-compaction lifecycle event.

That is why several hooks in this port were changed from `stderr` nudges to
plain stdout on `UserPromptSubmit`.

## Skill invocation delta

The original harness used custom slash-command language like `/onboard`,
`/mode`, and `/clean`. Codex does not expose repo-defined slash commands in
that way.

In this port:

- those names remain as historical nicknames in docs and prompts
- the practical invocation path is `$onboard`, `$mode`, `$clean`, or natural language

## Team-orchestrator deltas

There are two team systems in this repo:

- `deploy-team`
  - repo-local Python orchestrator
  - lives under `.agents/skills/deploy-team/`
- `deploy-team-dashboard`
  - user-global Node dashboard orchestrator
  - lives under `~/.codex/skills/deploy-team-dashboard/`

The dashboard skill was renamed from the original user-global `deploy-team`
to avoid a repo-skill/home-skill name collision in Codex.

## Model alias mapping

The dashboard orchestrator accepts both Codex model names and legacy Claude
aliases:

- `haiku` → `gpt-5.4-mini`
- `sonnet` → `gpt-5.4`
- `opus` → `gpt-5.5`

The `permissions` array in the dashboard config is accepted only as a legacy
compatibility field. `codex exec` has no `--allowed-tools` equivalent, so the
field is currently ignored.
