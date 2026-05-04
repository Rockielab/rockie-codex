#!/usr/bin/env python3
"""mode.py — manage operational overlays on the central taste corpus.

Subcommands:
    show              print active mode + brief overlay summary
    active            print active mode name only (machine-friendly)
    list              list available modes
    switch <name>     atomic flip of _active
    new <name>        copy a template (default --from default)
    edit <name>       open existing mode in $EDITOR
    diff <a> <b>      compare two modes
    seed              copy built-in templates into modes/ (install hook)

The active mode is named in <repo>/.rockie/taste/modes/_active.
A mode is a TOML file at <repo>/.rockie/taste/modes/<name>.toml.

Built-in templates live next to this script at ../templates/. The
seed subcommand copies templates into the user's modes/ on first run.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# tomllib is stdlib in Python 3.11+. For 3.10 we'd need a backport;
# rockie smoke-test pins recent Pythons so this is safe today.
try:
    import tomllib
except ModuleNotFoundError:
    print("error: requires Python 3.11+ for tomllib", file=sys.stderr)
    sys.exit(2)

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "templates"

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

# Mode-schema sections we know about. Anything else is a typo or a
# user extension; we surface unknowns as INFO, not errors.
KNOWN_SECTIONS = {"hardware", "reading", "methodology", "risk",
                  "output", "workflow", "dismissals", "deadline"}


def _repo_root() -> Path:
    """Walk up from cwd to find a .rockie or .codex directory."""
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".rockie").exists() or (cur / ".codex").exists():
            return cur
        cur = cur.parent
    # Fallback: cwd. CLI will create dirs as needed.
    return Path.cwd().resolve()


def _modes_dir(repo: Path) -> Path:
    return repo / ".rockie" / "taste" / "modes"


def _active_file(repo: Path) -> Path:
    return _modes_dir(repo) / "_active"


def _ensure_modes_dir(repo: Path) -> Path:
    d = _modes_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _list_modes(repo: Path) -> list[Path]:
    d = _modes_dir(repo)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.toml") if not p.name.startswith("_"))


def _read_active(repo: Path) -> str | None:
    f = _active_file(repo)
    if not f.exists():
        return None
    name = f.read_text().strip().splitlines()[0] if f.read_text().strip() else ""
    return name or None


def _write_active(repo: Path, name: str) -> None:
    """Atomic replace of _active. Write to sibling .tmp, fsync, rename."""
    d = _ensure_modes_dir(repo)
    target = d / "_active"
    fd, tmp = tempfile.mkstemp(prefix="_active.", suffix=".tmp", dir=d)
    try:
        os.write(fd, (name + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)


def _parse_mode(path: Path) -> tuple[dict, list[str]]:
    """Return (parsed, warnings). Warnings include unknown sections."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    warnings = []
    for k in data:
        if isinstance(data[k], dict) and k not in KNOWN_SECTIONS:
            warnings.append(f"unknown section [{k}] in {path.name} (typo?)")
    if "name" not in data:
        warnings.append(f"{path.name} missing required `name` field")
    return data, warnings


def _format_mode_summary(mode: dict) -> str:
    """Compact one-block summary of a parsed mode for SessionStart."""
    lines = [f"**mode**: `{mode.get('name', '?')}`"]
    desc = mode.get("description", "").strip()
    if desc:
        lines.append(f"_{desc}_")
    sections = []
    for sec in ("hardware", "risk", "output", "workflow", "deadline"):
        if sec in mode and mode[sec]:
            kvs = ", ".join(f"{k}={_fmt_val(v)}"
                            for k, v in mode[sec].items())
            sections.append(f"- **[{sec}]** {kvs}")
    lines.extend(sections)
    return "\n".join(lines)


def _fmt_val(v):
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def cmd_show(args):
    repo = _repo_root()
    name = _read_active(repo)
    if not name:
        print("no active mode set. Run `/mode list` then `/mode switch <name>`.")
        return 0
    path = _modes_dir(repo) / f"{name}.toml"
    if not path.exists():
        print(f"active mode '{name}' has no TOML file at {path}", file=sys.stderr)
        return 2
    mode, warnings = _parse_mode(path)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)
    print(_format_mode_summary(mode))
    return 0


def cmd_active(args):
    repo = _repo_root()
    name = _read_active(repo)
    print(name or "")
    return 0


def cmd_list(args):
    repo = _repo_root()
    modes = _list_modes(repo)
    active = _read_active(repo)
    if not modes:
        print(f"no modes found in {_modes_dir(repo)}.")
        print("Run `python3 .agents/skills/mode/runtime/mode.py seed` to "
              "copy built-in templates.")
        return 0
    for p in modes:
        try:
            mode, _ = _parse_mode(p)
        except Exception as exc:
            print(f"  {p.stem:20s}  (parse error: {exc})")
            continue
        marker = "*" if mode.get("name") == active else " "
        desc = mode.get("description", "").strip()
        print(f"{marker} {mode.get('name', p.stem):20s}  {desc}")
    return 0


