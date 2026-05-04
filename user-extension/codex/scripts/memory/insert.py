#!/usr/bin/env python3
"""Insert a correction into the memory DB.

Reads a [LEARN] block (or multiple) from stdin and writes to SQLite with
automatic dedup. Replaces the old JSONL append path in learn-capture.sh.

Usage:
  cat transcript.jsonl | insert.py --session-id <id> --repo <repo-path>

  Or inline:
  insert.py --session-id <id> --repo <path> <<'EOF'
  [LEARN] ffprobe-usage: always use lib/ffprobe
  Mistake: called subprocess.run(['ffprobe', ...])
  Correction: use lib.ffprobe.probe()
  EOF
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow sibling import when run as a script
sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402


BLOCK_RE = re.compile(
    r"\[LEARN\]\s*([^:\n]+?)\s*:\s*(.+?)\n"
    r"\s*Mistake\s*:\s*(.+?)\n"
    r"\s*Correction\s*:\s*(.+?)(?=\n\s*\[LEARN\]|\n\s*\n|\Z)",
    re.DOTALL,
)


def strip_code_fences(text: str) -> str:
    """Drop fenced code-block content so example [LEARN] blocks don't capture.

    State machine mirrors parse-learn-blocks.py so behavior stays consistent.
    """
    out = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session-id", default=None)
    p.add_argument("--repo", default=None, help="Absolute path of repo where captured")
    p.add_argument(
        "--tier",
        choices=["repo", "global"],
        default="repo",
        help="Default 'repo': requires --repo and tags the memory per-repo. 'global' is explicit opt-in for cross-repo rules (skip per-correction asks). Without --repo AND without --tier=global, capture is skipped — NEVER default to global silently.",
    )
    args = p.parse_args()

    text = strip_code_fences(sys.stdin.read())

    # Safety gate: the old code would silently land NULL-project (global) if
    # no --repo was provided. That let `[LEARN]` blocks from scratch dirs or
    # non-git cwds become cross-repo policy. Require explicit intent now.
    if args.tier == "repo" and not args.repo:
        print(
            "insert: no --repo provided and --tier=repo; skipping capture. "
            "Pass --repo <abs-path> (normal case) or --tier=global (explicit cross-repo rule).",
            file=sys.stderr,
        )
        return 0
    project = lib.project_from_path(args.repo) if args.tier == "repo" else None

    conn = lib.connect()
    inserted = 0
    dedup = 0
    for m in BLOCK_RE.finditer(text):
        category = m.group(1)
        rule = m.group(2)
        mistake = m.group(3).strip()
        correction = m.group(4).strip()
        _, action = lib.insert_memory(
            conn,
            category=category,
            rule=rule,
            mistake=mistake,
            correction=correction,
            project=project,
            origin_session=args.session_id,
            origin_repo_path=args.repo,
        )
        if action == "inserted":
            inserted += 1
        elif action == "dedup":
            dedup += 1

    if inserted or dedup:
        tier = f"project={project}" if project else "project=GLOBAL"
        print(
            f"📚 memory: {inserted} new, {dedup} deduped [{tier}]",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
