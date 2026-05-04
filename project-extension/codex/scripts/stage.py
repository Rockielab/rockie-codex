#!/usr/bin/env python3
"""Stage-gated AGENTS.md — set the current research stage.

Ported pattern: Sakana v2's _curate_task_desc (reimplemented, not copied;
their code is restrictively licensed). The insight is that different
phases of a research project want different context. Stage 1 agents
don't need to see the full creative plan; stage 4 (ablation) agents
should NOT see "propose new variants" prompts.

Stages are rockie-conventional:
    draft          — first attempt, anything goes
    baseline-tune  — change hyperparams, not architecture
    creative       — novel architectural variants, multi-day runs OK
    ablation       — strip-out studies on the best creative node

Usage:
    stage.py get
    stage.py set <name>
    stage.py list

AGENTS.md can include `## Stage: <name>` sections. The stage-inject.sh
UserPromptSubmit hook reads the current stage and emits the matching
section's contents via stderr on each prompt.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

# Canonical set of stages. journal.py imports this; do not fork the list.
# "debug" and "improve" are sub-modes the search-policy uses inside the
# journal tree — they aren't project-level stages the user can set, so they
# don't appear here even though journal.py's node.stage column accepts them.
VALID_STAGES = ["draft", "baseline-tune", "creative", "ablation"]
STATE_FILE = pathlib.Path(__file__).resolve().parent.parent / ".state" / "current-stage"


def cmd_get(_args) -> int:
    if STATE_FILE.exists():
        print(STATE_FILE.read_text().strip())
    else:
        print("(unset)")
    return 0


def cmd_set(args) -> int:
    if args.name not in VALID_STAGES:
        print(f"invalid stage '{args.name}'. valid: {', '.join(VALID_STAGES)}",
              file=sys.stderr)
        return 2
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(args.name + "\n")
    print(f"[stage] set to '{args.name}'")
    return 0


def cmd_list(_args) -> int:
    print("valid stages:")
    for s in VALID_STAGES:
        print(f"  - {s}")
    current = STATE_FILE.read_text().strip() if STATE_FILE.exists() else None
    print(f"\ncurrent: {current or '(unset)'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("get").set_defaults(func=cmd_get)
    sp = sub.add_parser("set"); sp.add_argument("name"); sp.set_defaults(func=cmd_set)
    sub.add_parser("list").set_defaults(func=cmd_list)

    args = p.parse_args()
    if not args.cmd:
        return cmd_get(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