def cmd_switch(args):
    repo = _repo_root()
    name = args.name
    if not NAME_RE.match(name):
        print(f"error: invalid mode name '{name}'. Must match {NAME_RE.pattern}",
              file=sys.stderr)
        return 2
    path = _modes_dir(repo) / f"{name}.toml"
    if not path.exists():
        print(f"error: mode '{name}' not found at {path}", file=sys.stderr)
        print("\navailable modes:", file=sys.stderr)
        cmd_list(args)
        return 2
    # Validate it parses before flipping _active.
    try:
        _parse_mode(path)
    except Exception as exc:
        print(f"error: mode '{name}' has invalid TOML: {exc}", file=sys.stderr)
        return 3
    _write_active(repo, name)
    print(f"active mode → {name}")
    print("(start a fresh session with /clear to load the new mode at SessionStart)")
    return 0


def cmd_new(args):
    repo = _repo_root()
    name = args.name
    if not NAME_RE.match(name):
        print(f"error: invalid mode name '{name}'. Must match {NAME_RE.pattern}",
              file=sys.stderr)
        return 2
    target = _modes_dir(repo) / f"{name}.toml"
    if target.exists():
        print(f"error: mode '{name}' already exists at {target}", file=sys.stderr)
        return 2
    src_template = args.template or "default"
    src = TEMPLATE_DIR / f"{src_template}.toml"
    if not src.exists():
        print(f"error: template '{src_template}' not found at {src}", file=sys.stderr)
        return 2
    _ensure_modes_dir(repo)
    shutil.copy2(src, target)
    # Patch the name field so it matches the new filename.
    text = target.read_text()
    text = re.sub(r'^name\s*=\s*"[^"]*"', f'name = "{name}"', text,
                  count=1, flags=re.MULTILINE)
    target.write_text(text)
    print(f"created {target}")
    print(f"edit it: $EDITOR {target}")
    print(f"or activate: /mode switch {name}")
    return 0


def cmd_edit(args):
    repo = _repo_root()
    target = _modes_dir(repo) / f"{args.name}.toml"
    if not target.exists():
        print(f"error: mode '{args.name}' not found at {target}", file=sys.stderr)
        return 2
    editor = os.environ.get("EDITOR", "vi")
    rc = subprocess.call([editor, str(target)])
    if rc != 0:
        print(f"editor exited with {rc}", file=sys.stderr)
        return rc
    # Validate after edit. Don't auto-revert; just warn.
    try:
        _parse_mode(target)
        print("✓ mode TOML parses cleanly")
    except Exception as exc:
        print(f"WARN: mode TOML now has parse error: {exc}", file=sys.stderr)
        print("Fix the file or revert before /mode switch.", file=sys.stderr)
        return 4
    return 0


def cmd_diff(args):
    repo = _repo_root()
    a = _modes_dir(repo) / f"{args.a}.toml"
    b = _modes_dir(repo) / f"{args.b}.toml"
    for p in (a, b):
        if not p.exists():
            print(f"error: {p.name} not found at {p}", file=sys.stderr)
            return 2
    rc = subprocess.call(["diff", "-u", str(a), str(b)])
    return 0 if rc <= 1 else rc


def cmd_seed(args):
    """Copy built-in templates into modes/ if absent. Idempotent."""
    repo = _repo_root()
    d = _ensure_modes_dir(repo)
    copied = 0
    skipped = 0
    for tmpl in TEMPLATE_DIR.glob("*.toml"):
        dst = d / tmpl.name
        if dst.exists():
            skipped += 1
            continue
        shutil.copy2(tmpl, dst)
        copied += 1
    print(f"seeded {copied} mode template(s) -> {d}; skipped {skipped} that "
          f"already existed.")
    if not _read_active(repo) and (d / "default.toml").exists():
        _write_active(repo, "default")
        print("set active mode → default")
    return 0


def main():
    p = argparse.ArgumentParser(prog="mode")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("active").set_defaults(fn=cmd_active)
    sub.add_parser("list").set_defaults(fn=cmd_list)

    sw = sub.add_parser("switch")
    sw.add_argument("name")
    sw.set_defaults(fn=cmd_switch)

    nw = sub.add_parser("new")
    nw.add_argument("name")
    nw.add_argument("--from", dest="template", default=None,
                    help="template to copy from (default: default)")
    nw.set_defaults(fn=cmd_new)

    ed = sub.add_parser("edit")
    ed.add_argument("name")
    ed.set_defaults(fn=cmd_edit)

    df = sub.add_parser("diff")
    df.add_argument("a")
    df.add_argument("b")
    df.set_defaults(fn=cmd_diff)

    sub.add_parser("seed").set_defaults(fn=cmd_seed)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
