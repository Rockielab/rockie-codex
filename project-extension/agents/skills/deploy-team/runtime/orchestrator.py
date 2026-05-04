#!/usr/bin/env python3
"""
orchestrator.py — /deploy-team runtime.

Given a template or config JSON + a topic + optional context files, spawns
N `codex` CLI subprocesses in parallel (one per agent), maintains a
shared thread.md, collects each agent's output.md, and emits a combined
REPORT.md.

Agents terminate on the AGENT_DONE sentinel or on max_total_minutes timeout.

Design choices:
  - Python (not Node) to match existing .codex/scripts/ conventions
  - Parallel by default (template controls sequential if desired)
  - No worktrees — agents produce markdown artifacts, not code commits
  - No live dashboard — final REPORT.md is the output
  - Shared thread.md is the coordination mechanism; agents can read it
    and append at will between iterations
"""

import argparse
import datetime
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
RUNS_DIR = REPO_ROOT / ".team-runs"

AGENT_DONE = "AGENT_DONE"

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


@dataclass
class AgentCfg:
    name: str
    motivation: str
    model: str
    prompt_template: str


@dataclass
class TeamCfg:
    name: str
    purpose: str
    parallel: bool
    max_total_minutes: int
    agents: list[AgentCfg]


@dataclass
class AgentRun:
    cfg: AgentCfg
    prompt: str
    output_path: pathlib.Path
    events_path: pathlib.Path
    stdout_path: pathlib.Path
    started_at: float = 0.0
    ended_at: float = 0.0
    returncode: int = -1
    done_sentinel_seen: bool = False
    error: Optional[str] = None


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config(template: Optional[str], config_path: Optional[str]) -> tuple[TeamCfg, pathlib.Path]:
    if template:
        path = TEMPLATES_DIR / f"{template}.json"
        if not path.exists():
            available = [p.stem for p in TEMPLATES_DIR.glob("*.json")]
            sys.exit(f"template '{template}' not found. available: {available}")
    elif config_path:
        path = pathlib.Path(config_path)
    else:
        sys.exit("must pass --template or --config")

    raw = json.loads(path.read_text())
    if not SAFE_NAME_RE.match(raw.get("name", "")):
        sys.exit(f"invalid team name: {raw.get('name')!r}")

    agents: list[AgentCfg] = []
    for a in raw.get("agents", []):
        if not SAFE_NAME_RE.match(a.get("name", "")):
            sys.exit(f"invalid agent name: {a.get('name')!r}")
        agents.append(AgentCfg(
            name=a["name"],
            motivation=a.get("motivation", ""),
            model=a.get("model", "sonnet"),
            prompt_template=a["prompt"],
        ))
    if not agents:
        sys.exit("team has no agents")

    return TeamCfg(
        name=raw["name"],
        purpose=raw.get("purpose", ""),
        # Default sequential — parallel mode breaks thread.md coordination
        # because agents receive their prompt once (no Ralph loop exists).
        parallel=raw.get("parallel", False),
        max_total_minutes=raw.get("max_total_minutes", 15),
        agents=agents,
    ), path


def generate_run_id(team_name: str) -> str:
    now = datetime.datetime.now()
    date = now.strftime("%Y%m%d")
    t = now.strftime("%H%M%S")
    suffix = f"{random.randint(0, 0xFFFF):04x}"
    slug = re.sub(r"[^a-z0-9]+", "-", team_name.lower()).strip("-")
    return f"{date}-{t}-{slug}-{suffix}"


def stage_context(run_dir: pathlib.Path, paths: list[str]) -> list[str]:
    """Copy (not symlink — codex CLI resolves symlinks oddly) context files
    into run_dir/context/. Returns the list of relative paths staged."""
    ctx_dir = run_dir / "context"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    staged: list[str] = []
    repo_abs = REPO_ROOT.resolve()
    for p in paths:
        src = (REPO_ROOT / p).resolve()
        # Reject context paths that escape the repo root. Defensive; the
        # user normally passes repo-relative paths, but a malicious or
        # careless `../../../etc/passwd` would otherwise leak arbitrary
        # files into the run dir (and into agent context).
        try:
            src.relative_to(repo_abs)
        except ValueError:
            log(f"WARN: rejected context path outside repo: {p}")
            continue
        if not src.exists():
            log(f"WARN: context file not found: {p}")
            continue
        dst = ctx_dir / src.name
        if src.is_file():
            shutil.copy2(src, dst)
            staged.append(dst.name)
        elif src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            staged.append(dst.name + "/")
    return staged


def build_prompt(template: str, topic: str, staged_ctx: list[str], run_dir: pathlib.Path, agent_name: str) -> str:
    ctx_lines = "\n".join(f"- ./context/{c}" for c in staged_ctx) if staged_ctx else "(none)"
    return (
        template
        .replace("{{TOPIC}}", topic)
        .replace("{{CONTEXT_FILES}}", ctx_lines)
        .replace("{{RUN_DIR}}", str(run_dir))
        .replace("{{AGENT_NAME}}", agent_name)
    )


