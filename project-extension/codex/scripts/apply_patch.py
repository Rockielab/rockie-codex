#!/usr/bin/env python3
"""SEARCH/REPLACE patch applier (Paper2Code format, reimplemented).

A cheaper alternative to full-file rewrites. Ports Paper2Code's
`codes/4_debugging.py` (Apache-2.0) — the idea, not the code.

Accepted format (agent emits this on stdout/stdin):

    path/to/file.py
    <<<<<<< SEARCH
    exact literal text to find
    =======
    replacement text
    >>>>>>> REPLACE

    other/file.txt
    <<<<<<< SEARCH
    ...

The applier:
  1. Parses all blocks.
  2. For each target file, writes a versioned backup (file.NNN.bak)
     so rollback is trivial.
  3. Applies each SEARCH/REPLACE as a literal string-match substitution.
     Failure (SEARCH text not found / matches >1) aborts the WHOLE patch
     — never partially applies.

Exit codes:
  0 = all blocks applied
  1 = at least one SEARCH miss (nothing applied)
  2 = malformed input

Usage:
    apply_patch.py --dry-run < patch.txt
    apply_patch.py           < patch.txt
    apply_patch.py path/to/file.py < patch.txt   # restrict to one file
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Iterable

BLOCK_RE = re.compile(
    r"(?P<path>[^\n<>=]+?)\s*\n"
    r"<{7}\s*SEARCH\s*\n"
    r"(?P<search>.*?)\n"
    r"={7}\s*\n"
    r"(?P<replace>.*?)\n"
    r">{7}\s*REPLACE\s*(?:\n|$)",
    re.DOTALL,
)


@dataclass
class Block:
    path: pathlib.Path
    search: str
    replace: str
    start: int
    end: int


def parse(text: str) -> list[Block]:
    out: list[Block] = []
    for m in BLOCK_RE.finditer(text):
        out.append(
            Block(
                path=pathlib.Path(m.group("path").strip()),
                search=m.group("search"),
                replace=m.group("replace"),
                start=m.start(),
                end=m.end(),
            )
        )
    return out


def next_backup_path(target: pathlib.Path) -> pathlib.Path:
    """file.py → file.py.001.bak (increments if exists)."""
    n = 1
    while True:
        p = target.with_name(f"{target.name}.{n:03d}.bak")
        if not p.exists():
            return p
        n += 1


def apply_blocks(blocks: Iterable[Block], *, dry_run: bool, restrict: pathlib.Path | None) -> int:
    # CONTAINMENT: reject absolute paths and any path that resolves outside
    # the current working directory. An LLM-produced patch can otherwise
    # coerce this script into writing ~/.ssh/authorized_keys, /etc/hosts,
    # etc. (security audit finding C-1, 2026-04-23).
    cwd = pathlib.Path.cwd().resolve()

    def contained(p: pathlib.Path) -> bool:
        if p.is_absolute():
            return False
        resolved = (cwd / p).resolve()
        try:
            resolved.relative_to(cwd)
            return True
        except ValueError:
            return False

    # First pass: validate all blocks before writing anything.
    validated: list[tuple[Block, str, str]] = []  # (block, current_contents, new_contents)
    seen: dict[pathlib.Path, str] = {}
    errors: list[str] = []
    for b in blocks:
        if restrict and b.path.resolve() != restrict.resolve():
            continue
        if not contained(b.path):
            errors.append(
                f"{b.path}: rejected — path escapes the current working directory "
                f"(absolute paths and '..' segments are never accepted)"
            )
            continue
        if not b.path.exists():
            errors.append(f"{b.path}: file not found")
            continue
        current = seen.get(b.path) or b.path.read_text()
        count = current.count(b.search)
        if count == 0:
            errors.append(f"{b.path}: SEARCH text not found")
            continue
        if count > 1:
            errors.append(f"{b.path}: SEARCH text matches {count}× (must be unique)")
            continue
        new_contents = current.replace(b.search, b.replace, 1)
        seen[b.path] = new_contents  # chain subsequent edits to the same file
        validated.append((b, current, new_contents))

    if errors:
        print("patch rejected:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    if not validated:
        print("patch rejected: no applicable blocks", file=sys.stderr)
        return 1

    # Second pass: write backups + apply.
    if dry_run:
        for b, _, _ in validated:
            print(f"[dry-run] would apply to {b.path} ({len(b.search)}→{len(b.replace)} chars)")
        return 0

    # Write backups (one per file, reflecting pre-patch state).
    for path in seen:
        original = path.read_text()
        bp = next_backup_path(path)
        bp.write_text(original)
        print(f"backup: {bp}")

    # Commit the in-memory final contents.
    for path, final_contents in seen.items():
        path.write_text(final_contents)
        print(f"wrote: {path}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("restrict", nargs="?", type=pathlib.Path,
                   help="If given, only apply blocks targeting this file")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    text = sys.stdin.read()
    blocks = parse(text)
    if not blocks:
        print("patch rejected: no blocks parsed (check format)", file=sys.stderr)
        return 2
    return apply_blocks(blocks, dry_run=args.dry_run, restrict=args.restrict)


if __name__ == "__main__":
    sys.exit(main())
