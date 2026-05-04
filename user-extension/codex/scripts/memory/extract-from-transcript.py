#!/usr/bin/env python3
"""Scan a Codex transcript for [LEARN] blocks and insert them.

Reads JSONL transcript (one event per line), pulls text content from
assistant messages, passes through the same [LEARN] block parser as
insert.py, and writes results to SQLite.

Used by both Stop hook (per-turn capture) and PreCompact/SessionEnd hooks
(sweep for anything the per-turn hook missed).

Usage:
  extract-from-transcript.py <transcript_path> [--session-id X] [--repo path]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402
from insert import BLOCK_RE, strip_code_fences  # noqa: E402


def read_assistant_text(transcript_path: Path) -> str:
    """Concatenate text content from all assistant messages in the transcript."""
    texts = []
    if not transcript_path.is_file():
        return ""
    with transcript_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = ev.get("role") or ev.get("message", {}).get("role")
            content = ev.get("content") or ev.get("message", {}).get("content")
            if role != "assistant" or not content:
                continue
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
    return "\n\n".join(texts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("transcript_path")
    p.add_argument("--session-id", default=None)
    p.add_argument("--repo", default=None)
    args = p.parse_args()

    # Safety gate: without a --repo, [LEARN] blocks from a non-git session
    # (e.g., scratch dir, /tmp) used to silently land as GLOBAL memories —
    # which made arbitrary text become cross-repo policy. Require a real
    # repo path; skip cleanly if absent.
    if not args.repo:
        print(
            "extract-from-transcript: no --repo; skipping capture to avoid silent global-tier writes.",
            file=sys.stderr,
        )
        return 0

    raw = read_assistant_text(Path(args.transcript_path))
    text = strip_code_fences(raw)
    if not text:
        return 0

    project = lib.project_from_path(args.repo)
    conn = lib.connect()

    inserted = dedup = 0
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
            f"📚 memory: sweep captured {inserted} new, {dedup} deduped [{tier}]",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
