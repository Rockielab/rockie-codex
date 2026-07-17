#!/usr/bin/env python3
"""session_report.py — onboarding diagnostic.

Emits a single Markdown block that describes the current state of the
project: what's set up, what's running, what's queued, where the last
scheduled session left off. Called by `hooks/session-report.sh` at
SessionStart so the agent sees this block in its FIRST context turn,
without the user needing to prompt for it.

The block deliberately ends with a **proposal** and a **one-word ask**
("say 'go' to accept, or redirect"). If you start a new session and
type nothing more complicated than "go" or "what next", the agent
should have everything it needs to proceed.

Output is always stdout (the SessionStart hook tees it). Exit 0 always;
missing pieces become WARN rows in the report, not failures.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parent.parent           # .codex/
REPO = ROOT.parent                                              # <project>/
DB = ROOT / "memory" / "workflow.db"
ENV = REPO / ".env"
STATE_MD = REPO / "STATE.md"
NOTES_MD = REPO / "SCHEDULED_NOTES.md"
LOG_MD = REPO / "EXPERIMENT_LOG.md"
CLAUDE_MD = REPO / "AGENTS.md"
TASTE_DIR = REPO / ".rockie" / "taste"
TASTE_INDEX = TASTE_DIR / "INDEX.md"
MODES_DIR = TASTE_DIR / "modes"
MODE_ACTIVE = MODES_DIR / "_active"
CATALOG_SENTINEL = ROOT / ".state" / "catalog-onramp-shown"
# Skills install to <project>/.agents/skills/ — a SIBLING of .codex/, not
# nested inside it (see install.sh: "project skills into <target>/.agents/
# skills/"). REPO, not ROOT, is the right anchor here.
SKILLS_DIR = REPO / ".agents" / "skills"
SKILLS_LIST_CAP = 40

OK = "✓"
WARN = "⚠"
MISS = "•"


def env_status() -> list[tuple[str, str, str]]:
    """Return rows describing each expected env var."""
    rows = []
    if not ENV.exists():
        rows.append((MISS, ".env file", "not found — copy .env.example and fill in keys"))
    else:
        rows.append((OK, ".env file", f"present at {ENV}"))
    # We don't read .env directly — we trust whatever was sourced. But we
    # tell the user which vars are/aren't set right now.
    for var, purpose in [
        ("GPU_API_KEY", "GPU compute provisioning"),
        ("NTFY_TOPIC", "push notifications (optional)"),
    ]:
        val = os.environ.get(var, "").strip()
        if val:
            rows.append((OK, var, f"set ({len(val)} chars)"))
        elif var == "NTFY_TOPIC":
            rows.append((MISS, var, f"unset — {purpose}; run without it if you like"))
        else:
            rows.append((WARN, var, f"NOT SET — {purpose} will be skipped"))
    return rows


def gpu_pods_status(conn: sqlite3.Connection | None) -> Optional[list[dict]]:
    """Read tracked GPU pods from the local reconciled gpu_pods table.

    The router (gpu.py reconcile, fired by hooks/budget-reconcile.sh and
    autopilot startup) keeps this table current against live compute
    state. Reading it here keeps SessionStart fast and offline — no
    provider API call, no supplier identity — while still surfacing what
    is running. Returns a list of pod dicts, or None if the table is
    absent/unreadable.
    """
    if conn is None:
        return None
    try:
        rows = conn.execute(
            "SELECT id, status, gpu_type, gpu_count, ssh_endpoint "
            "FROM gpu_pods "
            "WHERE status NOT IN ('TERMINATED', 'GONE') "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return None


def sqlite_ok() -> sqlite3.Connection | None:
    if not DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA trusted_schema=1")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def queue_status(conn: sqlite3.Connection, project: str) -> dict:
    try:
        by = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM experiment_queue WHERE project=? GROUP BY status",
                (project,),
            ).fetchall()
        )
        next_item = conn.execute(
            """
            SELECT id, priority, hypothesis, metric_name, predicted_delta,
                   estimated_minutes, suggested_stage
            FROM experiment_queue WHERE project=? AND status='pending'
            ORDER BY priority ASC, id ASC LIMIT 1
            """,
            (project,),
        ).fetchone()
        return {"counts": by, "next": dict(next_item) if next_item else None, "ok": True}
    except sqlite3.Error:
        return {"counts": {}, "next": None, "ok": False}


def journal_snapshot(conn: sqlite3.Connection, project: str) -> list[dict]:
    try:
        rows = conn.execute(
            """
            SELECT id, stage, status, is_buggy, failure_class, metric_name, metric_value, hypothesis
            FROM experiments WHERE project=? ORDER BY id DESC LIMIT 3
            """,
            (project,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def best_so_far(conn: sqlite3.Connection, project: str) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT id, metric_name, metric_value, lower_is_better, hypothesis FROM best_so_far WHERE project=?",
            (project,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def stage_state() -> Optional[str]:
    f = ROOT / ".state" / "current-stage"
    if f.exists():
        return f.read_text().strip()
    return None


def tail_file(path: pathlib.Path, lines: int = 10) -> Optional[str]:
    if not path.exists():
        return None
    content = path.read_text().splitlines()
    return "\n".join(content[-lines:])


def _load_active_mode() -> tuple[Optional[dict], list]:
    """Read modes/_active and return (parsed_mode, warnings).
    Returns (None, []) when no mode is set or files are missing.
    Warnings are advisory strings the report should surface.
    """
    if not MODE_ACTIVE.exists():
        return None, []
    name = (MODE_ACTIVE.read_text().strip().splitlines() or [""])[0]
    if not name:
        return None, []
    path = MODES_DIR / f"{name}.toml"
    if not path.exists():
        return None, [f"_active names '{name}' but {path.name} is missing"]
    try:
        import tomllib
        with path.open("rb") as f:
            mode = tomllib.load(f)
    except Exception as exc:  # noqa: BLE001 — surface any parse failure
        return None, [f"failed to parse {path.name}: {exc}"]
    return mode, _mode_conflicts(mode)


def _mode_conflicts(mode: dict) -> list:
    """Surface obvious mismatches between mode policy and live env."""
    out = []
    hw = mode.get("hardware") or {}
    pref = hw.get("preferred_provider")
    if pref:
        # A mode may pin a preferred adapter slug, but the credential is
        # always surfaced under one generic env var — the broker hides
        # which supplier it maps to.
        if not os.environ.get("GPU_API_KEY", "").strip():
            out.append(f"mode prefers '{pref}' but GPU_API_KEY is unset")
    if hw.get("spot_only") and os.environ.get("ROCKIE_GPU_MODE") == "none":
        out.append("mode requires spot GPUs but ROCKIE_GPU_MODE=none")
    return out


def _format_mode_block(mode: dict) -> str:
    """Compact mode summary for the SessionStart context."""
    lines = [f"**mode**: `{mode.get('name', '?')}`"]
    desc = (mode.get("description") or "").strip()
    if desc:
        lines.append(f"_{desc}_")
    for sec in ("hardware", "risk", "output", "workflow", "deadline"):
        block = mode.get(sec)
        if not block:
            continue
        kvs = ", ".join(f"{k}={_fmt_v(v)}" for k, v in block.items())
        lines.append(f"- **[{sec}]** {kvs}")
    return "\n".join(lines)


def _fmt_v(v):
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _parse_soft_topics(idx_md: str) -> list:
    """Extract the soft_topics list from INDEX.md frontmatter.
    Returns [] if absent or unparseable. Intentionally minimal — no yaml
    dep, just a regex over the frontmatter block.
    """
    import re
    m = re.match(r"---\n(.*?)\n---", idx_md, re.DOTALL)
    if not m:
        return []
    fm = m.group(1)
    block = re.search(r"^soft_topics:\s*\n((?:  -.*\n)*)", fm, re.MULTILINE)
    if not block:
        return []
    return [line.strip(" -").strip() for line in block.group(1).splitlines() if line.strip()]


def _parse_skill_md(skill_md: pathlib.Path) -> tuple[str, str]:
    """Extract (name, description) from a SKILL.md.

    Prefers YAML frontmatter's `name:`/`description:` fields (the
    contract every shipped skill here follows — see any
    `.agents/skills/*/SKILL.md`). Falls back to the directory name and
    the first non-empty prose line in the body when frontmatter is
    missing, unparseable, or lacks one of the two fields — a skill
    dropped in by hand without the exact contract should still show up
    in the inventory instead of vanishing silently.

    The frontmatter scan is deliberately lenient about the *closing*
    `---` fence: it reads `key: value` lines right after the opening
    fence for as long as they look like frontmatter, then treats
    whatever follows as body — whether or not a proper closing fence
    was ever written. A skill with a truncated/malformed frontmatter
    block still surfaces its `name`/`description` fields instead of
    leaking a raw YAML line as the "description".
    """
    try:
        text = skill_md.read_text()
    except OSError:
        return skill_md.parent.name, "(SKILL.md unreadable)"

    lines = text.splitlines()
    fm_lines: list[str] = []
    body_start = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and re.match(r"^[A-Za-z_][\w-]*:\s?", lines[i]):
            fm_lines.append(lines[i])
            i += 1
        if i < len(lines) and lines[i].strip() == "---":
            i += 1  # consume a proper closing fence when one is there
        body_start = i

    fm_text = "\n".join(fm_lines)
    body = "\n".join(lines[body_start:])

    name = None
    desc = None
    nm = re.search(r"^name:\s*(.+)\s*$", fm_text, re.MULTILINE)
    if nm:
        name = nm.group(1).strip().strip("\"'")
    dm = re.search(r"^description:\s*(.+)\s*$", fm_text, re.MULTILINE)
    if dm:
        desc = dm.group(1).strip().strip("\"'")

    if not name:
        name = skill_md.parent.name
    if not desc:
        for line in body.splitlines():
            cleaned = line.strip().lstrip("#").strip()
            if cleaned:
                desc = cleaned
                break
    if not desc:
        desc = "(no description found)"
    return name, desc


def _truncate_desc(text: str, limit: int = 110) -> str:
    """Collapse whitespace and clip to ~limit chars for a one-line summary.

    Descriptions here are written as dense single-sentence-or-more
    frontmatter — injecting all of them verbatim every session would
    blow the context budget the on-ramp block elsewhere in this file is
    careful to respect. Cuts at a sentence boundary when one falls
    inside the budget, otherwise hard-clips with an ellipsis.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed.rfind(". ", 0, limit)
    if cut > limit // 3:
        return collapsed[: cut + 1]
    return collapsed[: limit - 1].rstrip() + "…"


