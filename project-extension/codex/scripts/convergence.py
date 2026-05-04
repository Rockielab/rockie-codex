#!/usr/bin/env python3
"""Convergence-token detection for reflection loops.

Patterns worth exiting on (ordered by specificity — most specific first):

    AGENT_DONE   — used by /deploy-team, strongest signal
    CONVERGED    — generic convergence sentinel
    DONE         — weak; only accepts at end-of-turn alone on a line
    I am done    — natural-language sentinel (Sakana-style)

Use this instead of fixed-N reflection rounds. The orchestrator calls the
LLM, then runs `convergence.py check <transcript> --last-turn` — exit 0
means converged, exit 1 means keep looping, exit 2 means script error.

Also exposes Python API for in-process orchestrators:

    from convergence import check_text
    if check_text(assistant_output):
        break  # converged
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# Ordered by descending specificity. Regex anchors prevent false positives
# (e.g. "we're not done yet" shouldn't match DONE).
TOKEN_PATTERNS = [
    (re.compile(r"^\s*AGENT_DONE\s*$", re.MULTILINE), "AGENT_DONE"),
    (re.compile(r"^\s*CONVERGED\s*$", re.MULTILINE), "CONVERGED"),
    (re.compile(r"^\s*DONE\s*$", re.MULTILINE), "DONE"),
    (re.compile(r"^\s*I\s+am\s+done\.?\s*$", re.MULTILINE | re.IGNORECASE), "I am done"),
]


def check_text(text: str) -> str | None:
    """Return the matched token name, or None if not converged."""
    if not text:
        return None
    for pattern, name in TOKEN_PATTERNS:
        if pattern.search(text):
            return name
    return None


def read_last_assistant_turn(transcript_path: str) -> str:
    """Extract concatenated assistant text blocks from the most recent turn."""
    lines = pathlib.Path(transcript_path).read_text().splitlines()
    blocks: list[str] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        t = entry.get("type")
        if t == "user":
            content = entry.get("message", {}).get("content", [])
            if isinstance(content, str):
                break  # user prompt boundary
            if any(isinstance(b, dict) and b.get("type") == "text" for b in (content or [])):
                break
        if t == "assistant":
            content = entry.get("message", {}).get("content", [])
            for b in (content or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    blocks.insert(0, b.get("text", ""))
    return "\n\n".join(blocks)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", help="Transcript file path OR '-' for stdin text")
    p.add_argument("--last-turn", action="store_true",
                   help="Parse source as JSONL transcript; check last assistant turn")
    args = p.parse_args()

    if args.source == "-":
        text = sys.stdin.read()
    elif args.last_turn:
        text = read_last_assistant_turn(args.source)
    else:
        text = pathlib.Path(args.source).read_text()

    token = check_text(text)
    if token:
        print(f"converged: {token}")
        return 0
    print("not converged")
    return 1


if __name__ == "__main__":
    sys.exit(main())
