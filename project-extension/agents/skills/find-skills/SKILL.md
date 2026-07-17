---
name: find-skills
description: Pull expert skills into this harness from the Rockie platform catalog (~300 skills across ML training/inference, biology, chemistry, physics, databases, coding). Use BEFORE writing domain guidance from scratch or fumbling an unfamiliar framework — if the task names a library (vLLM, GRPO, TRL, AlphaFold, DuckDB, LAMMPS), check the catalog first. Browse `rockie skill catalog --search X --json`, pull into `.agents/skills/`, invoke immediately. Silently no-ops when the Rockie CLI is absent or logged out.
---

# $find-skills — mine the Rockie skill catalog

The Rockie platform ships ~300 skills. **They are deliberately not in
your context.** Loading 300 descriptions at every session start would
cost more than the skills are worth. Instead the catalog sits behind the
CLI, and you pull the two or three that match the work in front of you.

That is the whole design: **the catalog is your library card, not your
bookshelf.** This skill is how you use it.

A Rockie `SKILL.md` uses the same `name` + `description` frontmatter
Codex expects at `<repo>/.agents/skills/<name>/SKILL.md` (see
`docs/EVENT-MAPPING.md` § Verified runtime layout). A pulled skill is
usable in the same session — no restart, no registration step.

## When to reach for this

- The task names a framework/library/tool you'd otherwise wing it on
  (vLLM, verl, Unsloth, TRL, SGLang, RDKit, Biopython, DuckDB, …).
- You're about to write a long block of domain guidance from memory.
- You're entering a domain the project hasn't touched before.
- The user asks "is there a skill for X?"

**Check the catalog before writing expert guidance from scratch.** A
pulled skill is written by someone who has actually run the thing.

## Browse

```bash
rockie skill catalog --search grpo --json
rockie skill catalog --category ml-inference --json
rockie skill catalog --json                       # everything
```

**Always use `--json`.** Not for parsing convenience — because the
tab-delimited form omits a field you need. Shape:

```json
{"skills": [{"name": "verl-rl-training", "catalog_id": "verl",
             "description": "...", "category": "ml-training", "resources": [...]}],
 "catalog_revision": "f138f4b…",
 "tenant_visible_count": 296}
```

### The two identifiers — read this before you pull

`name` and `catalog_id` are **different fields and both matter**. They
differ for 39 of 297 catalog entries (~13%):

| field | what it is | you use it for |
|---|---|---|
| `catalog_id` | the catalog slug (shown as `/slug` in tab output) | **`rockie skill pull <catalog_id>`** |
| `name` | the skill's frontmatter name | **invoking it: `$<name>`** |

Verified example — `catalog_id: vllm`, `name: serving-llms-vllm`:

```bash
rockie skill pull serving-llms-vllm --out /tmp/x   # 404 not_found, exit 1
rockie skill pull vllm --out .agents/skills/vllm   # works, 5 files
# …and the pulled SKILL.md's frontmatter says `name: serving-llms-vllm`,
# so you invoke $serving-llms-vllm — NOT $vllm.
```

**Pull by `catalog_id`. Invoke by `name`.** Guessing either from the
other fails on ~13% of the catalog.

### `--search` is a substring match, not a search engine

It matches raw substrings across names and descriptions, so it is both
noisy and prone to missing exact names:

- `--search verl` returns **geopandas** — its description contains
  "o*verl*ay operations". It does not lead with `verl` itself.
- `--search vllm` returns `hqq-quantization` (description mentions vLLM).

So: don't trust the top hit, and don't conclude a skill is absent
because a name search missed it. Prefer `--category` for a clean sweep,
and read descriptions before choosing. A search with no hits is
**success with an empty list** (`{"skills":[]}`, exit 0), not an error.

Categories as of writing: `ml-training` (52), `biology` (43),
`databases` (32), `llm-tools` (31), `chemistry` (23), `physics` (23),
`coding` (20), `rockie-workflows` (19), `data-engineering` (10),
`writing` (10), `research` (10), `visualization` (8), `ml-inference`
(8), `quantum` (4), `other` (4). Derive the live list from `--json`
rather than trusting these counts to stay current.

## Evaluate before pulling

Read the `description` field. Pull the two or three that match; do not
pull a whole category. Each pulled skill costs a description in every
future session start — see *Context budget* below.

## Pull

```bash
rockie skill pull grpo-rl-training --out .agents/skills/grpo-rl-training
```

Repo-local Codex skills live in `.agents/skills/<name>/SKILL.md` — that
is the path Codex reads, so pull straight into it. Verified shape of a
pull:

```
.agents/skills/grpo-rl-training/
  SKILL.md                              # name + description frontmatter
  README.md
  examples/reward_functions_library.py
  templates/basic_grpo_training.py
```

`--json` emits `{"name": "grpo-rl-training", "files": 4, "dir": "..."}`.

Then confirm what it's actually called before invoking it:

```bash
head -3 .agents/skills/grpo-rl-training/SKILL.md   # frontmatter `name:` = the slug
```

Invoke `$<that name>` (Codex has no repo-defined slash commands — see
`docs/EVENT-MAPPING.md` § Skill invocation delta; natural language works
too: "use the grpo-rl-training skill"). Its bundled `examples/` and
`templates/` are real files on disk — read them.

## Your tenant's own overlay

`rockie skill list` shows your tenant's writable overlay (`--json` →
`{"skills":[{"name":"…"}]}`) — a **separate namespace** from the
catalog, ~300 entries. `pull` resolves against it too, so overlay
entries are pullable by name even when `catalog --search` doesn't
surface them. If you're looking for a skill you believe exists and the
catalog search comes up empty, check `rockie skill list` before
concluding it isn't there.

## Context budget — the point of all this

Every `SKILL.md` description in `.agents/skills/` loads at **every**
session start, forever. One pulled skill ≈ 30–80 tokens per session for
the life of the project.

- Pull what the current work needs. Not what might be nice.
- When a direction is done, `rm -rf .agents/skills/<name>`. It's one
  command to pull it back.
- Never bulk-pull a category "to have it".

## When the CLI isn't there

The CLI may be absent, logged out, or unreachable. **Never block the
session on it, never retry in a loop, never nag.**

| exit | meaning | what you do |
|---|---|---|
| `0` | worked | proceed |
| `1` | no such skill (`pull`) | re-check the name against `catalog --search` |
| `2` | not authenticated | mention `rockie auth login` **once**, then carry on without it |
| `127` | not installed, or tenant unreachable | say nothing; carry on |

Guard before you call, so a missing CLI is silent rather than a stack trace:

```bash
command -v rockie >/dev/null 2>&1 || exit 0
```

If the CLI is missing and the catalog would genuinely have helped, you
may mention `curl -fsSL https://rockielab.com/install.sh | sh` **at most
once per session** — see `skills/cli-guidance.md` for the nudge policy.
A user without the CLI is not a broken user. Do the work anyway.
