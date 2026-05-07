#!/usr/bin/env python3
"""Seed workflow.db with generic harness-level rules.

Idempotent: skips rows whose (project, category, rule) already exists. Safe
to re-run on an existing DB.

This file seeds ONLY harness-level rules that apply to any project using
rockie. To seed project-specific rules (architecture gotchas, training
lessons, etc.), copy examples/seed_example_ml_research.py to a file in your
own repo and edit it. Do NOT add your project's rules here — this file is
the rockie default and should stay generic.

Project name is derived from the parent repo's directory name (the repo
that this .codex/ lives inside). Override with the PROJECT env var if you
want an explicit name (e.g. CI, detached worktree).
"""
import os
import pathlib
import sqlite3

DB = pathlib.Path(__file__).resolve().parent.parent / "memory" / "workflow.db"


def resolve_project() -> str:
    env = os.environ.get("PROJECT")
    if env:
        return env
    # project-extension/codex/scripts/ → project-extension/codex/ → <repo>/.codex/ → <repo>
    return pathlib.Path(__file__).resolve().parents[2].name


PROJECT = resolve_project()

# (category, rule, mistake_or_None, correction_or_None)
SEEDS = [
    # ── Process (generic research discipline) ─────────────────────────────
    ("process", "Verify claims before stating them", None,
     "Use web search or research agents. Never assert facts without evidence."),
    ("process", "Audit code with a separate agent before running experiments", None,
     "The implementer does not review their own work."),
    ("process", "Smoke test every model before training", None,
     "Forward pass, backward pass, gradient check."),
    ("process", "Dead directions stay dead", None,
     "Don't revisit archived ideas unless the user asks."),
    ("process", "Save the exact script alongside experiment results", None,
     "Reproducibility requires the actual code that ran, not a description."),
    ("process", "Log everything to a file; produce a human-readable summary", None,
     "Raw logs are for debugging; summary is for the next agent."),

    # ── Harness-level invariants ──────────────────────────────────────────
    ("harness", "Pin sqlite3 to /usr/bin/sqlite3, not PATH default",
     "Some distros ship sqlite3 builds without FTS5 on PATH.",
     "Hardcode /usr/bin/sqlite3 in hook scripts."),
    ("harness", "FTS5 triggers on regular tables require PRAGMA trusted_schema=1 for writes",
     "Got 'unsafe use of virtual table' error on INSERT.",
     "Prepend PRAGMA trusted_schema=1; to every INSERT/UPDATE on the tracked table."),
    ("harness", "Project hooks live in .codex/hooks.json, not config.toml",
     "Hook registrations were placed in config.toml or another file and silently did not load.",
     "Keep project hooks in .codex/hooks.json. Use config.toml for non-hook Codex settings."),
    ("harness", "FTS5 MATCH treats bare `-` as NOT-operator, not hyphen",
     "'matrix-arch' in a MATCH query inverted the search.",
     "Replace hyphens with spaces in query construction before MATCH."),
    ("harness", "Heredoc hijacks stdin even when a pipe is also present",
     "`echo x | python3 - <<EOF` feeds heredoc to python, discarding the pipe.",
     "Use `python3 -c` with inline-quoted source when you need a pipe."),
    ("harness", "bm25() is an FTS5 aux function, not usable inside aggregates",
     "min(bm25(...)) errored at query time.",
     "Use ORDER BY bm25(...) LIMIT 1 instead of aggregating."),

    # ── Agent-team orchestration ──────────────────────────────────────────
    ("deploy-team", "Sequential default when agents share a thread",
     "Parallel mode without a Ralph loop delivers prompts once — agents can't see each other's posts.",
     "Default sequential; only parallel when the template has an explicit iteration loop."),
    ("deploy-team", "Detect AGENT_DONE in both streamed response AND output.md",
     "Some agents forget the sentinel in the stream but write it to output.md.",
     "Check both sources; one is a backstop for the other."),
]


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA trusted_schema=1")
    cur = conn.cursor()
    inserted, skipped = 0, 0
    for category, rule, mistake, correction in SEEDS:
        cur.execute(
            "SELECT id FROM learnings WHERE project=? AND category=? AND rule=? LIMIT 1",
            (PROJECT, category, rule),
        )
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute(
            "INSERT INTO learnings (project, category, rule, mistake, correction, source) "
            "VALUES (?,?,?,?,?,?)",
            (PROJECT, category, rule, mistake, correction, "seed"),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"seeded [{PROJECT}]: {inserted} inserted, {skipped} skipped")


if __name__ == "__main__":
    main()
