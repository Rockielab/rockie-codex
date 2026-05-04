#!/usr/bin/env python3
"""One-shot migration: existing JSONL corrections + team/*.md → SQLite.

Walks the repos registered in ~/.codex/projects/<project>/memory/ and the
repo-local .codex/memory/corrections/<dev>/ path, pulls any corrections
JSONL entries into the SQLite memory store, and renames the source files
with a `.migrated` suffix so it never re-runs.

Idempotent: running twice does nothing on the second run (source files are
already renamed).

Usage:
  migrate-jsonl.py [--repo <absolute-repo-path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402


def migrate_corrections_jsonl(
    conn, jsonl_path: Path, repo_path: str | None, dry_run: bool
) -> int:
    """Ingest one corrections.jsonl file. Returns count migrated."""
    if not jsonl_path.is_file():
        return 0
    count = 0
    project = lib.project_from_path(repo_path) if repo_path else None
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rule = (rec.get("rule") or "").strip()
            if not rule:
                continue
            if dry_run:
                count += 1
                continue
            _, action = lib.insert_memory(
                conn,
                category=rec.get("category", "uncategorized"),
                rule=rule,
                mistake=rec.get("mistake"),
                correction=rec.get("correction"),
                project=project,
                origin_session=rec.get("id"),
                origin_repo_path=repo_path,
            )
            if action in ("inserted", "dedup"):
                count += 1
    if not dry_run:
        jsonl_path.rename(jsonl_path.with_suffix(jsonl_path.suffix + ".migrated"))
    return count


def migrate_team_md(conn, team_dir: Path, dry_run: bool, *, project: str | None) -> int:
    """Ingest team/*.md files as global-tier memories.

    Team MDs typically look like:
        **Rule:** <one-liner>
        **Why:** <reason>
        **Pattern:** ...

    We extract the Rule line as the `rule` and keep the rest as `correction`
    so surface.py can render cleanly without double-bolding.
    """
    if not team_dir.is_dir():
        return 0
    count = 0
    for md in sorted(team_dir.glob("*.md")):
        slug = md.stem
        if slug == "MEMORY-TEAM":
            continue
        body = md.read_text().strip()
        if not body:
            continue

        # Strip YAML frontmatter if present
        if body.startswith("---"):
            parts = body.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()

        lines = body.split("\n")
        rule_text = None
        rest_lines = []
        for ln in lines:
            stripped = ln.strip()
            if rule_text is None:
                # Look for `**Rule:**` or `Rule:` or a bare first non-empty line
                m = re.match(r"^\*\*Rule:\*\*\s*(.+)$", stripped)
                if m:
                    rule_text = m.group(1).strip()
                    continue
                m = re.match(r"^Rule:\s*(.+)$", stripped)
                if m:
                    rule_text = m.group(1).strip()
                    continue
                # Skip blank lines / headings before the rule
                if not stripped or stripped.startswith("#"):
                    continue
                # Fallback: first prose line
                rule_text = stripped
                continue
            rest_lines.append(ln)

        rule = rule_text or slug.replace("-", " ")
        rest = "\n".join(rest_lines).strip()

        if dry_run:
            count += 1
            continue

        _, action = lib.insert_memory(
            conn,
            category=slug,
            rule=rule,
            mistake=None,
            correction=rest or None,
            project=project,  # None only if --promote-team was set
            origin_repo_path=None,
        )
        if action in ("inserted", "dedup"):
            count += 1
        md.rename(md.with_suffix(".md.migrated"))
    return count


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo",
        default=None,
        help="Absolute path of the repo to migrate from (required)",
    )
    p.add_argument(
        "--promote-team",
        action="store_true",
        help="If set, .codex/memory/team/*.md files migrate to GLOBAL tier. "
        "Default: migrate as repo-tier (safer — prevents untrusted checkouts from "
        "dumping cross-repo rules).",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.repo:
        print("migrate-jsonl: --repo is required (no cwd fallback)", file=sys.stderr)
        return 2

    conn = lib.connect()

    repo_path = args.repo
    repo = Path(repo_path)
    corrections_dir = repo / ".codex" / "memory" / "corrections"
    team_dir = repo / ".codex" / "memory" / "team"

    # Team MDs default to repo-tier. --promote-team is required to publish
    # them to global. This prevents accidental cross-repo policy dumps from
    # an untrusted checkout.
    team_project = None if args.promote_team else lib.project_from_path(repo_path)

    total = 0
    if corrections_dir.is_dir():
        for dev_dir in sorted(corrections_dir.iterdir()):
            if not dev_dir.is_dir():
                continue
            jsonl = dev_dir / "corrections.jsonl"
            n = migrate_corrections_jsonl(conn, jsonl, repo_path, args.dry_run)
            if n:
                total += n
                print(f"  {jsonl.relative_to(repo)}: {n}")
    n_team = migrate_team_md(conn, team_dir, args.dry_run, project=team_project)
    if n_team:
        total += n_team
        tier_tag = "GLOBAL" if team_project is None else f"repo={team_project}"
        print(
            f"  {team_dir.relative_to(repo)}: {n_team} team memories → tier={tier_tag}"
        )

    if total == 0:
        print(f"migrate-jsonl: nothing to migrate from {repo}", file=sys.stderr)
    else:
        suffix = " (dry-run)" if args.dry_run else ""
        print(f"✓ migrate-jsonl: {total} memories migrated{suffix}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