def init_run(run_dir: pathlib.Path, team: TeamCfg, topic: str, staged_ctx: list[str], template_path: Optional[pathlib.Path]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "agents").mkdir(exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps({
        "team": team.name,
        "purpose": team.purpose,
        "topic": topic,
        "staged_context": staged_ctx,
        "started_at": datetime.datetime.now().isoformat(),
    }, indent=2))
    thread = run_dir / "thread.md"
    if not thread.exists():
        thread.write_text(f"# Team thread: {team.name}\n\nTopic: {topic}\n\n---\n")
    # Reproducibility: snapshot the exact orchestrator + template used for this run
    snap = run_dir / "snapshot"
    snap.mkdir(exist_ok=True)
    shutil.copy2(pathlib.Path(__file__), snap / "orchestrator.py")
    if template_path and template_path.exists():
        shutil.copy2(template_path, snap / template_path.name)


def spawn_agent(run: AgentRun, agent_dir: pathlib.Path, run_dir: pathlib.Path, max_seconds: int) -> None:
    """Run `codex -p <prompt>` with stream-json output in a subprocess.
    Captures stdout to stdout_path, parses for AGENT_DONE, writes events.jsonl."""
    prompt_file = agent_dir / "prompt.txt"
    prompt_file.write_text(run.prompt)
    # bypassPermissions allows WebSearch, WebFetch, Bash, Edit, Write — all
    # tools agents might need. acceptEdits only covered the Edit tool and
    # blocked research agents from doing their core task.
    cmd = [
        "codex", "-p", run.prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--model", run.cfg.model,
        "--permission-mode", "bypassPermissions",
        "--add-dir", str(run_dir),
    ]
    run.started_at = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=agent_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        run.error = "codex CLI not found on PATH"
        run.returncode = 127
        return

    assert proc.stdout is not None

    # Watchdog: kills the process after max_seconds even if stdout is silent.
    # Inline `if time.time() > deadline` inside `for line in proc.stdout` is
    # insufficient because a hanging agent produces no lines to iterate over.
    killed_by_watchdog = {"flag": False}
    def watchdog() -> None:
        time.sleep(max(max_seconds, 1))
        if proc.poll() is None:
            killed_by_watchdog["flag"] = True
            try:
                proc.kill()
            except Exception:
                pass
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    try:
        with open(run.stdout_path, "w") as sout, open(run.events_path, "w") as ev:
            for line in proc.stdout:
                sout.write(line)
                sout.flush()
                ev.write(line)
                ev.flush()
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            if AGENT_DONE in (block.get("text") or ""):
                                run.done_sentinel_seen = True
                elif event.get("type") == "result":
                    result_text = event.get("result") or ""
                    if AGENT_DONE in result_text:
                        run.done_sentinel_seen = True
                    # Codex CLI returns exit 0 even on API-level errors.
                    # Surface is_error / api_error_status so the orchestrator
                    # doesn't silently classify them as "didn't finish".
                    if event.get("is_error") is True:
                        api_status = event.get("api_error_status")
                        snippet = result_text[:200] if result_text else "api error"
                        run.error = f"api_error{'/'+str(api_status) if api_status else ''}: {snippet}"
        proc.wait(timeout=10)
        run.returncode = proc.returncode
        if killed_by_watchdog["flag"]:
            run.error = "timeout"
        # Also accept AGENT_DONE written to the agent's output.md — some
        # models interpret "end your response with X" as "write X at the
        # end of the file you're producing" rather than emitting it in the
        # streamed assistant text. Either location counts as done.
        if not run.done_sentinel_seen and run.output_path.exists():
            try:
                if AGENT_DONE in run.output_path.read_text():
                    run.done_sentinel_seen = True
            except Exception:
                pass
    except Exception as e:
        run.error = f"{type(e).__name__}: {e}"
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        run.ended_at = time.time()