def installed_skills_block() -> Optional[str]:
    """Enumerate installed skills so a compacted session re-discovers them.

    This is the fix for the documented failure mode: a long session
    compacts its context, the agent forgets which skills are installed,
    and it stops browsing/using them unless project memory happens to
    mention one by name. SessionStart in this harness carries no
    `matcher`, so it fires on every source Codex emits — startup,
    resume, clear, AND compact (see hooks/session-report.sh) — which
    means re-rendering this block here re-surfaces the inventory after
    compaction for free, with no separate compact-specific hook needed.

    Handles, in order: no .agents/skills/ dir at all (silent skip — not
    every install has one), skill dirs without a SKILL.md (skipped, not
    fatal), malformed/missing frontmatter (falls back to dir name +
    first prose line via `_parse_skill_md`), and large counts (capped
    at SKILLS_LIST_CAP with a "+N more" line so the block can't grow
    unbounded as skills accumulate).
    """
    if not SKILLS_DIR.is_dir():
        return None
    try:
        skill_dirs = sorted(
            (p for p in SKILLS_DIR.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
    except OSError:
        return None

    entries: list[tuple[str, str]] = []
    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue  # skill dir without SKILL.md — skip silently
        name, desc = _parse_skill_md(skill_md)
        entries.append((name, _truncate_desc(desc)))

    if not entries:
        return None

    total = len(entries)
    shown = entries[:SKILLS_LIST_CAP]
    lines = [f"## Installed skills ({total})", ""]
    for name, desc in shown:
        lines.append(f"- **{name}** — {desc}")
    remaining = total - len(shown)
    if remaining > 0:
        lines.append(f"- _(+{remaining} more not shown — see `.agents/skills/`)_")
    lines.append("")
    lines.append(
        "_Browse the relevant SKILL.md before starting matching work; "
        "pull more with `rockie skill catalog`._"
    )
    return "\n".join(lines)


def catalog_onramp() -> Optional[str]:
    """Once-per-project pointer at the platform skill catalog.

    The catalog (~300 skills) is deliberately NOT in context — that's the
    whole reason it lives behind the CLI. But an agent that never learns
    the catalog exists never pulls from it, so the harness says so once,
    on the first session in a project, and then never again.

    Two deliberate constraints:

    * **Offline.** `shutil.which` only (~0.02ms). Never shell out to
      `rockie skill catalog` here — that's a ~1.7s network round-trip,
      and SessionStart stays fast and offline (same reason gpu_pods reads
      the local table instead of a provider API).
    * **Silent for non-customers.** No CLI on PATH → return None. We do
      not advertise a product to someone who hasn't installed it; the
      README and installer already cover that channel.

    Returns the block once, then writes a sentinel and returns None
    forever after. The sentinel lives in gitignored `.state/`, so a fresh
    clone re-shows it once to the next agent — which is correct.
    """
    if shutil.which("rockie") is None:
        return None
    if CATALOG_SENTINEL.exists():
        return None
    try:
        CATALOG_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_SENTINEL.write_text("shown\n")
    except OSError:
        # Can't write the sentinel → don't emit, rather than emit every
        # session. Nagging is worse than staying quiet.
        return None
    return (
        "## Skill catalog available (shown once per project)\n"
        "\n"
        "The `rockie` CLI is on PATH. It fronts ~300 platform skills "
        "(ml-training, ml-inference, biology, chemistry, physics, databases, "
        "coding, …) that are kept out of your context on purpose. Pull the "
        "ones this project needs:\n"
        "\n"
        "```bash\n"
        "rockie skill catalog --search <topic> --json   # browse\n"
        "rockie skill pull <catalog_id> --out .agents/skills/<catalog_id>\n"
        "```\n"
        "\n"
        "A pulled skill is usable immediately — same `name` + `description` "
        "frontmatter contract as any other skill in `.agents/skills/`. Pull "
        "by `catalog_id`, invoke by the pulled frontmatter `name` (`$<name>`); "
        "they differ for ~13% of entries. Before writing expert guidance on a "
        "named framework from scratch, search the catalog first. Full "
        "procedure + context-budget rules: `$find-skills`.\n"
    )


def project_name() -> str:
    env = os.environ.get("PROJECT")
    if env:
        return env
    return REPO.name


def render() -> str:
    proj = project_name()
    out: list[str] = []
    out.append(f"# rockie session report — {proj}")
    out.append("")
    out.append("_Auto-generated by SessionStart hook. Read this first, then act._")
    out.append("")

    # ── Researcher taste corpus ─────────────────────────────────────────
    # Inject INDEX.md inline if present; flag absence so the agent can
    # nudge the user toward /onboard. Keeps the auto-injected text
    # bounded (~300 tokens). Full files load on demand.
    no_taste = not TASTE_INDEX.exists()
    if not no_taste:
        try:
            idx = TASTE_INDEX.read_text()
            out.append("## Researcher (from `.rockie/taste/INDEX.md`)")
            out.append("")
            out.append(idx.strip())
            out.append("")
            # Surface SOFT topics as an explicit warning so they don't
            # get buried inside the embedded YAML frontmatter.
            soft = _parse_soft_topics(idx)
            if soft:
                out.append(f"- {WARN} taste corpus has SOFT topics: "
                           f"{', '.join(soft)}. Consider `/onboard --deep` "
                           f"or `/onboard --section <name>` to deepen.")
            out.append("_Full corpus available at `.rockie/taste/`. "
                       "Read SOUL.md / METHODOLOGY.md / DISMISSALS.md when relevant. "
                       "Treat files marked `soft: true` as hypotheses for "
                       "confirmation, not load-bearing constraints._")
            out.append("")
        except OSError:
            no_taste = True

    if no_taste:
        out.append("## Researcher")
        out.append(f"- {MISS} no `taste/` corpus found. Run `/onboard` to set one up "
                   "— 5–7 questions, ~5 minutes, voice optional.")
        out.append("")

    # ── Installed skills ────────────────────────────────────────────────
    # Re-surfaced every SessionStart (startup AND compact — see the
    # docstring on installed_skills_block()) so a long session doesn't
    # silently forget which skills are on disk once older turns age out
    # of context.
    skills_block = installed_skills_block()
    if skills_block:
        out.append(skills_block)
        out.append("")

    # ── Active mode ────────────────────────────────────────────────────
    # Modes are small TOML overlays on the central corpus. The active
    # one carries this session's operational policy (deadline, scope
    # lock, hardware prefs). Load it after the identity layer so the
    # agent sees identity → mode → operational state in that order.
    mode, mode_warnings = _load_active_mode()
    if mode is not None:
        out.append("## Active mode")
        out.append("")
        out.append(_format_mode_block(mode))
        for w in mode_warnings:
            out.append(f"- {WARN} {w}")
        out.append("")
    elif MODES_DIR.exists():
        out.append("## Active mode")
        out.append(f"- {MISS} modes/ exists but no `_active` set. "
                   "Run `python3 .agents/skills/mode/runtime/mode.py list` "
                   "to choose one.")
        out.append("")

    # ── Environment ─────────────────────────────────────────────────────
    out.append("## Environment")
    out.append("")
    for mark, name, detail in env_status():
        out.append(f"- {mark} **{name}** — {detail}")
    out.append("")

    # ── GPU compute pods ────────────────────────────────────────────────
    # Sourced from the local reconciled gpu_pods table (kept current by
    # `gpu.py reconcile`), not a provider API — no supplier identity, no
    # network call at SessionStart.
    pods = gpu_pods_status(sqlite_ok())
    if pods is not None and pods:
        out.append("## GPU compute")
        running = [p for p in pods if (p.get("status") or "").upper() == "RUNNING"]
        stopped = [p for p in pods if (p.get("status") or "").upper() in ("EXITED", "STOPPED", "PREEMPTED")]
        if running:
            for p in running:
                endpoint = p.get("ssh_endpoint") or "(no ssh endpoint recorded)"
                gpu = f"{p.get('gpu_type','?')}×{p.get('gpu_count','?')}"
                out.append(f"- {OK} **{p['id']}** ({gpu}) RUNNING — `{endpoint}`")
        if stopped:
            for p in stopped:
                # EXITED/PREEMPTED on a spot tier. The right response is
                # NOT a higher bid — resume at the current minimum via the
                # router, which picks a supplier behind the broker.
                gpu = f"{p.get('gpu_type','?')}×{p.get('gpu_count','?')}"
                out.append(
                    f"- {WARN} **{p['id']}** ({gpu}) {p.get('status','?')} "
                    f"— likely spot preemption. Resume at current min bid: "
                    f"`python3 .codex/scripts/gpu.py resume {p['id']} --yes`"
                )
                out.append(
                    f"  _(If preempted repeatedly, the router rotates the underlying "
                    f"supplier automatically — don't bump the bid.)_"
                )
        out.append("")

    # ── Queue / journal ────────────────────────────────────────────────
    conn = sqlite_ok()
    if conn is None:
        out.append("## Queue / Journal")
        out.append(f"- {WARN} workflow.db not found at {DB}")
        out.append("")
    else:
        qs = queue_status(conn, proj)
        out.append("## Experiment queue")
        if not qs.get("ok"):
            out.append(f"- {WARN} queue table not present — run `bash .codex/scripts/init_db.sh` to initialize schema")
        else:
            counts = qs["counts"]
            cc = "  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "(empty)"
            out.append(f"- status: {cc}")
        if qs.get("next"):
            n = qs["next"]
            pred = f"{n['predicted_delta']:+.3f}" if n["predicted_delta"] is not None else "—"
            out.append(
                f"- **next**: #{n['id']} (p={n['priority']}) — "
                f"{n['hypothesis']}  _(metric={n['metric_name']}, pred={pred}, ~{n['estimated_minutes']}m)_"
            )
        else:
            out.append("- no pending items. Run `/queue-refill` to brainstorm new experiments.")
        out.append("")

        out.append("## Best-so-far")
        bests = best_so_far(conn, proj)
        if bests:
            for b in bests:
                arrow = "↓" if b["lower_is_better"] else "↑"
                out.append(f"- #{b['id']} · **{b['metric_name']} {arrow} {b['metric_value']:g}** · {(b['hypothesis'] or '')[:70]}")
        else:
            out.append("- _(no closed non-buggy experiments yet)_")
        out.append("")

        out.append("## Last 3 experiments")
        recent = journal_snapshot(conn, proj)
        if recent:
            for r in recent:
                m = ""
                if r["metric_name"] and r["metric_value"] is not None:
                    m = f"  {r['metric_name']}={r['metric_value']:g}"
                bug = ""
                if r["is_buggy"] == 1:
                    bug = f" · BUG ({r['failure_class'] or 'unclassified'})"
                out.append(
                    f"- #{r['id']} [{r['stage']}] {r['status']}{m}{bug}  {(r['hypothesis'] or '')[:60]}"
                )
        else:
            out.append("- _(empty — `journal.py tree` shows nothing yet)_")
        out.append("")

    # ── Stage ──────────────────────────────────────────────────────────
    s = stage_state()
    out.append("## Stage")
    out.append(f"- current: `{s or '(unset)'}`")
    out.append("")

    # ── Scheduled notes + STATE.md teasers ─────────────────────────────
    notes = tail_file(NOTES_MD, 20)
    if notes:
        out.append("## Where the last scheduled run left off (`SCHEDULED_NOTES.md`)")
        out.append("```")
        out.append(notes)
        out.append("```")
        out.append("")

    state_tail = tail_file(STATE_MD, 8)
    if state_tail:
        out.append("## STATE.md tail")
        out.append("```")
        out.append(state_tail)
        out.append("```")
        out.append("")

    # ── Skill catalog on-ramp ──────────────────────────────────────────
    # Once per project, and only when the CLI is actually installed.
    # Placed last-but-one so it never buries the proposal below.
    onramp = catalog_onramp()
    if onramp:
        out.append(onramp)
        out.append("")

    # ── Proposal ───────────────────────────────────────────────────────
    out.append("## What to do next")
    out.append("")
    out.append("Propose a plan based on the state above, then pause for the user:")
    out.append("")
    out.append("0. **If `taste/` corpus is absent, propose `/onboard` BEFORE anything else.** "
               "The corpus shapes how the agent makes every downstream decision; running "
               "experiments without it means the harness can't model what the researcher cares about.")
    out.append("1. If `GPU_API_KEY` is missing, ask the user to populate `.env`.")
    out.append("2. If a pod is RUNNING, treat its SSH endpoint as the compute target.")
    out.append("3. If the queue has a pending top item, propose running it next.")
    out.append("4. If the queue is empty, propose `/queue-refill` before anything else.")
    out.append("5. State your proposed first action in ONE sentence, then: "
               "_say 'go' to accept, or redirect_.")
    out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    # Allow a --plain flag that drops the markdown headers (useful for
    # piping into /bin/sh pipelines or storing as JSON later).
    if "--help" in sys.argv:
        print(__doc__)
        return 0
    print(render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
