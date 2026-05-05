---
name: clean
description: Pre-commit anti-slop audit — checks staged/dirty files for code slop (debug artifacts, single-use helpers, dead imports) AND documentation slop (stale claims, broken internal links, new .md files, redundant sections). Writes a sentinel so the pre-commit-gate hook lets the commit through. MUST be invoked before `git commit` in this repo. Triggers when the agent is about to commit, when user says "commit", "clean", "ready to commit", or when the pre-commit-gate hook blocks.
---

# /clean — Pre-commit audit adapted for a research repo

Research repos are typically majority prose — scripts, experiment dirs,
and many `.md` docs read by humans AND future agents. Slop in either
kind hurts. The audit covers both.

## When to run

- Before EVERY `git commit`. The `pre-commit-gate` hook will block if the
  sentinel hash doesn't match current staged state.
- When the user asks to commit.
- When the hook emits a block message.

## What the skill does

1. Runs `.agents/skills/clean/audit.py`. Arguments:
   - `--scope staged` (default) — audits files in `git diff --cached --name-only`
   - `--scope dirty` — audits all modified + untracked non-gitignored files
2. The audit reports findings in three buckets:
   - **Blockers** — must fix before commit (new `.md` files created during
     cleanup runs, broken internal doc links, obvious debug artifacts,
     syntax errors)
   - **Warnings** — should review (TODO markers pointing to resolved work,
     duplicate content across docs, rules contradicting `.codex/memory/workflow.db`)
   - **Info** — worth knowing (file size growth, complexity spikes)
3. If zero blockers: the skill writes
   `.codex/.state/clean-ok-<hash>` where `<hash>` is computed by
   `.codex/scripts/compute_clean_hash.sh`. The pre-commit-gate hook
   recomputes the same hash and requires the sentinel to exist.
4. If blockers exist: the skill reports them and does NOT write a
   sentinel. Agent fixes, reruns.

## Hard rules for this repo specifically

- **NEVER create new `.md` files during cleanup.** Consolidate into
  existing ones. Exception: a user explicitly says "write a new doc for X."
- **NEVER auto-fix documentation.** Flag it, let agent or user decide.
- **NEVER audit the whole codebase.** Only changed files. Existing slop
  elsewhere is not this commit's problem.
- Thresholds apply to NEW code only: Python funcs ≤ 80 lines, cyclomatic
  complexity ≤ 8. Existing violations are noise.
- Degrade gracefully: if `ruff` / `shellcheck` / `code-simplifier` isn't
  installed, skip that check with a note. Don't block.

## Escape hatch

Emergency / docs-only / initial-bootstrap commits can use:

```bash
CLEAN_BYPASS=1 git commit -m "..."
```

The hook honors this. Don't use it routinely.

## Agent invocation

When this skill fires, the agent should:

1. Run `python3 .agents/skills/clean/audit.py --scope staged` (or `--scope dirty` if nothing is staged yet).
2. Read the JSON report on stdout.
3. For each blocker, fix the underlying issue (remove stray `console.log`, delete the new `.md` file, repair the broken link, etc.).
4. For warnings, apply judgment — fix if obvious, leave for user if contested.
5. Re-run the audit until zero blockers.
6. The audit writes the sentinel automatically on zero-blocker pass.
7. Proceed with `git commit`.

If a user invokes `/clean` directly (not agent-automatic), print the
report in human-readable form and wait for their direction on fixes.

## Post-audit hook

After the sentinel writes successfully (zero blockers), surface a
soft-prompt to the user — once per audit, never auto-invoked:

> Audit clean. Anything in this session worth upstreaming to
> `saml212/rockie-codex`? Run `$upstream-contribute` to scan the
> session for generalizable patterns (pruning fixes, small skill
> improvements, new hooks, cross-discipline capabilities) and dispatch
> a writer sub-agent to fork, branch, smoke-test, and open a PR.

Rules for this nudge:

- Print only when the audit passes with zero blockers.
- Print at most once per audit run; suppress on re-runs in the same
  session.
- Never auto-invoke `$upstream-contribute` — the user opts in by
  invoking the skill explicitly. The meta-loop is user-driven, not
  automatic.
- If `[LEARN harness-upstream]` or `[LEARN cross-discipline]` rows
  were added in the last 6 hours, prepend a one-line teaser noting
  the count. (Optional polish; skip if querying the DB would slow
  the audit.)

