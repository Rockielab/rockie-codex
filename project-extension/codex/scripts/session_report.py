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
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
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
        ("RUNPOD_API_KEY", "spot-GPU provisioning"),
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


def check_runpod_auth() -> Optional[tuple[str, list[dict]]]:
    """If RUNPOD_API_KEY is set, try auth + list pods. Returns (user_email, pods) or None."""
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not key:
        return None
    import json as _json
    q = '{"query": "query { myself { email pods { id name desiredStatus runtime { ports { ip isIpPublic privatePort publicPort } } } } }"}'
    try:
        req = urllib.request.Request(
            f"https://api.runpod.io/graphql?api_key={key}",
            data=q.encode(),
            headers={
                "content-type": "application/json",
                "user-agent": "rockie-session-report/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        me = (data.get("data") or {}).get("myself") or {}
        return (me.get("email", ""), me.get("pods") or [])
    except Exception:
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
        env_var = {
            "runpod": "RUNPOD_API_KEY",
            "vast": "VAST_API_KEY",
            "prime": "PRIME_API_KEY",
            "verda": "DATACRUNCH_CLIENT_ID",
        }.get(pref)
        if env_var and not os.environ.get(env_var, "").strip():
            out.append(f"mode prefers '{pref}' but {env_var} is unset")
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

    # ── RunPod pods ────────────────────────────────────────────────────
    pods_info = check_runpod_auth()
    if pods_info is None:
        if os.environ.get("RUNPOD_API_KEY"):
            out.append("## RunPod")
            out.append(f"- {WARN} API key set but auth query failed (network? key valid?)")
            out.append("")
    else:
        email, pods = pods_info
        out.append("## RunPod")
        out.append(f"- {OK} authed as `{email}`")
        running = [p for p in pods if p.get("desiredStatus") == "RUNNING"]
        stopped = [p for p in pods if p.get("desiredStatus") in ("EXITED", "STOPPED")]
        if running:
            for p in running:
                rt = p.get("runtime") or {}
                ports = rt.get("ports") or []
                ssh = next((x for x in ports if x.get("privatePort") == 22), None)
                endpoint = f"ssh root@{ssh['ip']} -p {ssh['publicPort']}" if ssh else "(no ssh port)"
                out.append(f"- {OK} **{p['id']}** ({p.get('name','')}) RUNNING — `{endpoint}`")
        if stopped:
            for p in stopped:
                # EXITED = spot preemption. The right response is NOT a
                # higher bid on the same provider — it's trying a
                # different provider at THAT provider's minimum, or
                # simply resuming at the same provider's current min
                # bid (via `runpod.py resume` with NO --bid, which now
                # defaults to minimumBidPrice).
                out.append(
                    f"- {WARN} **{p['id']}** ({p.get('name','')}) {p['desiredStatus']} "
                    f"— likely spot preemption. Resume at current min bid: "
                    f"`python3 .codex/scripts/runpod.py resume {p['id']} --yes`"
                )
                out.append(
                    f"  _(If preempted multiple times in a row, hop to a different provider "
                    f"rather than bumping the bid — see `scripts/gpu.py` when available.)_"
                )
        if not running and not stopped:
            out.append(f"- {MISS} no pods found")
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

    # ── Proposal ───────────────────────────────────────────────────────
    out.append("## What to do next")
    out.append("")
    out.append("Propose a plan based on the state above, then pause for the user:")
    out.append("")
    out.append("0. **If `taste/` corpus is absent, propose `/onboard` BEFORE anything else.** "
               "The corpus shapes how the agent makes every downstream decision; running "
               "experiments without it means the harness can't model what the researcher cares about.")
    out.append("1. If `RUNPOD_API_KEY` is missing, ask the user to populate `.env`.")
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
