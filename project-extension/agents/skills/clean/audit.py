#!/usr/bin/env python3
"""
audit.py — pre-commit anti-slop audit for this repo.

Three tracks, changed-files-only:
  - Static lint (ruff for .py, shellcheck for .sh — skip if not installed)
  - Doc audit (.md): new-file blocker, broken internal links, length,
    TODO/FIXME markers, stale time-sensitive phrases
  - AI slop prompt: returned in the report for the agent to action

On zero-blocker pass, hands off to <workspace>/scripts/clean-finalize.sh,
which writes the sentinel <workspace>/.state/clean-ok-<hash> AND emits
the upstream-contribute nudge to stderr. The pre-commit-gate hook reads
this sentinel. <workspace> (the .codex/ tree) is self-located from this
file's path (see resolve_workspace_dir()); no environment variable is
required or consulted.

Exit codes:
  0  zero blockers (sentinel written)
  1  blockers present (no sentinel)
  2  script error
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def resolve_workspace_dir():
    """Resolve the `.codex` workspace root (hooks/scripts/.state) that
    this audit hands off to.

    Every bash hook/script in this harness self-locates
    (`ROOT="$(cd "$(dirname "$0")/.." && pwd)"`) from its own file path —
    never from an environment variable. audit.py was the one holdout
    that *required* OPENCLAW_WORKSPACE_DIR: nothing in this repo (or an
    installed project) ever sets it, so a plain shell made $clean
    impossible to unblock even by following pre-commit-gate.sh's own
    remediation command verbatim (ported from Rockielab/rockie-claude#24
    bug 1).

    This repo splits the install in two: skills (including this file)
    land in <project>/.agents/skills/, while hooks/scripts/.state land
    in the SIBLING <project>/.codex/ — unlike rockie-claude, where
    everything installs under one .claude/ tree. So self-location here
    is "go up to the project root, then into .codex", not "go up to my
    own root": audit.py lives at <project>/.agents/skills/clean/audit.py,
    four path segments below <project>.

    An env-var override was deliberately NOT ported back in either: a
    stale value (e.g. left set from a previous session, pointing at a
    sibling checkout) would silently redirect the sentinel to the WRONG
    .codex/.state — this bites hardest in a `git worktree add` checkout,
    where .state/ is gitignored and so never copied between worktrees
    (same rockie-claude#24 bug 1, worktree manifestation). No other
    script in this harness supports such an override and nothing sets
    the var, so it would be pure risk with no upside.
    """
    return str(pathlib.Path(__file__).resolve().parents[3] / ".codex")


def changed_files(scope, since=None):
    if scope == "staged":
        out = run(["git", "diff", "--cached", "--name-only"]).stdout
    elif scope == "dirty":
        mod = run(["git", "diff", "--name-only"]).stdout
        unt = run(["git", "ls-files", "--others", "--exclude-standard"]).stdout
        out = mod + unt
    elif scope == "since":
        # Audit files changed since a given ref (commit, tag, branch,
        # or relative like HEAD~15). Useful for post-hoc review of
        # recent work when nothing is dirty.
        ref = since or "HEAD~1"
        out = run(["git", "diff", f"{ref}..HEAD", "--name-only"]).stdout
    else:
        return []
    files = [f.strip() for f in out.splitlines() if f.strip()]
    return [f for f in files if os.path.exists(f)]


def audit_python(f):
    issues = []
    if shutil.which("ruff"):
        r = run(["ruff", "check", "--select", "F401,F811,F841,E711,E712", f])
        for line in r.stdout.strip().splitlines():
            # Skip ruff's summary/status lines — only real findings matter.
            if not line:
                continue
            if line.startswith(("Found", "All checks passed")):
                continue
            if "warning:" in line.lower() or "error:" in line.lower() or f in line:
                issues.append((f, "warning", line.strip()))
    else:
        issues.append((f, "info", "ruff not installed — static lint skipped"))

    try:
        source = pathlib.Path(f).read_text()
        # print() detection is meant to catch debug artifacts, not CLI UI.
        # Skip files that look like CLIs (import argparse) or test files.
        is_cli = ("import argparse" in source) or ("argparse.ArgumentParser" in source)
        is_test = "test" in f.lower()
        if not is_cli and not is_test:
            for i, line in enumerate(source.splitlines(), 1):
                if re.match(r"\s*print\s*\(", line):
                    issues.append((f, "warning", f"L{i}: stray print() — debug artifact?"))
    except Exception:
        pass
    return issues


def audit_shell(f):
    issues = []
    if shutil.which("shellcheck"):
        r = run(["shellcheck", "-f", "gcc", "-S", "warning", f])
        for line in r.stdout.strip().splitlines():
            issues.append((f, "warning", line.strip()))
    else:
        issues.append((f, "info", "shellcheck not installed — static lint skipped"))
    return issues


def audit_markdown(f, is_new, repo_root):
    issues = []
    # Block creation of new .md files — user's rule for this repo.
    # Exempt: harness infrastructure (.codex/** legacy or .openclaw/**)
    # where .md files are skill/agent definitions required to exist, AND
    # the repo-root AGENTS.md itself. install.sh's own bootstrap
    # instructions tell every new user to `cp agents-md/AGENTS.md.template
    # AGENTS.md` as their first action after installing — $clean blocking
    # that made the harness reject the very first commit it told the user
    # to make (ported from Rockielab/rockie-claude#24 bug 2). AGENTS.md is
    # a singular, harness-mandated config file at a fixed path, not the
    # arbitrary doc proliferation this rule targets — unlike a new
    # NOTES.md/REPORT.md, there is only ever one. Other canonical root
    # docs are out of scope for this fix; only the reported file is
    # exempted.
    if is_new and f != "AGENTS.md" and not (f.startswith(".codex/") or f.startswith(".openclaw/")):
        issues.append((
            f, "blocker",
            "NEW .md file. Repo convention: consolidate into existing docs. "
            "If this is genuinely a novel topic (paper draft, design doc the user requested), "
            "override with CLEAN_BYPASS=1 at commit time."
        ))

    try:
        content = pathlib.Path(f).read_text()
    except Exception as e:
        issues.append((f, "info", f"read failed: {e}"))
        return issues

    base = pathlib.Path(f).parent

    # Broken internal links
    for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", content):
        link = m.group(2).strip().split()[0]  # strip ` "title"`
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_only = link.split("#")[0].split("?")[0]
        if not path_only:
            continue
        target = (base / path_only).resolve()
        if not target.exists():
            issues.append((f, "warning", f"broken link: [{m.group(1)}]({link})"))

    # TODO/FIXME/XXX
    for i, line in enumerate(content.splitlines(), 1):
        if re.search(r"\b(TODO|FIXME|XXX)\b", line):
            issues.append((f, "info", f"L{i}: marker — {line.strip()[:80]}"))

    # Length
    n = len(content.splitlines())
    if n > 500:
        issues.append((f, "warning", f"length {n} lines — consider consolidation"))

    # Stale markers — specific phrases that usually go out of date
    stale = re.findall(
        r"\b(currently running|in progress|as of \d{4}-\d{2}-\d{2}|this week|last week)\b",
        content, flags=re.IGNORECASE,
    )
    if stale:
        issues.append((f, "info", f"time-sensitive phrases present ({len(stale)}); verify currency"))

    return issues


def compute_hash():
    ws = resolve_workspace_dir()
    r = run(["bash", f"{ws}/scripts/compute_clean_hash.sh"])
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["staged", "dirty", "since"], default="staged")
    ap.add_argument("--since", help="Ref (commit/branch/HEAD~N) for --scope since")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    repo = run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
    if not repo:
        print("not a git repo", file=sys.stderr)
        sys.exit(2)
    os.chdir(repo)

    files = changed_files(args.scope, since=args.since)
    scope_note = args.scope if args.scope != "since" else f"since {args.since or 'HEAD~1'}"
    if args.scope == "staged" and not files:
        files = changed_files("dirty")
        scope_note = "dirty (no staged)"

    tracked = set(run(["git", "ls-tree", "--name-only", "-r", "HEAD"]).stdout.splitlines())

    issues = []
    for f in files:
        ext = pathlib.Path(f).suffix.lower()
        if ext == ".py":
            issues += audit_python(f)
        elif ext in (".sh", ".bash"):
            issues += audit_shell(f)
        elif ext == ".md":
            issues += audit_markdown(f, f not in tracked, repo)

    blockers = [i for i in issues if i[1] == "blocker"]
    warnings = [i for i in issues if i[1] == "warning"]
    info = [i for i in issues if i[1] == "info"]

    if args.json:
        print(json.dumps({
            "scope": scope_note,
            "files_audited": len(files),
            "blockers": [{"file": a, "msg": c} for a, _, c in blockers],
            "warnings": [{"file": a, "msg": c} for a, _, c in warnings],
            "info": [{"file": a, "msg": c} for a, _, c in info],
        }, indent=2))
    else:
        print(f"--- /clean audit ({scope_note}, {len(files)} files) ---")
        for label, group in (("BLOCKERS", blockers), ("WARNINGS", warnings), ("INFO", info)):
            if not group:
                continue
            print(f"\n{label} ({len(group)}):")
            for f, _, msg in group:
                print(f"  [{f}] {msg}")
        print()
        print("=== AI slop audit prompt (agent should address) ===")
        print("Review the diffs for the files above for:")
        print("  - debug artifacts (print/console.log/fmt.Println left in non-test code)")
        print("  - single-use helper functions (inline them)")
        print("  - restating comments (// CreateX above func CreateX)")
        print("  - catch-rethrow without added context")
        print("  - over-abstraction serving hypothetical needs")
        print("  - bloated docstrings that repeat the function signature")

    if not blockers:
        h = compute_hash()
        if h and h != "no-changes":
            # Delegate sentinel write + upstream-contribute nudge to
            # clean-finalize.sh so the nudge is deterministic (not
            # prose-only in SKILL.md) and the sentinel format stays in
            # one place shared with pre-commit-gate.sh.
            ws = resolve_workspace_dir()
            r = subprocess.run(
                ["bash", f"{ws}/scripts/clean-finalize.sh", h],
                text=True,
            )
            if r.returncode != 0:
                print(f"\n✗ clean-finalize.sh failed (exit {r.returncode})")
                sys.exit(2)
            print(f"\n✓ sentinel written: clean-ok-{h}")
        else:
            print("\n(nothing staged — no sentinel needed)")
        sys.exit(0)
    else:
        print(f"\n✗ {len(blockers)} blocker(s) — fix and rerun")
        sys.exit(1)


if __name__ == "__main__":
    main()