def run_team(args: argparse.Namespace) -> int:
    team, template_path = load_config(args.template, args.config)
    run_id = generate_run_id(team.name)
    run_dir = RUNS_DIR / run_id
    log(f"run id: {run_id}")
    log(f"run dir: {run_dir.relative_to(REPO_ROOT)}")

    staged_ctx = stage_context(run_dir, args.context or [])
    init_run(run_dir, team, args.topic, staged_ctx, template_path)

    max_total_seconds = (args.max_minutes or team.max_total_minutes) * 60
    team_deadline = time.time() + max_total_seconds
    # Per-agent budget: in parallel mode each agent gets the full window;
    # in sequential mode divide by N so the team can't exceed max_total_minutes.
    if team.parallel:
        per_agent_seconds = max_total_seconds
    else:
        per_agent_seconds = max(60, max_total_seconds // max(1, len(team.agents)))

    runs: list[AgentRun] = []
    for a in team.agents:
        agent_dir = run_dir / "agents" / a.name
        agent_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(a.prompt_template, args.topic, staged_ctx, run_dir, a.name)
        runs.append(AgentRun(
            cfg=a, prompt=prompt,
            output_path=agent_dir / "output.md",
            events_path=agent_dir / "events.jsonl",
            stdout_path=agent_dir / "stdout.log",
        ))

    log(f"spawning {len(runs)} agent(s) ({'parallel' if team.parallel else 'sequential'}); budget {max_total_seconds//60}m")

    if team.parallel:
        threads = []
        for run in runs:
            t = threading.Thread(
                target=spawn_agent,
                args=(run, run_dir / "agents" / run.cfg.name, run_dir, per_agent_seconds),
                daemon=True,
            )
            t.start()
            threads.append(t)
            log(f"  → {run.cfg.name} ({run.cfg.model}) started")
        for t in threads:
            t.join()
    else:
        for run in runs:
            # Global watchdog: if the team's total budget is already spent,
            # skip remaining agents with a synthetic error rather than
            # overrunning.
            remaining = team_deadline - time.time()
            if remaining <= 0:
                run.error = "team budget exhausted before agent started"
                run.started_at = time.time()
                run.ended_at = run.started_at
                log(f"  → {run.cfg.name} SKIPPED (team budget exhausted)")
                continue
            # Cap this agent's individual budget to whatever's left in the
            # team budget, so the last agent can't outrun the group.
            agent_budget = int(min(per_agent_seconds, remaining))
            log(f"  → {run.cfg.name} ({run.cfg.model}) starting ({agent_budget}s budget)")
            spawn_agent(run, run_dir / "agents" / run.cfg.name, run_dir, agent_budget)

    # Extract structured summary from each agent's output.md if present.
    # Agents are prompted to end with ```json {"key_findings": [...], ...} ```.
    summary = {"team": team.name, "topic": args.topic, "agents": []}
    # Require the ```json fence to be at the start of a line (preceded by
    # newline or start of string) so inline mentions in prose (e.g., a
    # backtick-span containing `` ```json {...}`` ``) don't match.
    json_block_re = re.compile(r"(?:^|\n)```json\s*\n([\s\S]*?)\n```", re.MULTILINE)
    for run in runs:
        entry = {
            "name": run.cfg.name,
            "model": run.cfg.model,
            "done": run.done_sentinel_seen,
            "error": run.error,
            "duration_s": round(run.ended_at - run.started_at, 1) if run.ended_at else 0,
            "key_findings": [],
            "recommendation": None,
        }
        if run.output_path.exists():
            out_text = run.output_path.read_text()
            matches = json_block_re.findall(out_text)
            # Walk from last to first so we prefer the trailing summary over
            # in-prose format examples.
            for raw in reversed(matches):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict) and "key_findings" in parsed:
                        entry["key_findings"] = parsed.get("key_findings", [])
                        entry["recommendation"] = parsed.get("recommendation")
                        break
                except Exception:
                    continue
            else:
                if matches:
                    entry["json_parse_error"] = "no valid schema block found"
        summary["agents"].append(entry)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Generate REPORT.md
    report_path = run_dir / "REPORT.md"
    with open(report_path, "w") as f:
        f.write(f"# Team report: {team.name}\n\n")
        f.write(f"**Topic:** {args.topic}\n\n")
        f.write(f"**Started:** {datetime.datetime.now().isoformat()}\n\n")
        f.write(f"**Run dir:** `{run_dir.relative_to(REPO_ROOT)}`\n\n")
        f.write("---\n\n")
        f.write("## Per-agent outputs\n\n")
        for run in runs:
            dur = run.ended_at - run.started_at if run.ended_at else 0
            status = (
                "✓ done" if run.done_sentinel_seen else
                f"✗ {run.error}" if run.error else
                f"ended rc={run.returncode}"
            )
            f.write(f"### {run.cfg.name} ({run.cfg.model}) — {status} — {dur:.1f}s\n\n")
            f.write(f"_{run.cfg.motivation}_\n\n")
            if run.output_path.exists():
                f.write(run.output_path.read_text())
            else:
                f.write("_(no output.md produced)_\n")
            f.write("\n\n---\n\n")
        f.write("## Shared thread\n\n")
        thread_path = run_dir / "thread.md"
        if thread_path.exists():
            f.write(thread_path.read_text())

    log(f"report: {report_path.relative_to(REPO_ROOT)}")

    # Exit code: 0 if all agents produced output, 1 if any failed
    if any(r.error or not r.done_sentinel_seen for r in runs):
        failed = [r.cfg.name for r in runs if r.error or not r.done_sentinel_seen]
        log(f"partial success — agents without AGENT_DONE: {failed}")
        return 1
    log("all agents completed cleanly")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", help="template name from templates/ (e.g. gauntlet)")
    ap.add_argument("--config", help="path to custom config JSON")
    ap.add_argument("--topic", required=True, help="the topic / question / artifact under review")
    ap.add_argument("--context", nargs="*", help="repo-relative paths to stage into ./context/")
    ap.add_argument("--max-minutes", type=int, help="override template's max_total_minutes")
    return run_team(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
