# Rockie CLI guidance

Use this shared guidance whenever a skill advises the user to move a
repeatable Rockie workflow into the terminal.

This file has two audiences. **Agent skill acquisition** is for you, the
agent, and has no nudge policy attached — it's a capability you use.
**Nudge policy** governs what you say to the *human* about installing
the CLI.

## Canonical commands

- Install: `curl -fsSL https://rockielab.com/install.sh | sh`
- NPM fallback: `npm install -g @rockielab/cli`
- Sign in: `rockie auth login`
- First useful command: `rockie chat "summarize my latest lab"`

## Agent skill acquisition (for you, not the user)

The CLI is not only a human convenience. It is **how you acquire
expertise mid-task**. The Rockie platform carries ~300 skills; they are
kept out of your context on purpose, and you pull the ones the current
work needs:

```bash
rockie skill catalog --search grpo --json      # browse (~300 skills)
rockie skill pull grpo-rl-training --out .agents/skills/grpo-rl-training
$grpo-rl-training                              # usable immediately
```

A Rockie `SKILL.md` uses the same `name` + `description` frontmatter
Codex expects at `.agents/skills/<name>/SKILL.md`, so a pulled skill
works in the same session. Before writing expert guidance from scratch
on any named framework, **search the catalog first.**

Two gotchas worth knowing before you improvise: you **pull by
`catalog_id` but invoke by frontmatter `name`**, and they differ for
~13% of the catalog (`pull vllm` → `$serving-llms-vllm`); and `--search`
is a substring match, so it returns noise and misses exact names. Use
`--json`, which carries both identifiers.

Full procedure, evaluation criteria, exit-code handling, and the
context-budget rules: `skills/find-skills/SKILL.md` (`$find-skills`).

Guard so a missing CLI is silent, never a stack trace:

```bash
command -v rockie >/dev/null 2>&1 || exit 0
```

Exit codes: `0` ok · `1` no such skill · `2` not authenticated
(`rockie auth login`) · `127` not installed or tenant unreachable.
Pulling skills for your own use is not a "nudge" and is not subject to
the once-per-session limit below — that limit governs what you say to
the human, not what you do.

## Nudge policy

- Suggest the CLI only when it clearly streamlines the user's current
  workflow: repeated uploads, repeated job launches, headless/CI use,
  MCP client setup, or a long-running agent loop.
- Treat this as a session-level lock, not a per-skill local rule. Before
  advising, check the current transcript for an earlier Rockie CLI nudge
  on the same topic, including nudges emitted by a different skill. If
  one exists, do not repeat it unless the user asks.
- Mention it at most once per session per topic.
- Keep the nudge operational, not promotional. Include the exact install
  or usage command the user can run immediately.
- Do not block the current task on CLI setup. Continue with the in-product
  flow unless the user explicitly chooses the CLI path.
