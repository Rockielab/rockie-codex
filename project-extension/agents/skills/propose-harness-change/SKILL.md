---
name: propose-harness-change
description: Package a harness-level improvement (a new hook, a fixed script, an improved skill) as a reviewed, verified patch — optionally openable as a PR against the rockie upstream repo. Uses Generator/Verifier/Updater role separation so the proposing agent never auto-commits; a fresh-context verifier plus the smoke test must agree, and the human signs off before anything is written to the user's rockie checkout or pushed anywhere. Triggers when the user says "upstream that", "propose a harness change", "write a PR for rockie", or when a recent `[LEARN harness-upstream]` block is waiting.
---

# /propose-harness-change — safe self-improvement

Autonomous research harnesses that let the agent edit themselves tend
to drift (MINJA / eTAMP memory-poisoning, arXiv 2603.29231's finding
that "memory scaffolds universally decrease long-horizon reliability",
the Ouroboros "AGENTS.md rewrite" footgun). rockie's discipline is
**Generator / Verifier / Updater separation** — nobody is allowed to
propose, verify, and commit in the same role.

## The three roles

### Generator (the proposing agent)
- Writes the diff against a LOCAL CLONE of the rockie source repo.
- Writes a short rationale: what pattern broke, why the fix composes
  with existing differentiators, what smoke-test assertion(s) prove it.
- **Never** commits directly. Produces a patch file
  `~/rockie-proposals/<YYYY-MM-DD-slug>/patch.diff` plus
  `rationale.md`, `test.sh` (the specific smoke-test snippet).

### Verifier (fresh-context audit agent)
- Dispatched via the `Agent` tool with NO prior context.
- Reads the patch + rationale, the files being touched, and the
  `CONTRIBUTING.md` composition rules.
- Must answer four questions with evidence:
  1. Does this compose with the existing differentiators, or duplicate
     one of them?
  2. Does the smoke test actually test the claimed improvement?
  3. Is the change local (one file) or does it ripple across the schema?
  4. Is there a path-traversal, SQL-injection, or shell-injection
     regression?
- Returns `APPROVE` | `CHANGES_REQUESTED` | `REJECT` with a short report.

### Updater (the human)
- Reviews Verifier report + diff.
- Runs `bash tests/smoke-test.sh` in the rockie clone — must be green.
- If everything looks right, runs `scripts/apply_upstream_patch.sh
  <proposal-dir>` which commits the diff locally with the rationale as
  the commit message, then offers `gh pr create`.
- The human — not the agent — chooses when to push.

## Invocation

Normal flow (agent finds a harness-level improvement during work):

```
[LEARN harness-upstream] apply_patch.py should normalize Windows line endings before SEARCH match
```

The Stop hook captures this as a durable learning with category
`harness-upstream`. When the user next says "let's upstream pending
improvements" (or runs the skill explicitly), `/propose-harness-change`:

1. Queries `learnings` for all `category='harness-upstream'` rows not
   yet upstreamed.
2. For each, the Generator writes the patch + rationale + test.
3. Dispatches a fresh-context Verifier via the `Agent` tool.
4. Reports the verdict to the user; does NOT open a PR without
   explicit human go-ahead.

## What qualifies as a harness-level improvement

**Yes:**
- A bug in a hook or script that affects any user.
- A new smoke-test assertion that catches a general-purpose regression.
- A new AGENTS.md section that generalizes (not domain-specific).
- A dep-free performance fix.

**No (keep these in your own fork):**
- Domain-specific changes (e.g. an ML-preset rule that doesn't generalize).
- Anything that depends on your private config.
- "Nice to have" re-formatting.
- Schema changes without a migration file.

## Refusal paths

The Generator must refuse to produce a patch if:

- The change touches `memory/schema.sql` without a companion migration
  file in `memory/migrations/NNN_*.sql`.
- The change modifies the Verifier's own definition (i.e. tries to edit
  this skill file or the Agent-tool prompt that dispatches the Verifier).
  That's the canonical self-improvement footgun — the Updater can change
  this by ordinary PR, but the Generator can't.
- The change adds a network dep that isn't already in `NOTICE`.
- The smoke test can't be updated to verify the claim.

## Open questions (roadmap)

- Automating `gh pr create` is deliberately NOT shipped until the
  Verifier has run on at least 20 real proposals and we've seen the
  false-approve rate.
- The Verifier is single-agent today. A bias-probe panel (two
  Verifiers with opposite priors + a meta-Verifier) is future work.
